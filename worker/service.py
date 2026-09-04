"""Deployable authenticated HTTP endpoint for external cloud rendering."""

import glob
import json
import os
import shutil
import subprocess
import tempfile
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .control_plane import SupabaseBlobControlPlane
from .http_contract import authenticate_render_request
from .pipeline import HOLD_SECONDS, build_composite_plan


def _run(argv):
    result = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=900)
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:] or f"{argv[0]} failed")


def _character_frame_paths(frame_pattern):
    pattern = str(frame_pattern).replace("%05d", "*")
    return sorted(Path(item) for item in glob.glob(pattern))


def prepare_character_frame_directory(frame_pattern):
    frame_dir = Path(frame_pattern).parent
    if frame_dir.exists():
        shutil.rmtree(frame_dir)
    frame_dir.mkdir(parents=True, exist_ok=True)
    return time.time_ns()


def verify_character_frames(frame_pattern, expected_frames, started_at_ns):
    frames = _character_frame_paths(frame_pattern)
    expected_names = {str(frame_pattern) % frame for frame in range(1, expected_frames + 1)}
    actual_names = {str(frame) for frame in frames}
    missing = sorted(expected_names - actual_names)
    unexpected = sorted(actual_names - expected_names)
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing {len(missing)} expected character frame(s)")
        if unexpected:
            details.append(f"found {len(unexpected)} unexpected character frame(s)")
        raise RuntimeError("Blender completed without producing a fresh complete character frame sequence: " + "; ".join(details))
    stale = [frame for frame in frames if not frame.is_file() or frame.stat().st_size <= 0 or frame.stat().st_mtime_ns < started_at_ns]
    if stale:
        raise RuntimeError("Blender completed with stale, empty, or invalid character frame(s)")


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
        frame_start_ns = prepare_character_frame_directory(plan.character_frames)
        run_command(plan.blender_argv)
        verify_character_frames(plan.character_frames, HOLD_SECONDS * int(job["spec_snapshot"]["output"]["fps"]), frame_start_ns)
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


def dispatch_render_job(job_id, control_plane, *, execute=execute_render_job):
    """Run synchronously so a successful response cannot lose a daemon thread."""
    return execute(job_id, control_plane)


def executable_status(*, which=shutil.which, run=subprocess.run):
    def ready(command, arguments):
        executable = which(command)
        if executable is None:
            return False
        try:
            result = run([executable, *arguments], capture_output=True, text=True, check=False, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return False
        return result is not None and result.returncode == 0

    ffmpeg = ready("ffmpeg", ["-version"])
    blender = ready("blender", ["--background", "--version"])
    rsvg_convert = ready("rsvg-convert", ["--version"])
    return {"ok": ffmpeg and blender and rsvg_convert, "ffmpeg": ffmpeg, "blender": blender, "rsvg_convert": rsvg_convert}


class RenderRequestHandler(BaseHTTPRequestHandler):
    server_version = "ulo-videos-external-worker/1.0"
    control_plane_factory = SupabaseBlobControlPlane
    render_executor = staticmethod(execute_render_job)
    health_checker = staticmethod(executable_status)

    def _json(self, status, body):
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.path == "/healthz":
            status = self.health_checker()
            self._json(HTTPStatus.OK if status["ok"] else HTTPStatus.SERVICE_UNAVAILABLE, {
                "ok": status["ok"], "mode": "external_worker",
                "capabilities": {"freezeResume": True, "logo": True, "captions": True, "character": True, "sourceAudio": False, "speech": False, "lipSync": False, "characterFormats": [".blend", ".gltf", ".glb", ".fbx"]},
                **status,
            })
        elif self.path == "/render-jobs":
            self._method_not_allowed()
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self):
        if self.path != "/render-jobs":
            self._method_not_allowed()
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length < 1 or content_length > 16_384:
                raise ValueError("request body must be between 1 and 16384 bytes")
            job_id = authenticate_render_request(self.rfile.read(content_length), self.headers.get("Authorization", ""), os.environ.get("RENDER_WORKER_SECRET"))
            result = dispatch_render_job(job_id, self.control_plane_factory(), execute=self.render_executor)
            self._json(HTTPStatus.OK, result)
        except PermissionError as error:
            self._json(HTTPStatus.UNAUTHORIZED, {"error": str(error)})
        except ValueError as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except Exception as error:
            self._json(HTTPStatus.BAD_GATEWAY, {"error": str(error)})

    def _method_not_allowed(self):
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self.send_header("Allow", "POST")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_OPTIONS = _method_not_allowed
    do_HEAD = _method_not_allowed

    def log_message(self, format, *args):
        print(format % args, flush=True)


def main():
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), RenderRequestHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
