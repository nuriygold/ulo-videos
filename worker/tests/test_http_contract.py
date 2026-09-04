import json
from pathlib import Path
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer


class HttpContractTests(unittest.TestCase):
    def test_authenticated_request_accepts_only_the_existing_queue_message(self):
        from worker.http_contract import authenticate_render_request

        self.assertEqual(
            authenticate_render_request(b'{"renderJobId":"rj_123"}', "Bearer shared-secret", "shared-secret"),
            "rj_123",
        )
        with self.assertRaises(PermissionError):
            authenticate_render_request(b'{"renderJobId":"rj_123"}', "Bearer wrong", "shared-secret")
        with self.assertRaises(ValueError):
            authenticate_render_request(b'{"jobId":"rj_123"}', "Bearer shared-secret", "shared-secret")

    def test_dispatch_runs_synchronously_and_returns_completed_result(self):
        from worker.service import dispatch_render_job

        result = dispatch_render_job("rj_123", object(), execute=lambda job_id, plane: {"jobId": job_id, "status": "completed"})
        self.assertEqual(result, {"jobId": "rj_123", "status": "completed"})

    def test_health_reports_not_ready_when_media_executable_is_missing(self):
        from worker.service import executable_status

        self.assertEqual(
            executable_status(which=lambda command: None, run=lambda argv: None),
            {"ok": False, "ffmpeg": False, "blender": False},
        )

    def test_post_only_accepts_render_jobs_path_and_completes_synchronously(self):
        from worker.service import RenderRequestHandler

        class ControlPlane: pass

        class Handler(RenderRequestHandler):
            control_plane_factory = ControlPlane
            render_executor = staticmethod(lambda job_id, control_plane: {"jobId": job_id, "status": "completed"})
            health_checker = staticmethod(lambda: {"ok": True, "ffmpeg": True, "blender": True})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            connection = HTTPConnection("127.0.0.1", port, timeout=3)
            connection.request("POST", "/not-render-jobs", body=b'{"renderJobId":"rj_123"}', headers={"Authorization": "Bearer shared-secret", "Content-Type": "application/json"})
            self.assertEqual(connection.getresponse().status, 405)
            connection.close()
            import os
            old_secret = os.environ.get("RENDER_WORKER_SECRET")
            os.environ["RENDER_WORKER_SECRET"] = "shared-secret"
            try:
                connection = HTTPConnection("127.0.0.1", port, timeout=3)
                connection.request("POST", "/render-jobs", body=b'{"renderJobId":"rj_123"}', headers={"Authorization": "Bearer shared-secret", "Content-Type": "application/json"})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read()), {"jobId": "rj_123", "status": "completed"})
                connection.close()
            finally:
                if old_secret is None:
                    del os.environ["RENDER_WORKER_SECRET"]
                else:
                    os.environ["RENDER_WORKER_SECRET"] = old_secret
        finally:
            server.shutdown()
            server.server_close()

    def test_root_docker_build_copies_worker_package_and_excludes_worker_env(self):
        root = Path(__file__).parents[2]
        dockerfile = (root / "worker" / "Dockerfile").read_text()
        dockerignore = (root / ".dockerignore").read_text() if (root / ".dockerignore").exists() else ""
        self.assertIn("COPY worker /app/worker", dockerfile)
        self.assertIn("blender-${BLENDER_VERSION}-linux-x64.tar.xz", dockerfile)
        self.assertIn("a31f524fa99a527d3d52b7f5aaa68c34e1a19d5a1c9473f79c5cc610fd5b10e9", dockerfile)
        self.assertIn("worker/.env", dockerignore)
        self.assertIn(".env", dockerignore)


if __name__ == "__main__":
    unittest.main()
