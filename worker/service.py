"""Deployable authenticated HTTP endpoint for external cloud rendering."""

import json
import os
import shutil
import subprocess
import tempfile
from threading import Thread
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .control_plane import SupabaseBlobControlPlane
from .http_contract import authenticate_render_request
from .pipeline import build_composite_plan


def _run(argv):
    result = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=900)
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:] or f"{argv[0]} failed")


def execute_render_job(job_id, control_plane, *, worker_id=None, run_command=_run):
    """Render one immutable job snapshot and update its existing Supabase record."""
    job = control_plane.get_job(job_id)
    if job.get("status") == "completed":
        return {
            "jobId": job_id,
            "status": "completed",
            "progress": 100,
            "outputAssetId": job.get("output_asset_id"),
        }
    workdir = Path(tempfile.mkdtemp(prefix=f"ulo-{job_id}-"))
    worker_id = worker_id or os.environ.get("WORKER_ID", "blender-ffmpeg-worker")
    try:
        control_plane.update_job(job_id, status="preparing", progress=5, worker_id=worker_id)
        plan = build_composite_plan(job["spec_snapshot"], workdir)
        control_plane.update_job(job_id, status="downloading_assets", progress=15)
        control_plane.download(plan.source_url, plan.source)
        control_plane.download(plan.character_url, plan.character)
        control_plane.download(plan.logo_url, plan.logo_source)
        control_plane.update_job(job_id, status="building_scene", progress=30)
        if plan.rasterize_logo:
            run_command(["rsvg-convert", str(plan.logo_source), "-o", str(plan.logo_image)])
        run_command(plan.blender_argv)
        control_plane.update_job(job_id, status="rendering", progress=55)
        control_plane.update_job(job_id, status="encoding", progress=70)
        run_command(plan.ffmpeg_argv)
        if not Path(plan.output).is_file():
            raise RuntimeError("FFmpeg completed without producing output.mp4")
        control_plane.update_job(job_id, status="uploading", progress=85)
        output_asset_id = control_plane.upload_output(job, plan.output)
        completed = {"status": "completed", "progress": 100, "output_asset_id": output_asset_id}
        control_plane.update_job(job_id, **completed)
        return {"jobId": job_id, "outputAssetId": output_asset_id, **completed}
    except Exception as error:
        failure = {"status": "failed", "progress": 100, "error_code": "render_failed", "error_message": str(error)[:2000]}
        control_plane.update_job(job_id, **failure)
        raise
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def dispatch_render_job(job_id, control_plane, *, thread_class=Thread):
    """Acknowledge a queue delivery before the long-running render begins."""
    thread = thread_class(target=execute_render_job, args=(job_id, control_plane), daemon=True)
    thread.start()
    return {"accepted": True, "jobId": job_id}


class RenderRequestHandler(BaseHTTPRequestHandler):
    server_version = "ulo-videos-external-worker/1.0"

    def _json(self, status, body):
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.path == "/healthz":
            self._json(HTTPStatus.OK, {"ready": True, "worker": "blender-ffmpeg"})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length < 1 or content_length > 16_384:
                raise ValueError("request body must be between 1 and 16384 bytes")
            job_id = authenticate_render_request(self.rfile.read(content_length), self.headers.get("Authorization", ""), os.environ.get("RENDER_WORKER_SECRET"))
            result = dispatch_render_job(job_id, SupabaseBlobControlPlane())
            self._json(HTTPStatus.ACCEPTED, result)
        except PermissionError as error:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": str(error)})
        except ValueError as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except Exception as error:
            self._json(HTTPStatus.BAD_GATEWAY, {"error": str(error)})

    def log_message(self, format, *args):
        print(format % args, flush=True)


def main():
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), RenderRequestHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
