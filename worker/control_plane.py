"""Small Supabase REST and Vercel Blob client for the external worker."""

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class SupabaseBlobControlPlane:
    def __init__(self, *, supabase_url=None, service_role_key=None, blob_token=None):
        self.supabase_url = (supabase_url or os.environ["SUPABASE_URL"]).rstrip("/")
        self.service_role_key = service_role_key or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        self.blob_token = blob_token or os.environ["BLOB_READ_WRITE_TOKEN"]

    def _request(self, path, *, method="GET", payload=None, prefer="return=representation"):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"apikey": self.service_role_key, "Authorization": f"Bearer {self.service_role_key}"}
        if body is not None:
            headers.update({"Content-Type": "application/json", "Prefer": prefer})
        try:
            with urlopen(Request(f"{self.supabase_url}/rest/v1/{path}", method=method, data=body, headers=headers), timeout=45) as response:
                raw = response.read()
        except HTTPError as error:
            try:
                detail = error.read().decode("utf-8", errors="replace").strip()
            except OSError:
                detail = ""
            suffix = f": {detail[:1000]}" if detail else ""
            raise RuntimeError(f"Supabase REST request failed ({error.code}){suffix}") from error
        return json.loads(raw.decode("utf-8")) if raw else None

    def get_job(self, job_id):
        rows = self._request(f"render_jobs?id=eq.{quote(job_id, safe='')}&select=*")
        if not rows:
            raise ValueError("render job not found")
        return rows[0]

    def update_job(self, job_id, **fields):
        rows = self._request(f"render_jobs?id=eq.{quote(job_id, safe='')}", method="PATCH", payload=fields)
        if rows == []:
            raise ValueError("render job not found during update")

    def claim_job(self, job_id, worker_id, *, now=None, lease_seconds=1800):
        if not worker_id:
            raise ValueError("worker_id is required to claim a render job")
        current = datetime.fromisoformat(now) if isinstance(now, str) else (now or datetime.now(timezone.utc))
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        now_value = current.isoformat()
        lease_value = (current + timedelta(seconds=lease_seconds)).isoformat()
        path = (
            f"render_jobs?id=eq.{quote(job_id, safe='')}"
            f"&status=eq.queued&or=(lease_expires_at.is.null,lease_expires_at.lt.{quote(now_value, safe='')})"
        )
        rows = self._request(
            path,
            method="PATCH",
            payload={
                "status": "preparing",
                "progress": 5,
                "worker_id": worker_id,
                "started_at": now_value,
                "lease_expires_at": lease_value,
            },
            prefer="return=representation",
        )
        return rows[0] if rows else None

    def transition_job(self, job_id, worker_id, expected_status, status, **fields):
        payload = {"status": status, **fields}
        path = (
            f"render_jobs?id=eq.{quote(job_id, safe='')}"
            f"&status=eq.{quote(expected_status, safe='')}"
            f"&worker_id=eq.{quote(worker_id, safe='')}"
        )
        rows = self._request(path, method="PATCH", payload=payload, prefer="return=representation")
        return bool(rows)

    def download(self, source_url, destination):
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        request = Request(source_url, headers={"User-Agent": "ulo-videos-external-worker/1.0"})
        with urlopen(request, timeout=180) as response, target.open("wb") as output:
            shutil.copyfileobj(response, output)

    def upload_output(self, job, output_path):
        pathname = f"workspaces/{job['workspace_id']}/renders/{job['id']}.mp4"
        path = Path(output_path)
        size = path.stat().st_size
        with path.open("rb") as data:
            request = Request(
                f"https://blob.vercel-storage.com/{pathname}", data=data, method="PUT",
                headers={
                    "Authorization": f"Bearer {self.blob_token}", "x-api-version": "7",
                    "x-content-type": "video/mp4", "Content-Type": "application/octet-stream",
                    "Content-Length": str(size),
                },
            )
            with urlopen(request, timeout=180) as response:
                blob = json.loads(response.read().decode("utf-8"))
        asset_id = f"asset_{job['id']}"
        asset = {
            "id": asset_id, "workspace_id": job["workspace_id"], "project_id": job["project_id"],
            "blob_key": pathname, "blob_url": blob["url"], "role": "render_output", "mime_type": "video/mp4", "bytes": size,
        }
        self._request("assets?on_conflict=id", method="POST", payload=asset, prefer="return=representation,resolution=merge-duplicates")
        return asset_id
