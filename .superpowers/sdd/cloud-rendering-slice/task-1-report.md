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
