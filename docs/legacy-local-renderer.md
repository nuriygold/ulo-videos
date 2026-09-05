# Legacy local renderer

This document describes the earlier Python WSGI application. It remains in the
repository for local planner experiments and legacy tests, but it is not the
supported hosted workspace or the production render architecture.

The current product entrypoints are the Next.js application in `app/`, the
browser/domain helpers in `src/web/`, and the external worker in `worker/`.
Start with the repository README and `docs/external-worker.md` when changing
production behavior.

## Local commands

From the repository root:

```sh
PYTHONPATH=src python3 -m ulo_videos
PYTHONPATH=src python3 -m ulo_videos --port 8080
```

The local WSGI application serves the historical `templates/` form and local
planner routes such as:

- `GET /api/tools`
- `POST /api/spec`
- `POST /api/render`
- `GET /api/artifact?path=build/NAME`
- `GET /api/spec/download`
- `POST /api/upload?filename=NAME`

Those routes plan or execute local media work against the checkout. They do not
represent the hosted Supabase, Vercel Blob, queue, or external-worker flow.

The shared Python modules under `src/ulo_videos/` also contain current fallback
and Scene v1 helpers. Check imports and module docstrings before changing a
module; do not infer production behavior from the legacy server alone.
