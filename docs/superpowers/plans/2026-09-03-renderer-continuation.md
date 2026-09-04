# Renderer Continuation Plan

## Summary

Land the existing rendering work safely, verify the visible FFmpeg edits in production, then add `.gltf`, `.glb`, and `.fbx` character conversion in a second PR. Production remains on the Vercel fallback until an external-worker provider is explicitly selected.

## PR 1 — Stabilize and Land Rendering

Continue on `blender-worker-compositing`. The PR must target `origin/main@74ac6b9` and review the full `origin/main..HEAD` diff, which includes all six external-worker and compositing commits.

- Restore live renderer readiness alongside the new workflow instructions.
- Extend `/api/setup-status` with renderer mode, reachability, and exact capabilities: freeze/resume, logo, captions, character, source audio, speech, lip-sync, and supported character formats.
- Add unauthenticated health responses to both queue implementations. External readiness must require FFmpeg, Blender, and `rsvg-convert`.
- Show users exactly what the active fallback applies: freeze/resume, logo, and captions. Clearly identify character, source audio, voice, and lip-sync as unavailable.
- Default `voice` and `lip_sync` to empty strings, remove their required state, and disable or mark those controls unavailable while speech capabilities are false.
- Make the external composite planner tolerate legacy non-empty `voice`/`lip_sync` values and render the supported silent/captioned result instead of failing.
- Keep the canonical demo SVG, but rasterize SVG logos to a transparent PNG in the browser before Blob upload so the fallback never depends on unsupported static-FFmpeg SVG decoding.
- Make the Docker image explicitly amd64-only and fail early on an incompatible architecture.
- Correct worker documentation: the synchronous endpoint is suitable for testing but must not be used as the production dispatcher for long renders until a durable provider queue exists.
- Do not change production `RENDER_QUEUE_URL` to the external worker.

## PR 2 — Character Format Import

After PR 1 merges, branch from updated main as `character-import-formats`.

- Accept `.blend`, `.gltf`, `.glb`, and `.fbx` character uploads using extension-aware MIME validation. Preserve the uploaded filename, valid MIME type, and Blob URL instead of coercing every character to Blender MIME.
- Treat `.blend` as the unchanged native path.
- During `building_scene`, import glTF/GLB or FBX into Blender 5.2.1, validate the imported scene, and save a temporary `.blend` inside the job workspace.
- Require an active camera, at least one armature, and exactly one matching requested gesture action.
- Normalize gesture names with Unicode NFKC, lowercase text, non-alphanumeric runs converted to underscores, and surrounding underscores removed. Zero or ambiguous matches must fail with an actionable `render_failed` message.
- Reject unresolved external textures or buffers. Version one supports self-contained `.gltf`, GLB, and embedded-resource FBX; recommend GLB for portable uploads.
- Never silently render a static character when import or gesture validation fails.
- Keep the queue message exactly `{"renderJobId":"rj_..."}` and retain the existing database/status vocabulary.
- Update renderer capabilities to advertise the additional formats only when the external worker reports them.
- Keep OBJ, Piper, Rhubarb, generated speech, and production worker deployment out of this PR.

## Verification and Landing

Develop each correction test-first, then run:

- `PYTHONPATH=src python3.12 -m unittest discover -s tests`
- `PYTHONPATH=.:src python3.12 -m unittest discover -s worker/tests -t worker/tests`
- `npm test`
- `npx tsc --noEmit`
- `npm run build`
- `git diff --check`

Add an amd64 GitHub Actions worker job that:

- Builds the pinned Blender 5.2.1 image.
- Executes FFmpeg, Blender, and `rsvg-convert` health checks.
- Opens and renders the Blender 5.0.2 demo asset.
- Runs a real FFmpeg composition and samples frames before, during, and after interruption to prove freeze/resume, logo visibility, caption timing, and termination.
- Generates small Blender fixtures and proves `.blend`, self-contained `.gltf`, `.glb`, and `.fbx` success plus missing-camera, missing-armature, missing-gesture, ambiguous-gesture, and missing-sidecar failures.

After PR 1 merges and Vercel deploys, verify `https://ulo-videos.vercel.app` from a fresh refresh:

1. The workspace starts blank.
2. All demo buttons visibly load assets.
3. Save and submit a demo shot.
4. The job completes and the MP4 plays.
5. The source freezes at the requested timestamp, the logo appears, the caption appears only during interruption, and the source resumes.
6. The UI explicitly states that the fallback did not apply character or speech stages.
7. `/api/setup-status` reports the fallback mode and matching capabilities.

Perform a fresh full-diff review before each merge. Merge only through PRs; never commit directly to `main`.

## Assumptions

- No external renderer is deployed or selected in this continuation.
- Production keeps using the current Vercel fallback after PR 1.
- External deployment requires a later provider decision and a durable dispatch/claim design; the synchronous worker must not be placed behind production `RENDER_QUEUE_URL`.
- No authentication or password gate is added.
