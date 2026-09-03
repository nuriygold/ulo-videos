"""Vercel entry point: the ulo-videos form and scene API as a WSGI app.

Vercel's Python runtime (the `/api` directory contract) loads this file as a
Vercel Function serving the `/api` routes natively — no rewrite needed. The
form and its scripts are CDN-served from `templates/` through the vercel.json
rewrites. All API routes are delegated to
`ulo_videos.server.make_wsgi_app` — the same dispatch logic the local
`http.server` app serves — so the deployed surface is the browser form, the
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

app = make_wsgi_app()
