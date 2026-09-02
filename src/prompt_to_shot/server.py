"""Local HTTP application for the prompt-to-shot browser form.

`make_server` builds a stdlib `http.server` bound to a local interface. The
form posts JSON whose fields are text; the server normalizes form-shaped
values (resolution string, numeric strings) and lets
`templates.compile_scene` remain the single validation authority. A successful
`POST /api/spec` returns the compiled scene plus the planned FFmpeg preview
command; toolchain availability is displayed status (`GET /api/tools`), never
a request failure. The generated spec is downloadable, in the repository's
canonical JSON form, at `GET /api/spec/download`.
"""

import argparse
import json
import re
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .renderers import (
    AssetPathError,
    MissingToolError,
    Toolchain,
    plan_ffmpeg_render,
)
from .schema import SceneValidationError
from .templates import compile_scene, serialize_scene

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
MAX_BODY_BYTES = 1_000_000
_RESOLUTION_PATTERN = re.compile(r"^\s*(\d+)\s*[xX]\s*(\d+)\s*$")
_STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


def default_project_root():
    """Return the repository root: the parent of the src/ directory."""
    return Path(__file__).resolve().parents[2]


def default_static_dir():
    """Return the repository-root templates directory holding the form."""
    return default_project_root() / "templates"


def normalize_form_payload(payload):
    """Convert browser text fields to typed values before validation.

    Resolution arrives as "WIDTHxHEIGHT" and becomes ``[width, height]``;
    numeric fields arrive as strings and become numbers. Values that cannot be
    converted are passed through unchanged so `compile_scene` rejects them
    with its own message — the server never pre-validates its rules.
    """
    if not isinstance(payload, dict):
        return payload
    normalized = dict(payload)
    if "pause_at" in normalized:
        normalized["pause_at"] = _to_float(normalized["pause_at"])
    if isinstance(normalized.get("output"), dict):
        output = dict(normalized["output"])
        if "resolution" in output:
            output["resolution"] = _to_resolution(output["resolution"])
        if "fps" in output:
            output["fps"] = _to_int(output["fps"])
        normalized["output"] = output
    return normalized


def _to_float(value):
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return value
    return value


def _to_int(value):
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return value
    return value


def _to_resolution(value):
    if isinstance(value, str):
        match = _RESOLUTION_PATTERN.match(value)
        if match:
            return [int(match.group(1)), int(match.group(2))]
    return value


def canonical_json_bytes(payload):
    """Serialize an API payload with the repository's canonical JSON convention."""
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    return text.encode("utf-8")


class PromptToShotHTTPServer(ThreadingHTTPServer):
    """Threaded server carrying the form's configuration and last generated spec."""

    daemon_threads = True

    def __init__(self, address, handler, *, static_dir, project_root, toolchain):
        self.static_dir = Path(static_dir)
        self.project_root = Path(project_root)
        self.toolchain = toolchain
        self.last_scene_text = None
        super().__init__(address, handler)


class PromptToShotHandler(BaseHTTPRequestHandler):
    """Serves the static browser form and the scene JSON API."""

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def log_message(self, format, *args):
        """Keep request logging quiet; the server runs in a foreground terminal."""

    def _dispatch(self, method):
        path = urlsplit(self.path).path
        try:
            self._route(method, path)
        except SceneValidationError as error:
            self._send_json(422, {"error": str(error)})
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:
            traceback.print_exc()
            self._send_json(500, {"error": "internal server error"})

    def _route(self, method, path):
        if path in _STATIC_FILES:
            if method == "GET":
                self._serve_static(path)
            else:
                self._method_not_allowed(method, path)
        elif path == "/api/tools":
            if method == "GET":
                self._send_json(200, self.server.toolchain.status())
            else:
                self._method_not_allowed(method, path)
        elif path == "/api/spec/download":
            if method == "GET":
                self._serve_spec_download()
            else:
                self._method_not_allowed(method, path)
        elif path == "/api/spec":
            if method == "POST":
                self._handle_spec_post()
            else:
                self._method_not_allowed(method, path)
        else:
            self._send_json(404, {"error": f"not found: {path}"})

    def _serve_static(self, path):
        name, content_type = _STATIC_FILES[path]
        try:
            body = (self.server.static_dir / name).read_bytes()
        except OSError:
            self._send_json(404, {"error": f"static file not found: {name}"})
            return
        self._send_bytes(200, body, content_type)

    def _serve_spec_download(self):
        if self.server.last_scene_text is None:
            self._send_json(
                404, {"error": "no generated spec yet; POST /api/spec first"}
            )
            return
        self._send_bytes(
            200,
            self.server.last_scene_text.encode("utf-8"),
            "application/json; charset=utf-8",
            {"Content-Disposition": 'attachment; filename="scene.json"'},
        )

    def _handle_spec_post(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send_json(400, {"error": "invalid Content-Length header"})
            return
        if length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "request body too large"})
            return
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._send_json(400, {"error": "request body must be valid JSON"})
            return
        scene = compile_scene(normalize_form_payload(payload))
        try:
            plan = plan_ffmpeg_render(scene, self.server.project_root, self.server.toolchain)
        except AssetPathError as error:
            self._send_json(422, {"error": str(error)})
            return
        except MissingToolError as error:
            plan = None
            plan_error = str(error)
        else:
            plan_error = None
        self.server.last_scene_text = serialize_scene(scene)
        self._send_json(200, {"scene": scene, "plan": plan, "plan_error": plan_error})

    def _method_not_allowed(self, method, path):
        self._send_json(405, {"error": f"method not allowed: {method} {path}"})

    def _send_json(self, status, payload):
        self._send_bytes(status, canonical_json_bytes(payload), "application/json; charset=utf-8")

    def _send_bytes(self, status, body, content_type, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)


def make_server(host=DEFAULT_HOST, port=DEFAULT_PORT, *, static_dir=None, project_root=None, toolchain=None):
    """Create the local HTTP server bound to (host, port) without serving it."""
    return PromptToShotHTTPServer(
        (host, port),
        PromptToShotHandler,
        static_dir=static_dir if static_dir is not None else default_static_dir(),
        project_root=project_root if project_root is not None else default_project_root(),
        toolchain=toolchain if toolchain is not None else Toolchain(),
    )


def main(argv=None):
    """Parse CLI arguments and serve the form until interrupted."""
    parser = argparse.ArgumentParser(
        description="Serve the prompt-to-shot browser form and scene API."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="interface to bind")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port to bind")
    args = parser.parse_args(argv)
    server = make_server(args.host, args.port)
    print(f"prompt-to-shot form: http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()