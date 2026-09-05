# ulo-videos

`ulo-videos` is a hosted, deterministic video-production workspace. The
browser authors a validated Scene v1 snapshot; the control plane persists that
snapshot and dispatches a small render message. Media execution belongs to an
external worker, not a Vercel Function.

```text
Browser editor
  -> Next.js control plane
  -> Supabase project/shot/render-job records
  -> Vercel Blob asset storage
  -> queue: { "renderJobId": "rj_..." }
  -> external Blender + FFmpeg worker
  -> Blob MP4 + render_jobs.output_asset_id
  -> workspace video player
```

Production: <https://ulo-videos.vercel.app>

## Product surface

The supported browser application is the Next.js App Router application in
`app/`, with domain and browser helpers in `src/web/`.

- `/` - Scene v1 workspace editor
- `/api/projects` - anonymous workspace projects
- `/api/shots` - validated immutable shot snapshots
- `/api/assets/upload` - scoped Vercel Blob uploads
- `/api/render-jobs` - immutable render-job creation and history
- `/api/render-jobs/[id]/status` - authenticated worker status updates
- `/api/setup-status` - cloud-service and renderer capability status

The anonymous workspace cookie scopes ownership. It is not an authentication
system, and this product does not add sign-in or password behavior.

## Render contract

Scene v1 JSON is the source of truth. A render job stores an immutable
`spec_snapshot`; workers must never read the mutable editor draft.

Queue messages contain only:

```json
{ "renderJobId": "rj_123" }
```

The worker fetches the job and its assets, reports the stages defined in
`src/web/contracts.ts`, renders the selected scene, uploads an MP4, creates a
`render_output` asset, and sets `output_asset_id`. The UI resolves that asset to
`output_url` and exposes a playable video when the job completes.

The external worker implementation is in `worker/`. It uses Blender for
character plates and FFmpeg for freeze/resume, compositing, captions, and MP4
encoding. The current worker supports `.blend`, self-contained `.gltf`, `.glb`,
and embedded-resource `.fbx` character assets. Voice and lip-sync references
are currently preserved as metadata; Piper and Rhubarb are not enabled.

See [docs/external-worker.md](docs/external-worker.md) for the worker HTTP
contract, container requirements, deployment boundary, and migration procedure.

## Current production state

Production currently reports the `vercel_fallback` renderer. It is intended for
control-plane and fallback-capability testing, not as the long-running
production media worker. Character rendering, source-audio preservation,
speech, and lip-sync are unavailable in this mode.

The latest verification record is in
[docs/verification-reports/2026-09-04-172512-PDT-ulovideos-production-verification.md](docs/verification-reports/2026-09-04-172512-PDT-ulovideos-production-verification.md).
That report records a known fallback render-completion blocker: the synchronous
Vercel render path returned HTTP 502 with FFmpeg output. Do not describe the
fallback as a completed production rendering service until that path is fixed
or production is moved to a durable external worker queue.

## Development

Requirements:

- Node.js with npm
- Python 3.11 or newer for worker and contract tests
- Docker only for building or running the external worker image

Install JavaScript dependencies and start the browser application:

```sh
npm ci
npm run dev
```

The development server is normally available at `http://localhost:3000`.
Production verification uses the Vercel URL above, not localhost.

The control plane requires these environment variables when cloud services are
used. Never commit or print their values:

```text
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
BLOB_READ_WRITE_TOKEN
RENDER_QUEUE_URL
RENDER_WORKER_SECRET
```

The external worker uses the Supabase, Blob, and worker-secret values above.
`RENDER_QUEUE_URL` must point at an authenticated dispatcher or queue endpoint;
the synchronous worker endpoint is for testing and controlled migration work,
not long production renders.

## Worker image

The worker image is pinned to Linux amd64 and Blender 5.2.1:

```sh
docker build --platform linux/amd64 \
  -t ulo-videos-render-worker -f worker/Dockerfile .
```

The image must remain an external container or service. Do not move Blender or
long-running FFmpeg execution into a Vercel Function.

## Verification

Focused and full checks for the current control plane and worker are:

```sh
npm test
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=.:src python3 -m unittest discover -s worker/tests -t worker/tests
npx tsc --noEmit
npm run build
git diff --check
```

The Docker-backed Blender fixture runs in the GitHub Actions workflow at
[`.github/workflows/worker-integration.yml`](.github/workflows/worker-integration.yml).

## Repository layout

- `app/` - Next.js pages and route handlers
- `src/web/` - Scene v1, workspace, upload, queue, setup, and Supabase helpers
- `worker/` - external Blender + FFmpeg worker and integration fixtures
- `db/schema.sql` - Supabase control-plane schema
- `schemas/scene-v1.schema.json` - authoritative Scene v1 shape
- `api/render-queue.py` - current synchronous fallback worker endpoint
- `docs/external-worker.md` - external worker contract and deployment guide
- `docs/verification-reports/` - dated production verification records
- `docs/legacy-local-renderer.md` - historical local WSGI/planner surface

The old local WSGI application is not the hosted workspace entrypoint. Its
scope and commands are documented separately so legacy tests and experiments do
not get confused with the current Next.js control plane.
