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
            {"ok": False, "ffmpeg": False, "blender": False, "rsvg_convert": False},
        )

    def test_health_is_unauthenticated_and_requires_ffmpeg_blender_and_rsvg_convert(self):
        from worker.service import RenderRequestHandler

        class Handler(RenderRequestHandler):
            health_checker = staticmethod(lambda: {"ok": True, "ffmpeg": True, "blender": True, "rsvg_convert": True})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            connection.request("GET", "/healthz")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read()), {"ok": True, "mode": "external_worker", "capabilities": {"freezeResume": True, "logo": True, "captions": True, "character": True, "sourceAudio": False, "speech": False, "lipSync": False, "characterFormats": [".blend", ".gltf", ".glb", ".fbx"]}, "ffmpeg": True, "blender": True, "rsvg_convert": True})
            connection.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_post_only_accepts_render_jobs_path_and_completes_synchronously(self):
        from worker.service import RenderRequestHandler

        class ControlPlane: pass

        class Handler(RenderRequestHandler):
            control_plane_factory = ControlPlane
            render_executor = staticmethod(lambda job_id, control_plane: {"jobId": job_id, "status": "completed"})
            health_checker = staticmethod(lambda: {"ok": True, "ffmpeg": True, "blender": True, "rsvg_convert": True})

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
        self.assertIn("FROM --platform=linux/amd64", dockerfile)
        self.assertIn('test "${TARGETARCH}" = "amd64"', dockerfile)
        self.assertIn("worker/.env", dockerignore)
        self.assertIn(".env", dockerignore)

    def test_worker_integration_workflow_runs_amd64_image_and_fixture_script(self):
        workflow = (Path(__file__).parents[2] / ".github" / "workflows" / "worker-integration.yml").read_text()
        self.assertIn("ubuntu-24.04", workflow)
        self.assertIn("platforms: linux/amd64", workflow)
        self.assertIn("--platform linux/amd64", workflow)
        self.assertIn("worker.integration_fixtures", workflow)

    def test_integration_fixture_script_covers_render_and_character_cases(self):
        script = (Path(__file__).parents[1] / "integration_fixtures.py").read_text()
        for expected in (
            "require_health",
            "render_demo_asset",
            "verify_composite",
            "verify_character_fixtures",
            '".blend", ".gltf", ".glb", ".fbx"',
            "missing_camera",
            "missing_armature",
            "missing_gesture",
            "ambiguous_gesture",
            "missing-sidecar.gltf",
            "ffprobe",
            "sampled-frames",
            "demo-character.blend",
            "DISCOVER_ACTIONS_SCRIPT",
        ):
            self.assertIn(expected, script)


if __name__ == "__main__":
    unittest.main()
