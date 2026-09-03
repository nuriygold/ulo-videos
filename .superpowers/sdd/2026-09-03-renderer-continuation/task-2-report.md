# Task 2: Character Format Import — Report

## What I implemented

- Added extension-aware character upload validation for `.blend`, `.gltf`, `.glb`, and `.fbx` with these MIME types: `application/x-blender`, `model/gltf+json`, `model/gltf-binary`, and `application/octet-stream`.
- Preserved the uploaded character filename and valid MIME type through the browser upload path instead of coercing every character upload to Blender MIME.
- Updated the character picker and workflow copy to advertise the supported formats and recommend self-contained GLB uploads.
- Propagated reported worker character formats through setup status. Native `.blend` remains available for an external worker; imported formats are advertised only when reported by that worker.
- Added external-worker health capabilities for `.blend`, `.gltf`, `.glb`, and `.fbx` without changing the queue message or render-job vocabulary.
- Kept `.blend` on its existing native Blender-open path. For glTF/GLB/FBX, the worker now runs Blender import mode during `building_scene`, validates the imported scene, and saves `input/imported-character.blend` within the job workspace.
- Enforced an active camera, one or more armatures, and exactly one normalized gesture action. Normalization uses Unicode NFKC, lowercase, non-alphanumeric runs as underscores, and trims surrounding underscores.
- Rejected external glTF/GLB buffers and images, plus unpacked FBX textures. Import/gesture failures reach the existing `render_failed` status with the actionable error message.

## TDD evidence

### RED

- `npm test -- tests/web-asset-upload.test.ts tests/web-setup-status.test.ts`
  - Failed as expected: character policy contained only `application/x-blender`; setup status exposed only `.blend`.
- `PYTHONPATH=.:src python3 -m unittest worker.tests.test_composite_pipeline worker.tests.test_http_contract`
  - Failed as expected: non-native assets were opened as `.blend`, Unicode gesture normalization collapsed word boundaries, and worker health advertised only `.blend`.
- `npm test -- tests/web-setup-status.test.ts`
  - Self-review regression test failed as expected when a worker-reported `.gltf` hid the native `.blend` format.

### GREEN

- Focused browser suite: 47 tests passed.
- Focused worker suite: 19 tests passed; 1 FFmpeg-dependent test skipped.
- Full verification is listed below.

## Tests and results

- `npm test` — 47 passed.
- `PYTHONPATH=src python3.12 -m unittest discover -s tests` — 162 passed.
- `PYTHONPATH=.:src python3.12 -m unittest discover -s worker/tests -t worker/tests` — 19 passed, 1 skipped (requires FFmpeg).
- `npx tsc --noEmit` — passed.
- `npm run build` — passed.
- `git diff --check` — passed.
- `npx vercel --prod --yes` — deployed successfully and aliased to `https://ulo-videos.vercel.app`.
- `https://ulo-videos.vercel.app/api/setup-status` — ready; correctly reports the deployed Vercel fallback and no character formats.

## Files changed

- `app/page.tsx`
- `src/web/asset-upload.ts`
- `src/web/setup-status.ts`
- `src/web/workspace-client.ts`
- `tests/web-asset-upload.test.ts`
- `tests/web-instructions.test.ts`
- `tests/web-setup-status.test.ts`
- `worker/blender_character.py`
- `worker/pipeline.py`
- `worker/service.py`
- `worker/tests/test_composite_pipeline.py`
- `worker/tests/test_http_contract.py`

## Self-review findings

- Found and fixed an external-health edge case: native `.blend` is retained even if a worker health response lists only an imported format.
- Confirmed the queue message contract is unchanged: `{"renderJobId":"rj_..."}`.
- No unresolved code-review findings. The explicit no-subagent instruction prevented external review; this report reflects an in-session self-review.

## Issues or concerns

- The local machine has no `blender` executable, so real Blender 5.2.1 import/render fixtures were not run locally. The pinned Docker image and worker deployment remain outside this task’s scope, as requested.
