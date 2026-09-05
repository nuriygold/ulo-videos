import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch


class ControlPlaneTests(unittest.TestCase):
    def test_claim_job_only_updates_a_queued_unleased_job(self):
        from worker.control_plane import SupabaseBlobControlPlane

        class ControlPlane(SupabaseBlobControlPlane):
            def __init__(self):
                self.calls = []

            def _request(self, path, *, method="GET", payload=None, prefer=None):
                self.calls.append((path, method, payload, prefer))
                return [{"id": "rj_123", "status": "preparing", "worker_id": "worker-a"}]

        control = ControlPlane()
        claimed = control.claim_job("rj_123", "worker-a", now="2026-09-05T12:00:00+00:00", lease_seconds=900)

        self.assertEqual(claimed["status"], "preparing")
        path, method, payload, prefer = control.calls[0]
        self.assertIn("status=eq.queued", path)
        self.assertIn("worker_id", payload)
        self.assertEqual(method, "PATCH")
        self.assertEqual(prefer, "return=representation")

    def test_transition_job_returns_false_when_the_expected_owner_or_status_is_stale(self):
        from worker.control_plane import SupabaseBlobControlPlane

        class ControlPlane(SupabaseBlobControlPlane):
            def __init__(self):
                self.calls = []

            def _request(self, path, *, method="GET", payload=None, prefer=None):
                self.calls.append((path, method, payload, prefer))
                return []

        control = ControlPlane()
        self.assertFalse(control.transition_job("rj_123", "worker-a", "rendering", "encoding", progress=70))
        path, method, payload, _ = control.calls[0]
        self.assertIn("status=eq.rendering", path)
        self.assertIn("worker_id=eq.worker-a", path)
        self.assertEqual(method, "PATCH")
        self.assertEqual(payload, {"status": "encoding", "progress": 70})

    def test_rest_http_errors_include_the_safe_upstream_response_body(self):
        from worker.control_plane import SupabaseBlobControlPlane

        error = HTTPError(
            "https://supabase.example/rest/v1/render_jobs",
            400,
            "Bad Request",
            {},
            io.BytesIO(b'{"message":"worker_id column is missing"}'),
        )

        class ControlPlane(SupabaseBlobControlPlane):
            def __init__(self):
                self.supabase_url = "https://supabase.example"
                self.service_role_key = "service-role"

        with patch("worker.control_plane.urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, r"Supabase REST request failed \(400\): \{\"message\":\"worker_id column is missing\"\}"):
                ControlPlane()._request("render_jobs?select=*")

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
