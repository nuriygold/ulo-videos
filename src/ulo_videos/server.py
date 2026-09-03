"""Local HTTP application for the ulo-videos browser form.

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
    CommandTimeoutError,
    MissingToolError,
    RendererError,
    Toolchain,
    plan_ffmpeg_render,
    run_command,
)
from .schema import SceneValidationError
from .templates import compile_scene, serialize_scene

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
# Deployed form origins allowed to read local toolchain status cross-origin:
# the deployed page probes this endpoint on the viewer's machine so its
# toolchain panel can report that machine's real tools.
TOOL_STATUS_CORS_ORIGINS = (
    "https://ulo-videos.vercel.app",
    "https://ulo-videos-nuriys-projects.vercel.app",
)
MAX_BODY_BYTES = 1_000_000
RENDER_TIMEOUT_SECONDS = 300
# Executable-plan and artifact endpoints exist only in the local runtime: the
# serverless form compiles and plans, the machine running the local app renders.
_CORS_PATHS = ("/api/tools", "/api/render")
_ARTIFACT_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".png": "image/png",
}
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

    def __init__(self, *, static_dir, project_root, toolchain, allow_exec=False, runner=None):
        self.static_dir = Path(static_dir)
        self.project_root = Path(project_root)
        self.toolchain = toolchain
        self.allow_exec = allow_exec
        self.runner = runner if runner is not None else run_command
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


def _cors_extra(headers):
    """CORS echo headers for allowlisted deployed-form origins, else None."""
    origin = headers.get("Origin", "") if headers is not None else ""
    if origin in TOOL_STATUS_CORS_ORIGINS:
        return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
    return None


def _preflight_response(path, headers):
    """Answer a CORS preflight for the probe and render endpoints, else 404."""
    extra = _cors_extra(headers)
    if path not in _CORS_PATHS or extra is None:
        return _json_response(404, {"error": f"not found: {path}"})
    extra.update(
        {
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Max-Age": "600",
        }
    )
    return _response(204, b"", "text/plain; charset=utf-8", extra)


def _tool_status_response(state, headers):
    """Report toolchain status, CORS-open to the deployed form origins.

    The deployed page probes this endpoint on the viewer's machine to report
    that machine's real tools; a matching Origin is echoed so the browser may
    read the answer, and anything else gets no CORS header.
    """
    return _response(
        200,
        canonical_json_bytes(state.toolchain.status()),
        "application/json; charset=utf-8",
        _cors_extra(headers),
    )


def _render_post_response(state, headers, input_stream):
    """Compile, plan, and — in the local runtime only — execute the plan.

    The response mirrors `POST /api/spec` plus a `render` object: `executed`
    is true only when the machine running this server actually has the tools
    and the planned command exited 0. The serverless form answers with
    `executed: false` never running a subprocess (403 body explains), so
    rendering stays a local-machine capability by construction.
    """
    if not state.allow_exec:
        return _json_response(
            403,
            {"error": "rendering runs only in the local app; the deployed form compiles and plans"},
        )
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
        return _response(
            200,
            canonical_json_bytes(
                {"scene": scene, "plan": None, "plan_error": str(error), "render": {"executed": False}}
            ),
            "application/json; charset=utf-8",
            _cors_extra(headers),
        )
    state.last_scene_text = serialize_scene(scene)
    render = {"executed": False}
    if plan["status"] == "ready":
        output = Path(plan["output"]["path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = state.runner(plan["argv"], timeout=RENDER_TIMEOUT_SECONDS)
        except (RendererError, CommandTimeoutError) as error:
            render = {"executed": False, "error": str(error)}
        else:
            render = {
                "executed": result["returncode"] == 0,
                "returncode": result["returncode"],
                "stderr_tail": result["stderr"][-2000:],
                "output_path": str(output),
                "download": _download_path(output, state.project_root),
            }
    return _response(
        200,
        canonical_json_bytes({"scene": scene, "plan": plan, "plan_error": None, "render": render}),
        "application/json; charset=utf-8",
        _cors_extra(headers),
    )


def _download_path(output, project_root):
    """Return `output` as a project-root-relative POSIX path for /api/artifact."""
    try:
        return output.resolve().relative_to(Path(project_root).resolve()).as_posix()
    except ValueError:
        return None


def _artifact_response(state, target):
    """Serve a rendered file from the project's build directory (local only)."""
    if not state.allow_exec:
        return _json_response(
            403,
            {"error": "rendered files live on the machine running the local app"},
        )
    names = parse_qs(urlsplit(target).query).get("path")
    if not names or len(names) > 1:
        return _json_response(400, {"error": "path query parameter is required exactly once"})
    build_root = (state.project_root / "build").resolve()
    candidate = (state.project_root / names[0]).resolve()
    if candidate != build_root and build_root not in candidate.parents:
        return _json_response(404, {"error": "no artifact outside the project build directory"})
    if not candidate.is_file():
        return _json_response(404, {"error": f"artifact not found: {names[0]}"})
    content_type = _ARTIFACT_TYPES.get(candidate.suffix.lower())
    if content_type is None:
        return _json_response(415, {"error": f"unsupported artifact type: {candidate.suffix}"})
    return _response(
        200,
        candidate.read_bytes(),
        content_type,
        {"Content-Disposition": f'attachment; filename="{candidate.name}"'},
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
    if method == "OPTIONS":
        return _preflight_response(path, headers)
    if path in _STATIC_FILES:
        if method == "GET":
            return _static_response(state, path)
        return _method_not_allowed(method, path)
    if path == "/api/tools":
        if method == "GET":
            return _tool_status_response(state, headers)
        return _method_not_allowed(method, path)
    if path == "/api/render":
        if method == "POST":
            return _render_post_response(state, headers, input_stream)
        return _method_not_allowed(method, path)
    if path == "/api/artifact":
        if method == "GET":
            return _artifact_response(state, target)
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


class UloVideosHTTPServer(ThreadingHTTPServer):
    """Threaded server carrying the form's state and last generated spec."""

    daemon_threads = True

    def __init__(self, address, handler, *, static_dir, project_root, toolchain, runner=None):
        self.state = AppState(
            static_dir=static_dir,
            project_root=project_root,
            toolchain=toolchain,
            allow_exec=True,
            runner=runner,
        )
        super().__init__(address, handler)


class UloVideosHandler(BaseHTTPRequestHandler):
    """Writes the shared request dispatcher's responses onto the socket."""

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_OPTIONS(self):
        self._dispatch("OPTIONS")

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


def make_server(host=DEFAULT_HOST, port=DEFAULT_PORT, *, static_dir=None, project_root=None, toolchain=None, runner=None):
    """Create the local HTTP server bound to (host, port) without serving it."""
    state = _app_state(static_dir, project_root, toolchain)
    return UloVideosHTTPServer(
        (host, port),
        UloVideosHandler,
        static_dir=state.static_dir,
        project_root=state.project_root,
        toolchain=state.toolchain,
        runner=runner,
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
        request_headers = {
            "Content-Length": environ.get("CONTENT_LENGTH", ""),
            "Origin": environ.get("HTTP_ORIGIN", ""),
        }
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
        description="Serve the ulo-videos browser form and scene API."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="interface to bind")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port to bind")
    args = parser.parse_args(argv)
    server = make_server(args.host, args.port)
    print(f"ulo-videos form: http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
