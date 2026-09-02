"""Local HTTP application for the prompt-to-shot browser form.

`make_server` builds a stdlib `http.server` bound to a local interface. The
form posts JSON whose fields are text; the server normalizes form-shaped
values (resolution string, numeric strings) and lets
`templates.compile_scene` remain the single validation authority. A successful
`POST /api/spec` returns the compiled scene plus the planned FFmpeg preview
command; toolchain availability is displayed status (`GET /api/tools`), never
a request failure. The generated spec is downloadable, in the repository's
canonical JSON form, at `GET /api/spec/download`. Media assets are uploaded as
raw bytes to `POST /api/upload?filename=NAME`; storage rules live in
`projects`, and the server only maps storage errors to HTTP statuses.

Every transport shares one routing entry point: `dispatch_request` takes the
request's method, target, headers, and body stream, and returns the response
as plain data. The local handler writes that data onto the socket, and
`make_wsgi_app` wraps the same dispatcher in a WSGI callable — the shape
Vercel's Python runtime hosts from `api/index.py`, where a serverless function
serves the form, compiler, planner, and toolchain status without a socket.
"""

import argparse
import json
import re
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import projects
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


class AppState:
    """Configuration and the last generated spec, shared by every transport.

    The local `http.server` app and the WSGI adapter route requests through
    the same state: where the form files live, where project assets resolve,
    which toolchain is installed, and the most recently generated spec. The
    spec is deliberately in-process — the generated document is held in
    memory, so a restart (or a fresh function instance) starts empty.
    """

    def __init__(self, *, static_dir, project_root, toolchain):
        self.static_dir = Path(static_dir)
        self.project_root = Path(project_root)
        self.toolchain = toolchain
        self.last_scene_text = None


def _response(status, body, content_type, extra_headers=None):
    """Return a response as (status, headers, body) with the shared header set."""
    headers = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
    ]
    headers.extend((extra_headers or {}).items())
    return status, headers, body


def _json_response(status, payload):
    return _response(
        status, canonical_json_bytes(payload), "application/json; charset=utf-8"
    )


def _method_not_allowed(method, path):
    return _json_response(405, {"error": f"method not allowed: {method} {path}"})


def _static_response(state, path):
    name, content_type = _STATIC_FILES[path]
    try:
        body = (state.static_dir / name).read_bytes()
    except OSError:
        return _json_response(404, {"error": f"static file not found: {name}"})
    return _response(200, body, content_type)


def _spec_download_response(state):
    if state.last_scene_text is None:
        return _json_response(
            404, {"error": "no generated spec yet; POST /api/spec first"}
        )
    return _response(
        200,
        state.last_scene_text.encode("utf-8"),
        "application/json; charset=utf-8",
        {"Content-Disposition": 'attachment; filename="scene.json"'},
    )


def _declared_length(headers):
    """Return the request's declared Content-Length, or None when invalid."""
    try:
        return int(headers.get("Content-Length") or 0)
    except ValueError:
        return None


def _read_body(input_stream, length):
    """Read `length` bytes from the request body stream, tolerating no stream."""
    if length <= 0 or input_stream is None:
        return b""
    return input_stream.read(length)


def _spec_post_response(state, headers, input_stream):
    length = _declared_length(headers)
    if length is None:
        return _json_response(400, {"error": "invalid Content-Length header"})
    if length > MAX_BODY_BYTES:
        return _json_response(413, {"error": "request body too large"})
    raw = _read_body(input_stream, length)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _json_response(400, {"error": "request body must be valid JSON"})
    scene = compile_scene(normalize_form_payload(payload))
    try:
        plan = plan_ffmpeg_render(scene, state.project_root, state.toolchain)
    except AssetPathError as error:
        return _json_response(422, {"error": str(error)})
    except MissingToolError as error:
        plan = None
        plan_error = str(error)
    else:
        plan_error = None
    state.last_scene_text = serialize_scene(scene)
    return _json_response(200, {"scene": scene, "plan": plan, "plan_error": plan_error})


def _upload_post_response(state, target, headers, input_stream):
    """Store the raw request body as a project asset and update the manifest."""
    query = parse_qs(urlsplit(target).query)
    names = query.get("filename")
    if not names:
        return _json_response(400, {"error": "filename query parameter is required"})
    if len(names) > 1:
        return _json_response(
            400, {"error": "filename query parameter must be given once"}
        )
    length = _declared_length(headers)
    if length is None:
        return _json_response(400, {"error": "invalid Content-Length header"})
    if length > projects.MAX_UPLOAD_BYTES:
        return _json_response(
            413,
            {
                "error": (
                    "upload body too large; the limit is "
                    f"{projects.MAX_UPLOAD_BYTES} bytes"
                )
            },
        )
    raw = _read_body(input_stream, length)
    if not raw:
        return _json_response(400, {"error": "upload body must contain the file bytes"})
    if len(raw) != length:
        return _json_response(
            400, {"error": "request body ended before Content-Length bytes"}
        )
    try:
        relative, entry = projects.store_upload(state.project_root, names[0], raw)
    except projects.InvalidFilenameError as error:
        return _json_response(400, {"error": str(error)})
    except projects.UnsupportedExtensionError as error:
        return _json_response(415, {"error": str(error)})
    except projects.UploadTooLargeError as error:
        return _json_response(413, {"error": str(error)})
    except projects.ManifestError as error:
        return _json_response(500, {"error": str(error)})
    except projects.ProjectStorageError as error:
        return _json_response(500, {"error": str(error)})
    except AssetPathError as error:
        return _json_response(400, {"error": str(error)})
    return _json_response(200, {"path": relative, "entry": entry})


def _route(state, method, path, target, headers, input_stream):
    if path in _STATIC_FILES:
        if method == "GET":
            return _static_response(state, path)
        return _method_not_allowed(method, path)
    if path == "/api/tools":
        if method == "GET":
            return _json_response(200, state.toolchain.status())
        return _method_not_allowed(method, path)
    if path == "/api/spec/download":
        if method == "GET":
            return _spec_download_response(state)
        return _method_not_allowed(method, path)
    if path == "/api/spec":
        if method == "POST":
            return _spec_post_response(state, headers, input_stream)
        return _method_not_allowed(method, path)
    if path == "/api/upload":
        if method == "POST":
            return _upload_post_response(state, target, headers, input_stream)
        return _method_not_allowed(method, path)
    return _json_response(404, {"error": f"not found: {path}"})


def dispatch_request(state, method, target, *, headers, input_stream):
    """Route one request and return (status, headers, body).

    The single entry point shared by the local `http.server` handler and the
    WSGI serverless adapter: `target` is the raw request target, `headers` is
    any mapping with a `Content-Length` key, and `input_stream` is a binary
    reader holding the request body. Validation errors become 422 JSON, and
    every other error becomes a 500 JSON response instead of a traceback on
    the wire — a serverless function must answer, never crash. Connection
    resets are re-raised so the transport can drop the connection itself.
    """
    path = urlsplit(target).path
    try:
        return _route(state, method, path, target, headers, input_stream)
    except SceneValidationError as error:
        return _json_response(422, {"error": str(error)})
    except (BrokenPipeError, ConnectionResetError):
        raise
    except Exception:
        traceback.print_exc()
        return _json_response(500, {"error": "internal server error"})


class PromptToShotHTTPServer(ThreadingHTTPServer):
    """Threaded server carrying the form's state and last generated spec."""

    daemon_threads = True

    def __init__(self, address, handler, *, static_dir, project_root, toolchain):
        self.state = AppState(
            static_dir=static_dir, project_root=project_root, toolchain=toolchain
        )
        super().__init__(address, handler)


class PromptToShotHandler(BaseHTTPRequestHandler):
    """Writes the shared request dispatcher's responses onto the socket."""

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def log_message(self, format, *args):
        """Keep request logging quiet; the server runs in a foreground terminal."""

    def _dispatch(self, method):
        try:
            status, headers, body = dispatch_request(
                self.server.state,
                method,
                self.path,
                headers=self.headers,
                input_stream=self.rfile,
            )
            self._send(status, headers, body)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def _send(self, status, headers, body):
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)


def _app_state(static_dir, project_root, toolchain):
    """Build AppState, filling in the repository defaults for anything omitted."""
    return AppState(
        static_dir=static_dir if static_dir is not None else default_static_dir(),
        project_root=project_root if project_root is not None else default_project_root(),
        toolchain=toolchain if toolchain is not None else Toolchain(),
    )


def make_server(host=DEFAULT_HOST, port=DEFAULT_PORT, *, static_dir=None, project_root=None, toolchain=None):
    """Create the local HTTP server bound to (host, port) without serving it."""
    state = _app_state(static_dir, project_root, toolchain)
    return PromptToShotHTTPServer(
        (host, port),
        PromptToShotHandler,
        static_dir=state.static_dir,
        project_root=state.project_root,
        toolchain=state.toolchain,
    )


def _status_line(status):
    """Return a WSGI status line such as "200 OK" for a numeric status."""
    try:
        return f"{status} {HTTPStatus(status).phrase}"
    except ValueError:
        return str(status)


def make_wsgi_app(*, static_dir=None, project_root=None, toolchain=None):
    """Create a WSGI application serving the same surface as `make_server`.

    Serverless hosts (Vercel's Python runtime) call a WSGI callable per
    request instead of binding a socket, so this is the deployment form of the
    same app: the same `dispatch_request` routes, the same repository defaults,
    and the per-process state a warm function instance carries between
    requests. The toolchain is capability-detected at request time, so a host
    without ffmpeg or blender reports those tools as unavailable instead of
    failing, and planning never writes to the (read-only) deployment
    filesystem.
    """
    state = _app_state(static_dir, project_root, toolchain)

    def app(environ, start_response):
        target = environ.get("PATH_INFO", "/")
        query = environ.get("QUERY_STRING", "")
        if query:
            target = f"{target}?{query}"
        request_headers = {"Content-Length": environ.get("CONTENT_LENGTH", "")}
        status, headers, body = dispatch_request(
            state,
            str(environ.get("REQUEST_METHOD", "GET")).upper(),
            target,
            headers=request_headers,
            input_stream=environ.get("wsgi.input"),
        )
        start_response(_status_line(status), headers)
        return [body]

    return app


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
