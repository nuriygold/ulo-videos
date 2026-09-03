"""Vercel entry point: the ulo-videos form and scene API as a WSGI app.

Vercel's Python runtime (the `/api` directory contract) loads this file as a
Vercel Function. The vercel.json catch-all rewrite forwards every non-/api
path to this function with the original path in a `__p` query parameter —
the runtime hands rewritten requests the destination path and no original-
path marker (verified against a live deployment), so the original has to
ride along explicitly. The adapter below rebuilds the real target and then
delegates every request to `ulo_videos.server.make_wsgi_app` — the same
dispatch logic the local `http.server` app serves — so the deployed surface
is byte-equivalent to the local one: the browser form, its scripts, the
scene compiler, the render planner, and toolchain status.

Native rendering cannot run serverless: the function has no ffmpeg, blender,
piper, or rhubarb, so `GET /api/tools` reports the toolchain as unavailable
and a spec request carries the named `plan_error` instead of a command.
Uploads write into the project's `assets/` directory, which a deployment
mounts read-only, so they fail with a clean JSON error rather than a file.
The function stays on the Python standard library like the rest of the app;
the runtime is pinned by `.python-version` and nothing else needs installing.
"""

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode


def _add_src_to_path():
    """Put the repository's src/ on sys.path so the package imports.

    Vercel runs Python functions with the project root as the working
    directory and uploads the repository's file layout, so src/ is reachable
    both next to this file and relative to the working directory; resolve from
    both so the import holds if either assumption changes.
    """
    here = Path(__file__).resolve().parent
    for base in (here.parent, Path.cwd()):
        candidate = base / "src"
        if (
            (candidate / "ulo_videos" / "server.py").is_file()
            and str(candidate) not in sys.path
        ):
            sys.path.insert(0, str(candidate))


_add_src_to_path()

# Imported after the path bootstrap above: this file is loaded by the hosting
# runtime as a standalone script, not as part of a package.
from ulo_videos.server import make_wsgi_app

_wsgi = make_wsgi_app()


def app(environ, start_response):
    """Unwrap rewrite-forwarded targets, then delegate to the dispatcher.

    Rewritten requests land on PATH_INFO="/api" with the original path in
    `__p`; native `/api/*` routes (which all have a suffix after /api) are
    passed through untouched, matching the local transport exactly.
    """
    if environ.get("PATH_INFO") == "/api":
        params = parse_qs(environ.get("QUERY_STRING", ""))
        if "__p" in params:
            rest = {k: v for k, v in params.items() if k != "__p"}
            environ = dict(
                environ,
                PATH_INFO=params["__p"][0] or "/",
                QUERY_STRING=urlencode(rest, doseq=True),
            )
    return _wsgi(environ, start_response)