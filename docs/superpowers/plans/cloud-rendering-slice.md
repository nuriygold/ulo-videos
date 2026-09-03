# Cloud rendering workspace slice

## Global Constraints

- The first slice is anonymous; do not add sign-in or password-gate behavior.
- Vercel is the control plane. Large media uploads go directly to Vercel Blob; server routes persist metadata and job state.
- Postgres is the source of truth for projects, shots, assets, and immutable render jobs.
- The browser submits structured JSON scene specifications; no LLM interpretation is required.
- The worker contract must remain small and asynchronous: queue messages carry renderJobId, while the worker reports meaningful job stages.
- Keep existing Python renderer behavior intact while adding the hosted Next.js surface.
- Every implementation task must have focused tests and must not duplicate an existing abstraction.

## Tasks

### Task 1: Direct Blob upload contract

Add the Vercel Blob client-token route and asset metadata helpers. Uploads must use the direct browser-to-Blob flow, with allowed media types, size limits, scoped object keys, and completion metadata persistence seams. Add focused tests for key generation and metadata validation.

### Task 2: Persistent project and shot APIs

Add anonymous-cookie project and shot APIs backed by the existing Supabase control-plane store. Extend the existing store interfaces rather than creating duplicate persistence logic. Validate scene snapshots with the existing scene contract before saving.

### Task 3: Wire the workspace UI

Replace the static dashboard actions with a minimal usable project/shot flow: create project, create/edit shot specification, request direct upload, save shot, submit render, and show render-job status/history. Keep the first UI focused on the deterministic interruption template and clearly explain cloud prerequisites.

### Task 4: Worker callback and output history

Connect the external worker callback/status contract to persisted render jobs and expose polling/status data to the UI. Keep the existing FFmpeg baseline render path producing MP4 and document the remaining Blender/audio/lip-sync prerequisites.

### Task 5: Verification and whole-branch review

Run focused tests, full Python tests where permitted, TypeScript build, diff checks, and a final code review. Report any environment limitation preventing a real cloud MP4 render.
