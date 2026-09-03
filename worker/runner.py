"""Deterministic worker-side render planning and execution primitives."""

import subprocess
from pathlib import Path

from ulo_videos.scene_contract import validate_scene


def build_worker_plan(job, workdir):
    """Build the first real cloud-worker FFmpeg pass from an immutable job."""
    if not isinstance(job, dict) or not isinstance(job.get("spec_snapshot"), dict):
        raise ValueError("render job must contain a spec_snapshot object")
    scene = validate_scene(job["spec_snapshot"])
    root = Path(workdir).resolve()
    source = root / "input" / Path(scene["source"]["video"]).name
    output = root / "output.mp4"
    trigger = scene["trigger"]["value"]
    width = scene["output"]["width"]
    height = scene["output"]["height"]
    fps = scene["output"]["fps"]
    filters = f"trim=end={trigger},tpad=stop_mode=clone:stop_duration=2,scale={width}:{height},fps={fps}"
    return {
        "argv": [
            "ffmpeg", "-y", "-i", str(source), "-vf", filters,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", "-f", "mp4", str(output),
        ],
        "input": str(source),
        "output": str(output),
    }


def run_worker_job(job, workdir, *, runner=subprocess.run):
    """Execute the minimal worker pass; asset transfer is injected by callers."""
    plan = build_worker_plan(job, workdir)
    Path(workdir).mkdir(parents=True, exist_ok=True)
    result = runner(plan["argv"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:] or "ffmpeg render failed")
    if not Path(plan["output"]).is_file():
        raise RuntimeError("ffmpeg completed without producing the output MP4")
    return plan


def execute_job(job, workdir, *, download, upload, update, runner=subprocess.run):
    """Run the first cloud slice with provider-neutral I/O callbacks.

    ``download`` receives a Blob/object-storage key and a local destination;
    ``upload`` receives the completed local output and returns an asset id.
    ``update`` receives small status dictionaries suitable for a queue/API.
    """
    job_id = job["id"]
    root = Path(workdir).resolve()
    try:
        update({"job_id": job_id, "status": "preparing", "progress": 5})
        plan = build_worker_plan(job, root)
        source_key = job["spec_snapshot"]["source"]["video"]
        update({"job_id": job_id, "status": "downloading_assets", "progress": 15})
        download(source_key, Path(plan["input"]))
        update({"job_id": job_id, "status": "rendering", "progress": 45})
        result = runner(plan["argv"], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr[-2000:] or "ffmpeg render failed")
        if not Path(plan["output"]).is_file():
            raise RuntimeError("ffmpeg completed without producing the output MP4")
        update({"job_id": job_id, "status": "uploading", "progress": 85})
        output_asset_id = upload(Path(plan["output"]))
        completed = {"job_id": job_id, "status": "completed", "progress": 100, "output_asset_id": output_asset_id}
        update(completed)
        return completed
    except Exception as error:
        failed = {"job_id": job_id, "status": "failed", "progress": 100, "error_code": "render_failed", "error_message": str(error)}
        update(failed)
        return failed
