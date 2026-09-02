"""HTTP application tests against a real locally bound server.

Every request goes through `http.server` over a loopback socket, so routing,
status codes, headers, and JSON bodies are verified as a browser would see
them — no handler mocks.
"""

import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from prompt_to_shot.renderers import Toolchain
from prompt_to_shot.server import (
    default_project_root,
    default_static_dir,
    make_server,
    normalize_form_payload,
)
from prompt_to_shot.templates import compile_scene, serialize_scene


def form_payload():
    """A payload exactly as the browser form submits it: every field is text."""
    return {
        "template": "interruption_spokescharacter_v1",
        "background_video": "assets/house_leak.mp4",
        "pause_at": "7.4",
        "character": {
            "asset": "assets/characters/lizard.blend",
            "position": "foreground_right",
            "entrance": "pop_in",
            "gesture": "shrug_and_point",
        },
        "dialogue": {
            "text": "Every landlord knows real estate isn't passive.",
            "voice": "local_voice_01",
            "lip_sync": "rhubarb",
        },
        "branding": {"logo": "assets/logo.svg", "caption_style": "lower_third"},
        "output": {"resolution": "1920x1080", "fps": "30", "format": "mp4"},
    }


def typed_payload():
    """form_payload with the values the server normalizes before compiling."""
    payload = json.loads(json.dumps(form_payload()))
    payload["pause_at"] = 7.4
    payload["output"]["resolution"] = [1920, 1080]
    payload["output"]["fps"] = 30
    return payload


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        root = Path(tempfile.mkdtemp(prefix="prompt-to-shot-server-")).resolve()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.project_root = root
        for relative in (
            "assets/house_leak.mp4",
            "assets/characters/lizard.blend",
            "assets/logo.svg",
        ):
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            (root / relative).touch()
        self.static_dir = root / "www"
        self.static_dir.mkdir()
        self.write_static("index.html", "<!doctype html><title>scene form</title>\n")
        self.write_static("app.js", "// form behavior\n")
        self.write_static("styles.css", "body { margin: 0; }\n")
        self.toolchain = Toolchain(
            lookup=lambda name: "/fake/bin/ffmpeg" if name == "ffmpeg" else None,
            filter_probe=lambda tool, name: False,
        )
        self.start_server()

    def start_server(self, **overrides):
        options = {
            "static_dir": self.static_dir,
            "project_root": self.project_root,
            "toolchain": self.toolchain,
        }
        options.update(overrides)
        server = make_server("127.0.0.1", 0, **options)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self._stop, server, thread)
        self.server = server
        self.base_url = f"http://127.0.0.1:{server.server_port}"

    @staticmethod
    def _stop(server, thread):
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    def write_static(self, name, text):
        (self.static_dir / name).write_text(text, encoding="utf-8")

    def request(self, path, *, method="GET", body=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        headers = {"Content-Type": "application/json"} if data is not None else {}
        request = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, dict(response.headers.items()), response.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, dict(error.headers.items()), error.read()

    def post_spec(self, payload):
        return self.request("/api/spec", method="POST", body=json.dumps(payload))


class StaticFileTests(ServerTestCase):
    def test_serves_the_form_page_at_root(self):
        for path in ("/", "/index.html"):
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 200)
                self.assertTrue(headers["Content-Type"].startswith("text/html"))
                self.assertIn(b"<!doctype html>", body)

    def test_serves_the_script_and_stylesheet(self):
        for path, content_type, marker in (
            ("/app.js", "text/javascript", b"// form behavior"),
            ("/styles.css", "text/css", b"body { margin: 0; }"),
        ):
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 200)
                self.assertTrue(headers["Content-Type"].startswith(content_type))
                self.assertIn(marker, body)

    def test_returns_404_for_unknown_paths(self):
        for path in ("/missing.png", "/api/unknown"):
            with self.subTest(path=path):
                status, _, body = self.request(path)
                self.assertEqual(status, 404)
                self.assertIn("not found", json.loads(body)["error"])

    def test_returns_404_when_a_static_file_is_missing(self):
        (self.static_dir / "app.js").unlink()

        status, _, body = self.request("/app.js")

        self.assertEqual(status, 404)
        self.assertIn("app.js", json.loads(body)["error"])

    def test_rejects_traversal_paths(self):
        for path in ("/../outside", "/%2e%2e/outside"):
            with self.subTest(path=path):
                status, _, _ = self.request(path)
                self.assertEqual(status, 404)


class SpecApiTests(ServerTestCase):
    def test_post_valid_spec_returns_compiled_scene_and_plan(self):
        status, _, body = self.post_spec(form_payload())

        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["scene"], compile_scene(typed_payload()))
        scene = payload["scene"]
        self.assertEqual(scene["pause_at"], 7.4)
        self.assertEqual(scene["output"]["resolution"], [1920, 1080])
        self.assertEqual(scene["output"]["fps"], 30)
        self.assertIsNone(payload["plan_error"])
        plan = payload["plan"]
        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["argv"][0], "/fake/bin/ffmpeg")
        self.assertIn("-an", plan["argv"])
        filters = plan["argv"][plan["argv"].index("-vf") + 1]
        self.assertIn("trim=end=7.4", filters)
        self.assertIn("scale=1920:1080", filters)
        self.assertEqual(
            plan["output"]["path"], str(self.project_root / "build" / "preview.mp4")
        )
        self.assertEqual(plan["output"]["resolution"], [1920, 1080])
        self.assertEqual(plan["output"]["fps"], 30)
        self.assertEqual(plan["missing_assets"], [])
        self.assertFalse(plan["captions"]["applied"])
        self.assertIn("drawtext", plan["captions"]["reason"])

    def test_post_reports_validation_errors_as_422(self):
        payload = form_payload()
        del payload["dialogue"]

        status, _, body = self.post_spec(payload)

        self.assertEqual(status, 422)
        error = json.loads(body)["error"]
        self.assertIn("missing required field", error)
        self.assertIn("dialogue", error)

    def test_post_passes_unconvertible_text_to_the_validator(self):
        payload = form_payload()
        payload["pause_at"] = "soon"
        status, _, body = self.post_spec(payload)
        self.assertEqual(status, 422)
        self.assertEqual(json.loads(body)["error"], "pause_at must be numeric")

        payload = form_payload()
        payload["output"]["resolution"] = "very wide"
        status, _, body = self.post_spec(payload)
        self.assertEqual(status, 422)
        self.assertIn("output.resolution", json.loads(body)["error"])

    def test_post_malformed_json_returns_400(self):
        for body_text in ("{not json", ""):
            with self.subTest(body=body_text):
                status, _, body = self.request(
                    "/api/spec", method="POST", body=body_text
                )
                self.assertEqual(status, 400)
                self.assertIn("JSON", json.loads(body)["error"])

    def test_post_unknown_route_returns_404(self):
        status, _, _ = self.request("/api/unknown", method="POST", body="{}")

        self.assertEqual(status, 404)

    def test_wrong_methods_are_rejected_with_405(self):
        status, _, _ = self.request("/api/spec")
        self.assertEqual(status, 405)

        status, _, _ = self.request("/api/tools", method="POST", body="{}")
        self.assertEqual(status, 405)

    def test_missing_ffmpeg_returns_scene_without_a_plan(self):
        self.start_server(toolchain=Toolchain(lookup=lambda name: None))

        status, _, body = self.post_spec(form_payload())

        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["scene"], compile_scene(typed_payload()))
        self.assertIsNone(payload["plan"])
        self.assertIn("ffmpeg", payload["plan_error"])

    def test_post_with_unsafe_asset_path_returns_422(self):
        payload = form_payload()
        payload["background_video"] = "/etc/house_leak.mp4"

        status, _, body = self.post_spec(payload)

        self.assertEqual(status, 422)
        self.assertIn("background_video", json.loads(body)["error"])


class SpecDownloadTests(ServerTestCase):
    def test_download_returns_canonical_scene_json_after_a_post(self):
        self.post_spec(form_payload())

        status, headers, body = self.request("/api/spec/download")

        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        self.assertIn("attachment", headers.get("Content-Disposition", ""))
        text = body.decode("utf-8")
        expected = serialize_scene(compile_scene(typed_payload()))
        self.assertEqual(text, expected)
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(json.loads(text), compile_scene(typed_payload()))

    def test_download_before_any_spec_returns_404(self):
        status, _, body = self.request("/api/spec/download")

        self.assertEqual(status, 404)
        self.assertIn("POST /api/spec", json.loads(body)["error"])

    def test_download_serves_the_most_recent_spec(self):
        payload = form_payload()
        self.post_spec(payload)
        payload["dialogue"]["text"] = "Second take."
        self.post_spec(payload)

        _, _, body = self.request("/api/spec/download")

        scene = json.loads(body)
        self.assertEqual(scene["dialogue"]["text"], "Second take.")


class ToolsApiTests(ServerTestCase):
    def test_tools_reports_availability_as_status(self):
        status, _, body = self.request("/api/tools")

        self.assertEqual(status, 200)
        report = json.loads(body)
        self.assertTrue(report["ffmpeg"]["available"])
        self.assertEqual(report["ffmpeg"]["path"], "/fake/bin/ffmpeg")
        self.assertFalse(report["blender"]["available"])
        self.assertIsNone(report["blender"]["path"])

    def test_tools_never_fails_when_nothing_is_installed(self):
        self.start_server(toolchain=Toolchain(lookup=lambda name: None))

        status, _, body = self.request("/api/tools")

        self.assertEqual(status, 200)
        report = json.loads(body)
        self.assertFalse(report["ffmpeg"]["available"])
        self.assertFalse(report["blender"]["available"])


class NormalizeFormPayloadTests(unittest.TestCase):
    def test_converts_form_text_fields_to_typed_values(self):
        normalized = normalize_form_payload(form_payload())

        self.assertEqual(normalized["pause_at"], 7.4)
        self.assertEqual(normalized["output"]["resolution"], [1920, 1080])
        self.assertEqual(normalized["output"]["fps"], 30)
        self.assertEqual(normalized["output"]["format"], "mp4")

    def test_normalized_payload_compiles_to_the_typed_scene(self):
        normalized = normalize_form_payload(form_payload())

        self.assertEqual(compile_scene(normalized), compile_scene(typed_payload()))

    def test_leaves_typed_values_unchanged(self):
        payload = typed_payload()

        self.assertEqual(normalize_form_payload(payload), payload)

    def test_passes_unconvertible_values_through_for_the_validator(self):
        payload = form_payload()
        payload["pause_at"] = "soon"
        payload["output"]["resolution"] = "wide"
        payload["output"]["fps"] = "thirty"

        normalized = normalize_form_payload(payload)

        self.assertEqual(normalized["pause_at"], "soon")
        self.assertEqual(normalized["output"]["resolution"], "wide")
        self.assertEqual(normalized["output"]["fps"], "thirty")

    def test_does_not_mutate_the_original_payload(self):
        payload = form_payload()

        normalize_form_payload(payload)

        self.assertEqual(payload, form_payload())

    def test_handles_payloads_without_an_output_object(self):
        self.assertEqual(normalize_form_payload(None), None)
        self.assertEqual(
            normalize_form_payload({"template": "x"}), {"template": "x"}
        )
        self.assertEqual(
            normalize_form_payload({"output": "1920x1080"}),
            {"output": "1920x1080"},
        )


class DefaultPathTests(unittest.TestCase):
    def test_project_root_is_the_parent_of_src(self):
        root = default_project_root()

        self.assertTrue((root / "src" / "prompt_to_shot" / "server.py").is_file())

    def test_static_dir_defaults_to_repo_templates_with_shipped_files(self):
        self.assertEqual(default_static_dir(), default_project_root() / "templates")
        for name in ("index.html", "app.js", "styles.css"):
            with self.subTest(name=name):
                self.assertTrue((default_static_dir() / name).is_file())


if __name__ == "__main__":
    unittest.main()