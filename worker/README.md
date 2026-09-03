# External Blender + FFmpeg render worker

This is the media execution service, deliberately external to Vercel. It
accepts the existing queue contract and uses the same Supabase and Vercel Blob
records as the current control plane.

```json
{"renderJobId":"rj_123"}
```

`POST /` validates `Authorization: Bearer $RENDER_WORKER_SECRET`, returns
`202 Accepted`, then performs the render in the worker process. `GET /healthz`
is an unauthenticated liveness check.

## What this worker renders

For the submitted immutable Scene v1 snapshot it:

1. Downloads the source video, selected `.blend` character, and logo from the
   URLs saved in the snapshot.
2. Uses Blender to render the character as a transparent PNG sequence. The
   selected gesture must exist as an action in the `.blend`; otherwise the job
   fails rather than pretending the gesture was applied.
3. Uses FFmpeg to freeze the source at `trigger.value`, composits the character
   during that hold, resumes the source video, composites the logo, and draws
   the selected dialogue as captions.
4. Uploads `output.mp4` to Blob, creates the `render_output` asset row, and
   updates `render_jobs.output_asset_id` and the usual staged status.

Dialogue text is currently rendered as captions. Piper/Rhubarb speech and
mouth-cue stages are intentionally not claimed as enabled by this container.

## Build and run

Build from this directory so the container contains only worker files:

```sh
docker build -t ulo-videos-render-worker worker
docker run --rm -p 8080:8080 \
  -e SUPABASE_URL \
  -e SUPABASE_SERVICE_ROLE_KEY \
  -e BLOB_READ_WRITE_TOKEN \
  -e RENDER_WORKER_SECRET \
  ulo-videos-render-worker
```

Required environment variables are `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, `BLOB_READ_WRITE_TOKEN`, and
`RENDER_WORKER_SECRET`. `WORKER_ID` is optional and is written to the job for
diagnostics. Do not put any of these values in source control.

## Control-plane integration

Deploy this container to a service that exposes its HTTPS root endpoint, then
set Vercel's existing `RENDER_QUEUE_URL` to that HTTPS URL. Keep
`RENDER_WORKER_SECRET` identical in Vercel and in this container. No queue
message, database schema, browser code, or Vercel Function changes are needed.

The worker relies on the existing immutable snapshot fields: `source.video`,
the first character element's `asset`, `branding.logo`, `trigger`, `captions`,
and `output`.
