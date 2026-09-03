# Task 1 implementation report

Status: DONE_WITH_CONCERNS

## Files changed

- `app/api/assets/upload/route.ts`
  - Added the Vercel Blob browser-direct client-token endpoint using `@vercel/blob/client` `handleUpload`.
  - Requires an established anonymous workspace cookie; no sign-in or auth was added.
  - Authorizes only exact workspace/project/role/asset-scoped pathnames.
  - Enforces role-specific content-type allowlists and byte limits.
  - Disables random suffixes and overwrites because asset IDs make keys unique and deterministic.
  - Verifies callback metadata with Blob `head` before persistence.
- `src/web/asset-upload.ts`
  - Added browser-upload role policies, safe scope and filename validation, deterministic key generation, token-payload parsing, and completed-asset metadata validation.
  - Browser uploads explicitly reject the worker-only `render_output` role.
- `src/web/integrations.ts`
  - Extended the existing `ControlPlaneStore` seam with project ownership validation and asset metadata persistence.
- `src/web/supabase-store.ts`
  - Implemented the two new store operations without introducing another persistence abstraction.
  - Asset completion writes are idempotent via upsert.
- `tests/web-asset-upload.test.ts`
  - Added six focused tests covering scoped key generation, traversal rejection, upload-intent validation, role policies, accepted completion metadata, and mismatch/size/content-type rejection.
- `package.json`
  - Expanded the TypeScript test script to run all `tests/*.test.ts`, including the new focused test file.

## Commands and results

1. `npm test` before implementation
   - Expected red result: new suite failed because `src/web/asset-upload` did not exist; existing render-job test passed.
2. `npm test` after initial implementation
   - 6 passed, 1 failed. The malformed-payload test exposed validation-order behavior.
3. `npm test` after correction
   - PASS: 7 tests, 7 passed, 0 failed.
4. `npx tsc --noEmit`
   - PASS: exit 0, no diagnostics.
5. `git diff --check`
   - PASS: exit 0, no whitespace errors.
6. `npm run build`
   - PASS: Next.js 16.3.4 production build compiled and type-checked successfully; `/api/assets/upload` was emitted as a dynamic route.
7. Final housekeeping command (`git check-ignore ...` followed by removal of generated `tsconfig.tsbuildinfo`)
   - INTERRUPTED by the user after the required verification had completed; completion could not be confirmed.

## Concerns

- No live Vercel Blob/Supabase upload callback was exercised because this task used local focused tests and build checks; deployment credentials and an actual browser upload are required for that integration check.
- The anonymous workspace cookie is intentionally the current ownership boundary because sign-in is explicitly out of scope. It is not a production authentication mechanism and should be replaced or protected by the planned password/auth gate.
- The repository already contained a large uncommitted cloud-workspace slice on `main`. This commit intentionally limits staging to Task 1 and its direct existing seams/dependencies; unrelated working-tree changes remain untouched.
- The final housekeeping command was interrupted. This does not invalidate the previously completed test, TypeScript, whitespace, or production-build checks.

## Fix round: immutable asset claims and Blender-only character uploads

Status: DONE_WITH_CONCERNS

### Review findings addressed

- Replaced asset metadata `upsert` with `insert`. An asset ID is now an immutable claim: a duplicate primary key is surfaced as an error and cannot replace metadata owned by another workspace.
- Restricted browser character uploads to `.blend` filenames and the `application/x-blender` content type. Generic `application/octet-stream` is no longer authorized or accepted at completion.
- Extracted upload authorization into a focused helper while preserving the existing browser-direct Vercel Blob token flow. Tests cover missing and mismatched workspace scope, project ownership, and exact scoped path matching.

### Commands and results

1. `npm test` (inherited partial fix baseline)
   - PASS: 9 tests, 9 passed, 0 failed.
2. `npx tsc --noEmit` (inherited partial fix baseline)
   - EXPECTED RED: `app/api/assets/upload/route.ts(46,24): error TS2304: Cannot find name 'parseAssetUploadIntent'.`
3. `node --import tsx --test tests/web-asset-upload.test.ts`
   - PASS: 9 focused tests, 9 passed, 0 failed.
4. `npx tsc --noEmit` after route integration correction
   - PASS: exit 0, no diagnostics.
5. Final `npm test`
   - PASS: 10 tests, 10 passed, 0 failed.
6. Final `npx tsc --noEmit`
   - PASS: exit 0, no diagnostics.
7. `git diff --check`
   - PASS: exit 0, no whitespace errors.
8. `npm run build`
   - PASS: Next.js 16.3.4 production build compiled and type-checked successfully; `/api/assets/upload` remained a dynamic route.

### Concerns

- No live Blob/Supabase callback was exercised locally. The focused tests verify policy, authorization, and collision behavior at the application seams; deployment credentials are still required for an end-to-end integration check.
- Some browsers may report `.blend` files with an empty or generic MIME type. The caller must submit them as `application/x-blender`; this is intentional so the upload token does not authorize arbitrary octet-stream content.
- Unrelated cloud-workspace changes remain present and are excluded from this fix commit.

### Fix-round integration result

- Verified the staged patch is limited to immutable asset-claim insertion/collision rejection, Blender-only character upload policy, authorization coverage, and this report.
- Fresh checks: `npm test` PASS (10/10), `npx tsc --noEmit` PASS, `git diff --check` PASS, and `npm run build` PASS.
- Remaining concern: no live Vercel Blob/Supabase callback was exercised; deployment credentials are required for an end-to-end upload check.
