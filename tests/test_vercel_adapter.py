"""WSGI adapter tests: the serverless entry point and read-only deployments.

`make_wsgi_app` exposes the same routes as the local `http.server` app through
a WSGI callable — the shape Vercel's Python runtime loads from `api/index.py`.
Requests are invoked directly against the callable (no network, no sockets),
and `api/index.py` is loaded the way Vercel loads it: as a standalone file.
The serverless simulation injects a toolchain that finds nothing, mirroring a
deployment without ffmpeg or blender.
"""

import importlib.util
import io
import json
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

from ulo_videos.renderers import Toolchain
from ulo_videos.server import make_wsgi_app
from ulo_videos.templates import compile_scene

ADAPTER_ENTRY = Path(__file__).resolve().parents[1] / "api" / "index.py"


def form_payload():
    """The same all-text payload the browser form submits."""
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


def invoke(app, path, *, method="GET", body=None, query=""):
    """Call the WSGI app directly and return (status, headers, body)."""
    raw = body.encode("utf-8") if isinstance(body, str) else (body or b"")
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "SERVER_NAME": "serverless",
        "SERVER_PORT": "443",
        "CONTENT_LENGTH": str(len(raw)) if raw else "",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "https",
        "wsgi.input": io.BytesIO(raw),
        "wsgi.errors": io.StringIO(),
        "wsgi.multithread": False,
        "wsgi.multiprocess": True,
        "wsgi.run_once": False,
    }
    chunks = app(environ, start_response)
    # start_response carries a WSGI status line ("405 Method Not Allowed").
    status = int(captured["status"].split(" ")[0])
    return status, captured["headers"], b"".join(chunks)


class ServerlessTestCase(unittest.TestCase):
    """A function-style app whose toolchain finds nothing, like a deployment."""

    def setUp(self):
        root = Path(tempfile.mkdtemp(prefix="ulo-videos-serverless-")).resolve()
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
        (self.static_dir / "index.html").write_text(
            "<!doctype html><title>scene form</title>\n", encoding="utf-8"
        )
        (self.static_dir / "app.js").write_text("// form behavior\n", encoding="utf-8")
        (self.static_dir / "styles.css").write_text(
            "body { margin: 0; }\n", encoding="utf-8"
        )
        self.app = make_wsgi_app(
            static_dir=self.static_dir,
            project_root=self.project_root,
            toolchain=Toolchain(lookup=lambda name: None),
        )


class AdapterEntryTests(unittest.TestCase):
    def test_api_entry_loads_as_a_standalone_file_and_exports_app(self):
        spec = importlib.util.spec_from_file_location("vercel_api_index", ADAPTER_ENTRY)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertTrue(callable(module.app))
        # The entry serves the real repository form, resolved from the file's
        # own location and not from the working directory.
        status, headers, body = invoke(module.app, "/")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))

    def test_entry_module_resolves_paths_without_a_repo_working_directory(self):
        spec = importlib.util.spec_from_file_location("vercel_api_index", ADAPTER_ENTRY)
        module = importlib.util.module_from_spec(spec)
        previous = os.getcwd()
        os.chdir(tempfile.mkdtemp(prefix="ulo-videos-cwd-"))
        try:
            spec.loader.exec_module(module)
        finally:
            os.chdir(previous)
        status, _, _ = invoke(module.app, "/api/tools")
        self.assertEqual(status, 200)


class ServerlessStaticTests(ServerlessTestCase):
    def test_serves_the_form_page_at_root(self):
        for path in ("/", "/index.html"):
            with self.subTest(path=path):
                status, headers, body = invoke(self.app, path)
                self.assertEqual(status, 200)
                self.assertTrue(headers["Content-Type"].startswith("text/html"))
                self.assertIn(b"<!doctype html>", body)

    def test_serves_the_script_and_stylesheet(self):
        for path, content_type, marker in (
            ("/app.js", "text/javascript", b"// form behavior"),
            ("/styles.css", "text/css", b"body { margin: 0; }"),
        ):
            with self.subTest(path=path):
                status, headers, body = invoke(self.app, path)
                self.assertEqual(status, 200)
                self.assertTrue(headers["Content-Type"].startswith(content_type))
                self.assertIn(marker, body)

    def test_unknown_paths_are_404(self):
        for path in ("/missing.png", "/api/unknown"):
            with self.subTest(path=path):
                status, _, body = invoke(self.app, path)
                self.assertEqual(status, 404)
                self.assertIn("not found", json.loads(body)["error"])

    def test_wrong_methods_are_rejected_with_405(self):
        status, _, _ = invoke(self.app, "/api/tools", method="POST", body="{}")
        self.assertEqual(status, 405)

        status, _, _ = invoke(self.app, "/api/spec")
        self.assertEqual(status, 405)


class ServerlessApiTests(ServerlessTestCase):
    def test_tools_reports_every_tool_unavailable_without_failing(self):
        status, _, body = invoke(self.app, "/api/tools")

        self.assertEqual(status, 200)
        report = json.loads(body)
        self.assertEqual(
            report,
            {
                "blender": {"available": False, "path": None},
                "ffmpeg": {"available": False, "path": None},
            },
        )

    def test_spec_post_compiles_the_scene_and_names_the_missing_tool(self):
        status, _, body = invoke(
            self.app, "/api/spec", method="POST", body=json.dumps(form_payload())
        )

        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertIsNone(payload["plan"])
        self.assertIn("ffmpeg", payload["plan_error"])
        self.assertEqual(payload["scene"]["pause_at"], 7.4)

    def test_spec_post_validation_error_is_422_json(self):
        payload = form_payload()
        del payload["dialogue"]

        status, _, body = invoke(
            self.app, "/api/spec", method="POST", body=json.dumps(payload)
        )

        self.assertEqual(status, 422)
        self.assertIn("dialogue", json.loads(body)["error"])

    def test_download_serves_the_most_recent_spec(self):
        invoke(
            self.app, "/api/spec", method="POST", body=json.dumps(form_payload())
        )
        status, headers, body = invoke(self.app, "/api/spec/download")

        self.assertEqual(status, 200)
        self.assertIn("attachment", headers.get("Content-Disposition", ""))
        text = body.decode("utf-8")
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(
            json.loads(text)["dialogue"]["text"],
            "Every landlord knows real estate isn't passive.",
        )

    def test_download_before_any_spec_returns_404(self):
        status, _, body = invoke(self.app, "/api/spec/download")

        self.assertEqual(status, 404)
        self.assertIn("POST /api/spec", json.loads(body)["error"])

    def test_malformed_json_is_400_json(self):
        status, _, body = invoke(
            self.app, "/api/spec", method="POST", body="{not json"
        )

        self.assertEqual(status, 400)
        self.assertIn("JSON", json.loads(body)["error"])


class ReadOnlyFilesystemTests(ServerlessTestCase):
    """A deployment's project directory is read-only; requests must degrade.

    The form and compiler never write to disk, so they keep working; only the
    upload endpoint touches the filesystem, and it must fail with a clean JSON
    error rather than a traceback.
    """

    def setUp(self):
        super().setUp()
        self.lock_down(self.project_root)

    @classmethod
    def lock_down(cls, path):
        # A deployment mounts the whole project tree read-only, so every
        # directory must reject writes, not just the root.
        for directory in (path, *path.rglob("*")):
            if directory.is_dir():
                os.chmod(directory, stat.S_IRUSR | stat.S_IXUSR)

    @classmethod
    def unlock(cls, path):
        for directory in (path, *path.rglob("*")):
            if directory.is_dir():
                os.chmod(directory, stat.S_IRWXU)

    def tearDown(self):
        self.unlock(self.project_root)

    def test_spec_post_still_compiles_and_plans_read_only(self):
        status, _, body = invoke(
            self.app, "/api/spec", method="POST", body=json.dumps(form_payload())
        )

        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertIsNone(payload["plan"])
        self.assertIn("ffmpeg", payload["plan_error"])

    def test_upload_returns_a_clean_json_error(self):
        status, _, body = invoke(
            self.app,
            "/api/upload",
            method="POST",
            body=b"still frame bytes",
            query="filename=house_leak-2.mp4",
        )

        self.assertEqual(status, 500)
        error = json.loads(body)["error"]
        self.assertIn("could not store", error)
        self.assertIn("assets/house_leak-2.mp4", error)

    def test_upload_still_rejects_unsafe_names_read_only(self):
        status, _, body = invoke(
            self.app,
            "/api/upload",
            method="POST",
            body=b"still frame bytes",
            query="filename=notes.txt",
        )

        self.assertEqual(status, 415)
        self.assertIn("extension", json.loads(body)["error"])

    def test_static_form_files_still_serve_read_only(self):
        status, _, body = invoke(self.app, "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<!doctype html>", body)


class RewriteParamTests(unittest.TestCase):
    """The vercel.json catch-all forwards non-/api paths with the original
    path in a `__p` query parameter: the Python runtime hands rewritten
    requests the destination path (proven against a live deployment), so the
    original has to ride along explicitly. The entry point must rebuild the
    real target before delegating to the shared dispatcher."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "vercel_api_index_rewrite", ADAPTER_ENTRY
        )
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_rewrite_param_serves_the_form(self):
        status, headers, body = invoke(self.module.app, "/api", query="__p=/")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertIn(b"<!doctype html>", body)

    def test_rewrite_param_serves_scripts_with_types(self):
        for path, kind in (("app.js", "text/javascript"), ("styles.css", "text/css")):
            status, headers, _ = invoke(self.module.app, "/api", query=f"__p=/{path}")
            self.assertEqual(status, 200, path)
            self.assertTrue(headers["Content-Type"].startswith(kind), path)

    def test_rewrite_param_preserves_the_rest_of_the_query(self):
        status, _, _ = invoke(self.module.app, "/api", query="__p=/&preview=1")
        self.assertEqual(status, 200)

    def test_native_api_routes_ignore_the_param(self):
        status, _, body = invoke(self.module.app, "/api/tools", query="__p=/")
        self.assertEqual(status, 200)
        self.assertIn("ffmpeg", json.loads(body))


class LocalOnlyEndpointTests(ServerlessTestCase):
    """Rendering and artifact serving exist only in the local runtime."""

    def test_render_post_is_rejected_on_the_serverless_form(self):
        status, _, body = invoke(
            self.app, "/api/render", method="POST", body=json.dumps(form_payload())
        )

        self.assertEqual(status, 403)
        self.assertIn("local app", json.loads(body)["error"])

    def test_artifact_get_is_rejected_on_the_serverless_form(self):
        status, _, body = invoke(self.app, "/api/artifact?path=build/preview.mp4")

        self.assertEqual(status, 403)
        self.assertIn("local app", json.loads(body)["error"])


if __name__ == "__main__":
    unittest.main()
