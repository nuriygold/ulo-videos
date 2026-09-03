# External Blender render worker

This guide deploys the media execution plane outside Vercel. The Vercel app
creates an immutable `render_jobs.spec_snapshot` and dispatches one small,
authenticated message to the worker:

```json
{"renderJobId":"rj_123"}
```

The external service owns media execution. It retrieves the job snapshot from
Supabase, downloads only the assets named by that snapshot, renders the scene,
uploads the finished MP4 to Vercel Blob, creates its `assets` row, and updates
the same `render_jobs` row. It must never mutate a saved shot or read a live
editor draft.

## Required HTTP contract

Expose one private worker endpoint:

```text
POST /render-jobs
Authorization: Bearer <RENDER_WORKER_SECRET>
Content-Type: application/json

{"renderJobId":"rj_123"}
```

The request handler must reject all of the following before starting a render:

- a method other than `POST` (`405`)
- a missing or invalid Bearer secret (`401`)
- a non-JSON body, missing `renderJobId`, or an ID not starting with `rj_`
  (`400`)

The current service runs a job synchronously and returns `200 OK` only after
the worker has written its terminal state. The authoritative result remains
the `render_jobs` record in Supabase. This deliberately avoids acknowledging a
render from an in-memory background thread that a restart could lose.

Keep the message shape exactly as above. Do not add source URLs, Blob tokens,
or the scene specification to queue messages.

Provide an unauthenticated, side-effect-free health route:

```text
GET /healthz
200 {"ok":true,"ffmpeg":true,"blender":true}
```

The readiness check should report `503` until both `ffmpeg` and `blender` are
available on `PATH`. Piper and Rhubarb may be reported separately when those
stages are enabled. Do not use `/healthz` to reveal environment values.

## Worker responsibilities

For each accepted job, use the service-role credentials only inside the worker:

1. Read `render_jobs?id=eq.<renderJobId>&limit=1` from Supabase REST.
2. Set status to `preparing`, then `downloading_assets`.
3. Resolve and download the source video, optional logo, and character `.blend`
   asset URLs from `spec_snapshot`. Keep downloads in a per-job temporary
   directory.
4. Set `building_scene`, run Blender for character placement, entrance, and
   gesture, then set `rendering` for the scene/plate render.
5. Set `encoding` and use FFmpeg for source timing/freeze, Blender plate
   compositing, logo compositing, captions, and final MP4 encoding.
6. Set `uploading`, upload the MP4 to a key such as
   `workspaces/<workspaceId>/renders/<renderJobId>.mp4`, insert an `assets`
   record with `role: render_output`, then set the job to `completed`,
   `progress: 100`, and its `output_asset_id`.
7. On any failure, set `status: failed`, `progress: 100`,
   `error_code: render_failed`, and a bounded, non-secret `error_message`.

Use the existing status vocabulary in `src/web/contracts.ts`:

```text
queued → preparing → downloading_assets → building_scene → rendering
→ encoding → uploading → completed | failed
```

The worker should delete its temporary job directory on success and failure.
It must not mark a job complete if the selected character, dialogue, captions,
or branding values were ignored. The current image supports text captions, not
spoken dialogue: a non-empty `voice` or `lip_sync` is rejected before asset
download with `error_code: unsupported_performance`. Captions do not stand in
for a requested Piper/Rhubarb performance.

## Configuration by service

Set these values in the external worker's secret manager or container runtime.
Never put real values in an image, Dockerfile, `.env.example`, source file, or
deployment log.

| Service | Environment variables | Purpose |
| --- | --- | --- |
| Supabase | `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | Read immutable jobs and assets; update stages/output row. |
| Vercel Blob | `BLOB_READ_WRITE_TOKEN` | Upload final MP4s. Source assets are downloaded from the saved Blob URLs. |
| Queue authentication | `RENDER_WORKER_SECRET` | Validate the Vercel control-plane Bearer token. |
| Optional speech | `PIPER_VOICE_PATH` and any provider-specific voice configuration | Reserved for a future Piper/Rhubarb image; the current image rejects requested voice/lip-sync. |
| Optional assets | `FONTCONFIG_PATH` / application font directory as needed | Make the caption font deterministic in the image. |

The Vercel control-plane project also needs all five core variables:

```text
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
BLOB_READ_WRITE_TOKEN
RENDER_QUEUE_URL
RENDER_WORKER_SECRET
```

`RENDER_WORKER_SECRET` must be identical in Vercel and the external worker.
The current Vercel process uses the other three service credentials for its
existing fallback worker, so retain them during a migration.

## Build the worker image

The external image must contain system executables rather than trying to install
them in a Vercel Function:

```text
Python 3.11+
FFmpeg
Blender (headless-capable)
Piper and Rhubarb plus a compatible voice/rig mapping (before spoken dialogue is enabled)
required fonts and character/template packages
```

Once the worker service has its Dockerfile, build and inspect the image from
the repository root:

```sh
docker build -t ulo-videos-render-worker -f worker/Dockerfile .
docker run --rm ulo-videos-render-worker ffmpeg -version
docker run --rm ulo-videos-render-worker blender --background --version
```

Run it with a local, uncommitted environment file that contains only real
runtime values:

```sh
docker run --rm --name ulo-videos-render-worker \
  --env-file worker/.env \
  -p 8080:8080 \
  ulo-videos-render-worker
```

Then verify the container boundary without exposing the secret in shell history
or logs. Use your deployment platform's secret injection or a local HTTP client
that sources the secret from its secure environment:

```text
GET  /healthz                         → 200 and all required tools true
POST /render-jobs with valid message  → 200 after the terminal job update
POST /render-jobs without auth        → 401
POST /render-jobs with invalid body   → 400
```

For a real render test, create a new demo shot through the production app,
submit it once, and verify the job advances through Supabase to `completed`,
has an `output_asset_id`, and its `assets.blob_url` is a playable MP4. Use a
new job for each retry; the snapshot is intentionally immutable.

## Deploy and switch the queue endpoint

1. Deploy the image to a container platform that supports long-running CPU/GPU
   workloads, ephemeral disk sized for source assets and frames, and an HTTPS
   service endpoint. Allow only the Vercel deployment to call `POST
   /render-jobs` where the platform supports network allow-listing.
2. Configure the worker variables above through that platform's secret manager.
3. Verify its public/private HTTPS `GET /healthz` before directing production
   traffic to it.
4. In Vercel Project Settings → Environment Variables, replace
   `RENDER_QUEUE_URL` with the external endpoint, for example:

   ```text
   https://renderer.example.com/render-jobs
   ```

   Do not change the message body or the `Authorization: Bearer` contract.
5. Redeploy the Vercel project so the server route picks up the changed
   environment variable.
6. Submit a demo render in production and verify the completed MP4 in the
   workspace player.

Vercel does not send the other four configuration values in the dispatch body.
The external container independently receives its own secret-injected values.

## Roll back to the current Vercel worker

The existing baseline worker is still available at the deployed Vercel endpoint:

```text
https://ulo-videos.vercel.app/api/render-queue
```

If the external service is unhealthy or produces failed jobs:

1. Set Vercel `RENDER_QUEUE_URL` back to that URL.
2. Keep `RENDER_WORKER_SECRET` unchanged; the current endpoint uses the same
   Bearer authentication contract.
3. Redeploy the Vercel project.
4. Submit a fresh demo render and confirm a completed MP4 is playable.

This rollback preserves existing `render_jobs` records. Jobs already accepted
by the external service should be allowed to finish or be explicitly marked
failed; do not silently resubmit them because a render job is an immutable
snapshot and attempts must remain auditable.

The Vercel fallback currently provides the FFmpeg baseline only. Do not present
it as a Blender/Piper/Rhubarb renderer: a rollback sacrifices character
performance until the external service is restored.
