# ulo-videos — Repository Instructions

## Product intent

`ulo-videos` is a hosted, deterministic video-production workspace. The user configures a structured Scene v1 specification; the system renders it without an LLM.

```text
Browser form → validated JSON snapshot → Supabase render job → queue { renderJobId }
→ external worker → Vercel Blob MP4 → workspace video player
```

The product is not a local renderer wrapped in a web page. Vercel is the control plane and UI; media execution belongs in an external worker/container.

## Current architecture

- Next.js App Router app: `app/`
- Browser/editor helpers: `src/web/workspace-client.ts`
- Domain validation and Supabase persistence: `src/web/`
- Worker/render code: `src/ulo_videos/`
- Vercel queue endpoint: `api/render-queue.py`
- Supabase schema: `db/schema.sql`
- Production site: `https://ulo-videos.vercel.app`

The anonymous workspace cookie is used only to scope project ownership. Do not add sign-in or password-gate behavior unless explicitly requested.

## Scene and render-job contract

- Scene v1 JSON is the authoritative source of truth; do not introduce LLM prompt interpretation.
- A submitted render job is an immutable snapshot. Never render from a mutable live draft.
- Queue messages contain only `{ "renderJobId": "rj_..." }`.
- The worker fetches the job and assets, updates meaningful stages, uploads the MP4, stores an output asset record, and sets `output_asset_id`.
- The UI must resolve the output asset to `output_url`, show live status, and display a playable MP4 when complete.
- Keep render stages compatible with `src/web/contracts.ts`.

## Renderer requirements

- FFmpeg is responsible for deterministic video assembly: source timing/freeze, logo compositing, captions, and final MP4 encoding.
- Blender is responsible for the `.blend` character: placement, entrance, gesture, and character compositing.
- Piper and Rhubarb are responsible for speech and lip-sync when those stages are enabled.
- Do not describe a render as complete if the worker ignores selected character, dialogue, captions, or branding inputs. UI capability copy must state exactly what the deployed worker applies.
- A Blender-capable worker must be an external container/service, never a Vercel Function.

## Assets and branding

- `examples/ulo-videos-logo-draft-1.svg` is a **site asset**. It is the source for the public header/metadata logo at `public/ulo-videos-logo.svg`.
- `public/demo/demo-logo.svg` is a separate **demo upload asset**. It must remain independent from the site-brand asset.
- The demo flow needs separately loadable source video, `.blend` character, and logo files. A loaded demo must visibly read as ready to upload; browser security prevents populating a native file input programmatically.
- Keep the Ulo Videos brand logo in the site header and metadata. Do not restore removed “Anonymous workspace” header copy.

## UX requirements

- Production is the user-facing verification target. You may use local tooling for tests, but hand off the Vercel URL, not a localhost URL.
- Refreshing the app starts a fresh editor state. Do not auto-restore an old project, shot, or render into the editor.
- A render must make its output discoverable: display an inline playable video and an MP4 link once `output_url` is available.
- Surface actionable state, not vague prerequisite prose. The setup panel reports actual cloud service readiness.

## Environment and production configuration

The Vercel project needs these values; never print their contents:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `BLOB_READ_WRITE_TOKEN`
- `RENDER_QUEUE_URL`
- `RENDER_WORKER_SECRET`

`RENDER_QUEUE_URL` is an authenticated HTTP endpoint that accepts `{ "renderJobId": "rj_123" }` using `RENDER_WORKER_SECRET` as a Bearer token.

## Working rules

1. Read this file before working. Also read dependency-level `AGENTS.md` files before modifying code that uses that dependency. In particular, `node_modules/next/AGENTS.md` requires consulting the installed Next.js docs before changing Next behavior; Supabase package instructions require consulting their pinned README/source API.
2. Inspect existing code before adding abstractions. Extend the existing control-plane store and job contract rather than duplicating persistence or worker logic.
3. Use test-driven development: add a focused failing test, run it to observe the expected failure, then implement the minimal change.
4. Use `apply_patch` for file edits. Preserve unrelated worktree changes; do not reset, clean, or overwrite user changes.
5. Before a completion claim, run focused tests, the full relevant test suite, TypeScript checks, `npm run build`, and `git diff --check`.
6. Deploy only verified changes to Vercel production, then check the production alias and relevant live API/asset behavior.
7. Do not expose credentials, worker secrets, Supabase service-role keys, or Blob tokens in code, logs, commits, or user messages.

## Deployment verification checklist

- `npm test`
- `python3 -m unittest discover -s tests` for Python worker/render changes
- `npx tsc --noEmit`
- `npm run build`
- `git diff --check`
- Deploy: `npx vercel --prod --yes`
- Confirm `https://ulo-videos.vercel.app/api/setup-status` is ready and validate the affected production flow.
