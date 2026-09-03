"""Small HTTP worker contract used by the first hosted render slice."""

import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen


def download_request(url):
    return Request(url, headers={"User-Agent": "ulo-videos-render-worker/1.0"})


def queue_message(raw_body, authorization, expected_secret):
    if not expected_secret or authorization != f"Bearer {expected_secret}":
        raise PermissionError("worker authorization required")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("request body must be JSON") from error
    job_id = payload.get("renderJobId") if isinstance(payload, dict) else None
    if not isinstance(job_id, str) or not job_id.startswith("rj_") or len(job_id) > 124:
        raise ValueError("renderJobId is required")
    return {"renderJobId": job_id}


def ffmpeg_command(source, output, trigger, width, height, fps):
    filters = f"trim=end={trigger},tpad=stop_mode=clone:stop_duration=2,scale={width}:{height},fps={fps}"
    return ["ffmpeg", "-y", "-i", source, "-vf", filters, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", "-f", "mp4", output]


def _json_request(url, *, method="GET", token=None, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"apikey": token, "Authorization": f"Bearer {token}"} if token else {}
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["Prefer"] = "return=representation"
    with urlopen(Request(url, data=body, headers=headers, method=method), timeout=45) as response:
        raw = response.read()
    return json.loads(raw.decode()) if raw else None


def _update_job(job_id, *, status, progress, output_asset_id=None, error_code=None, error_message=None):
    base = os.environ["SUPABASE_URL"].rstrip("/")
    token = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    update = {"status": status, "progress": progress}
    if output_asset_id:
        update["output_asset_id"] = output_asset_id
    if error_code:
        update["error_code"] = error_code
    if error_message:
        update["error_message"] = error_message[:2000]
    _json_request(f"{base}/rest/v1/render_jobs?id=eq.{job_id}", method="PATCH", token=token, payload=update)


def _ffmpeg_binary():
    existing = shutil.which("ffmpeg")
    if existing:
        return existing
    target = Path(tempfile.gettempdir()) / "ulo-ffmpeg" / "ffmpeg"
    if target.is_file():
        return str(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    archive = target.with_suffix(".tar.xz")
    url = os.environ.get("FFMPEG_STATIC_URL", "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz")
    with urlopen(url, timeout=120) as response, archive.open("wb") as output:
        shutil.copyfileobj(response, output)
    with tarfile.open(archive, mode="r:xz") as package:
        member = next(item for item in package.getmembers() if item.name.endswith("/ffmpeg") and item.isfile())
        with package.extractfile(member) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)
    target.chmod(target.stat().st_mode | stat.S_IXUSR)
    archive.unlink(missing_ok=True)
    return str(target)


def _put_blob(pathname, data, token):
    request = Request(
        f"https://blob.vercel-storage.com/{pathname}",
        data=data,
        method="PUT",
        headers={"Authorization": f"Bearer {token}", "x-api-version": "7", "x-content-type": "video/mp4", "Content-Type": "application/octet-stream"},
    )
    with urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode())


def render_cloud_job(job_id, callback_origin):
    """Execute the first hosted pass synchronously inside the Vercel worker."""
    base = os.environ["SUPABASE_URL"].rstrip("/")
    token = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    rows = _json_request(f"{base}/rest/v1/render_jobs?id=eq.{job_id}&limit=1", token=token)
    if not rows:
        raise ValueError("render job not found")
    job = rows[0]
    scene = job["spec_snapshot"]
    source_url = scene["source"]["video"]
    output = Path(tempfile.mkdtemp(prefix=f"ulo-{job_id}-"))
    source = output / "input.mp4"
    rendered = output / "output.mp4"
    try:
        _update_job(job_id, status="preparing", progress=5)
        _update_job(job_id, status="downloading_assets", progress=15)
        with urlopen(download_request(source_url), timeout=120) as response, source.open("wb") as destination:
            shutil.copyfileobj(response, destination)
        _update_job(job_id, status="rendering", progress=45)
        command = ffmpeg_command(str(source), str(rendered), scene["trigger"]["value"], scene["output"]["width"], scene["output"]["height"], scene["output"]["fps"])
        command[0] = _ffmpeg_binary()
        result = subprocess.run(command, capture_output=True, text=True, timeout=240, check=False)
        if result.returncode or not rendered.is_file():
            raise RuntimeError(result.stderr[-2000:] or "ffmpeg did not produce output.mp4")
        _update_job(job_id, status="uploading", progress=85)
        pathname = f"workspaces/{job['workspace_id']}/renders/{job_id}.mp4"
        blob = _put_blob(pathname, rendered.read_bytes(), os.environ["BLOB_READ_WRITE_TOKEN"])
        asset_id = f"asset_{job_id}"
        _json_request(f"{base}/rest/v1/assets", method="POST", token=token, payload={"id": asset_id, "workspace_id": job["workspace_id"], "project_id": job["project_id"], "blob_key": pathname, "blob_url": blob["url"], "role": "render_output", "mime_type": "video/mp4", "bytes": rendered.stat().st_size})
        _update_job(job_id, status="completed", progress=100, output_asset_id=asset_id)
        return {"jobId": job_id, "status": "completed", "outputAssetId": asset_id}
    except Exception as error:
        _update_job(job_id, status="failed", progress=100, error_code="render_failed", error_message=str(error))
        raise
    finally:
        shutil.rmtree(output, ignore_errors=True)
