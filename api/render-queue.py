"""Authenticated Vercel-hosted first-pass render worker."""

import json
import os
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
for base in (here.parent, Path.cwd()):
    source = base / "src"
    if (source / "ulo_videos" / "cloud_worker.py").is_file() and str(source) not in sys.path:
        sys.path.insert(0, str(source))

from ulo_videos.cloud_worker import fallback_health, queue_message, render_cloud_job


def _response(start_response, status, body):
    payload = json.dumps(body).encode()
    start_response(status, [("Content-Type", "application/json"), ("Content-Length", str(len(payload)))])
    return [payload]


def app(environ, start_response):
    if environ.get("REQUEST_METHOD") == "GET":
        return _response(start_response, "200 OK", fallback_health())
    if environ.get("REQUEST_METHOD") != "POST":
        return _response(start_response, "405 Method Not Allowed", {"error": "POST required"})
    length = int(environ.get("CONTENT_LENGTH") or 0)
    raw = environ.get("wsgi.input").read(length)
    try:
        message = queue_message(raw, environ.get("HTTP_AUTHORIZATION", ""), os.environ.get("RENDER_WORKER_SECRET"))
        result = render_cloud_job(message["renderJobId"], environ.get("HTTP_HOST", "ulo-videos.vercel.app"))
        return _response(start_response, "200 OK", result)
    except PermissionError as error:
        return _response(start_response, "401 Unauthorized", {"error": str(error)})
    except (ValueError, json.JSONDecodeError) as error:
        return _response(start_response, "400 Bad Request", {"error": str(error)})
    except Exception as error:
        return _response(start_response, "502 Bad Gateway", {"error": str(error)})
