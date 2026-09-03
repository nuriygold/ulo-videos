"""Small Supabase REST and Vercel Blob client for the external worker."""

import json
import os
import shutil
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


class SupabaseBlobControlPlane:
    def __init__(self, *, supabase_url=None, service_role_key=None, blob_token=None):
        self.supabase_url = (supabase_url or os.environ["SUPABASE_URL"]).rstrip("/")
        self.service_role_key = service_role_key or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        self.blob_token = blob_token or os.environ["BLOB_READ_WRITE_TOKEN"]

    def _request(self, path, *, method="GET", payload=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"apikey": self.service_role_key, "Authorization": f"Bearer {self.service_role_key}"}
        if body is not None:
            headers.update({"Content-Type": "application/json", "Prefer": "return=representation"})
        with urlopen(Request(f"{self.supabase_url}/rest/v1/{path}", method=method, data=body, headers=headers), timeout=45) as response:
            raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else None

    def get_job(self, job_id):
        rows = self._request(f"render_jobs?id=eq.{quote(job_id, safe='')}&select=*")
        if not rows:
            raise ValueError("render job not found")
        return rows[0]

    def update_job(self, job_id, **fields):
        self._request(f"render_jobs?id=eq.{quote(job_id, safe='')}", method="PATCH", payload=fields)

    def download(self, source_url, destination):
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        request = Request(source_url, headers={"User-Agent": "ulo-videos-external-worker/1.0"})
        with urlopen(request, timeout=180) as response, target.open("wb") as output:
            shutil.copyfileobj(response, output)

    def upload_output(self, job, output_path):
        pathname = f"workspaces/{job['workspace_id']}/renders/{job['id']}.mp4"
        data = Path(output_path).read_bytes()
        request = Request(
            f"https://blob.vercel-storage.com/{pathname}", data=data, method="PUT",
            headers={
                "Authorization": f"Bearer {self.blob_token}", "x-api-version": "7",
                "x-content-type": "video/mp4", "Content-Type": "application/octet-stream",
            },
        )
        with urlopen(request, timeout=180) as response:
            blob = json.loads(response.read().decode("utf-8"))
        asset_id = f"asset_{job['id']}"
        asset = {
            "id": asset_id, "workspace_id": job["workspace_id"], "project_id": job["project_id"],
            "blob_key": pathname, "blob_url": blob["url"], "role": "render_output", "mime_type": "video/mp4", "bytes": len(data),
        }
        self._request("assets", method="POST", payload=asset)
        return asset_id
