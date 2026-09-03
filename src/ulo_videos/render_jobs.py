"""Immutable render-job snapshots and worker state transitions."""

from copy import deepcopy


STATES = ("queued", "preparing", "downloading_assets", "generating_audio", "lip_sync", "building_scene", "rendering", "encoding", "uploading", "completed", "failed")
_TERMINAL = {"completed", "failed"}


class InvalidTransition(ValueError):
    """Raised when a worker attempts an invalid job transition."""


def create_job(job_id, workspace_id, shot_id, spec_snapshot):
    return {
        "id": str(job_id),
        "workspace_id": str(workspace_id),
        "shot_id": str(shot_id),
        "spec_snapshot": deepcopy(spec_snapshot),
        "status": "queued",
        "progress": 0,
        "attempt": 1,
        "output_asset_id": None,
        "error_code": None,
        "error_message": None,
    }


def transition_job(job, status, *, progress=None, output_asset_id=None, error_code=None, error_message=None):
    if status not in STATES:
        raise InvalidTransition(f"unknown render job state: {status}")
    current = job.get("status")
    if current in _TERMINAL or (status == "queued" and current != "queued"):
        raise InvalidTransition(f"cannot transition render job from {current} to {status}")
    if status != "failed" and current != "queued" and STATES.index(status) <= STATES.index(current):
        raise InvalidTransition(f"cannot transition render job from {current} to {status}")
    updated = dict(job)
    updated["status"] = status
    updated["progress"] = 100 if status == "completed" else (progress if progress is not None else updated.get("progress", 0))
    if output_asset_id is not None:
        updated["output_asset_id"] = output_asset_id
    if status == "failed":
        updated["error_code"] = error_code or "worker_failed"
        updated["error_message"] = error_message or "render worker failed"
    return updated
