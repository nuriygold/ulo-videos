import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ControlPlaneTests(unittest.TestCase):
    def test_update_job_detects_empty_patch_result(self):
        from worker.control_plane import SupabaseBlobControlPlane

        class ControlPlane(SupabaseBlobControlPlane):
            def __init__(self): pass
            def _request(self, path, *, method="GET", payload=None):
                self.path = path
                self.method = method
                self.payload = payload
                return []

        control = ControlPlane()
        with self.assertRaisesRegex(ValueError, "render job not found"):
            control.update_job("rj_missing", status="completed", progress=100)
        self.assertEqual(control.method, "PATCH")

    def test_upload_output_streams_mp4_and_upserts_asset_idempotently(self):
        from worker.control_plane import SupabaseBlobControlPlane

        requests = []

        class ControlPlane(SupabaseBlobControlPlane):
            def __init__(self):
                self.blob_token = "blob-token"
            def _request(self, path, *, method="GET", payload=None, prefer=None):
                requests.append((path, method, payload, prefer))
                return [payload]

        def fake_urlopen(request, timeout):
            self.assertTrue(hasattr(request.data, "read"), "upload body must be a stream, not bytes")
            self.assertEqual(request.get_header("Content-length"), "7")
            self.assertEqual(request.data.read(), b"mp4data")
            return io.BytesIO(json.dumps({"url": "https://blob.example/render.mp4"}).encode())

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output.mp4"
            output.write_bytes(b"mp4data")
            with patch("worker.control_plane.urlopen", fake_urlopen):
                asset_id = ControlPlane().upload_output({"id": "rj_123", "workspace_id": "w_1", "project_id": "p_1"}, output)

        self.assertEqual(asset_id, "asset_rj_123")
        self.assertEqual(requests, [("assets?on_conflict=id", "POST", {
            "id": "asset_rj_123", "workspace_id": "w_1", "project_id": "p_1",
            "blob_key": "workspaces/w_1/renders/rj_123.mp4", "blob_url": "https://blob.example/render.mp4",
            "role": "render_output", "mime_type": "video/mp4", "bytes": 7,
        }, "return=representation,resolution=merge-duplicates")])


if __name__ == "__main__":
    unittest.main()
