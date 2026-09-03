"""Small provider-neutral callback client for the hosted render control plane."""

import json
from urllib.request import Request, urlopen


def report_status(control_plane_url, job_id, secret, status, progress, **fields):
    if not control_plane_url or not job_id or not secret:
        raise ValueError("control plane URL, job ID, and worker secret are required")
    payload = {"status": status, "progress": progress, **fields}
    request = Request(
        f"{control_plane_url.rstrip('/')}/api/render-jobs/{job_id}/status",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {secret}"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        if response.status >= 300:
            raise RuntimeError(f"control plane rejected status update ({response.status})")
        return json.loads(response.read() or b"{}")
