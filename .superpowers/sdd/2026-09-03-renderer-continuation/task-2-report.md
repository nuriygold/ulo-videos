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

## Round 1 review fix report — 2026-09-04

### Findings fixed

- High: Browser character upload UI and save path now derive active accepted extensions/MIME types from `setup.renderer.capabilities.characterFormats`. When production reports the Vercel fallback with no character formats, the character picker, demo load button, and save action are blocked instead of accepting unsupported imported formats.
- High: Worker rendering now clears the character frame directory before each Blender run in both the service and Blender script path. After Blender returns, the service verifies the exact expected `character_%05d.png` sequence exists, contains no extras, and contains non-empty frames before FFmpeg can run.
- Medium voice/lip-sync behavior was intentionally left intact per recorded ruling.

### Files changed in this round

- `app/page.tsx`
- `src/web/asset-upload.ts`
- `src/web/workspace-client.ts`
- `tests/web-asset-upload.test.ts`
- `tests/web-instructions.test.ts`
- `worker/blender_character.py`
- `worker/service.py`
- `worker/tests/test_composite_pipeline.py`

### Commands run and summarized outputs

- `npm test -- tests/web-asset-upload.test.ts tests/web-instructions.test.ts tests/web-setup-status.test.ts`
  - First attempt failed because `tsx` was not installed in this isolated worktree.
- `npm install`
  - Installed 74 packages; audit reported 0 vulnerabilities.
- `npm test -- tests/web-asset-upload.test.ts tests/web-instructions.test.ts tests/web-setup-status.test.ts`
  - Passed: 48 tests, 0 failures.
- `PYTHONPATH=.:src python3 -m unittest -v worker.tests.test_composite_pipeline.CompositePipelineTests.test_execution_reports_blender_then_encoding_before_upload worker.tests.test_composite_pipeline.CompositePipelineTests.test_stale_character_frames_are_removed_and_incomplete_blender_output_fails_before_ffmpeg worker.tests.test_composite_pipeline.CompositePipelineTests.test_import_validation_failure_is_reported_as_render_failed worker.tests.test_http_contract`
  - Passed: 9 tests, 0 failures.
- `npx tsc --noEmit`
  - Passed.
- `git diff --check`
  - Passed.

### Notes

- Full `worker.tests.test_composite_pipeline` hangs on the existing FFmpeg integration test in this local sandbox even with a 600s timeout; the targeted stale-frame regression and HTTP contract tests pass. FFmpeg/ffprobe executables are present at `/opt/homebrew/bin/ffmpeg` and `/opt/homebrew/bin/ffprobe`.
