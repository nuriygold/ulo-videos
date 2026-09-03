# Handoff — ulo-videos

Date: 2026-09-02

## Objective

Build a reusable local prompt-to-video app:

- Form inputs for background video, pause time, character, gesture, dialogue, voice, captions, branding, and output.
- JSON/YAML scene specification as the source of truth.
- Python template compiler.
- Blender deterministic rendering/compositing.
- FFmpeg final assembly.
- Local TTS and lip-sync.
- Optional ComfyUI integration later.
- Publish source to GitHub as `ulo-videos`.
- Deploy the UI/API surface to Vercel with a project/URL beginning with `ulo`.

## Current location

Standalone git repository:

`/Users/claw/ulo-videos`

The original `career-ops` repository was not modified, except for its pre-existing untracked `.superpowers/sdd/career-ops-docs-2026-09-02/` artifact.

## Current state

- Git repository initialized; implementation proceeds on branch `feat/prompt-to-shot-mvp` (main receives work only via PR merge).
- Design: `docs/superpowers/specs/2026-09-02-prompt-to-shot-design.md`
- Implementation plan: `docs/superpowers/plans/2026-09-02-prompt-to-shot-implementation.md`
- SDD ledger: `.superpowers/sdd/2026-09-02-prompt-to-shot-implementation/progress.md`
- Task 1 worker was interrupted after writing files but before committing/reporting.
- Existing Task 1 files:
  - `src/ulo_videos/__init__.py`
  - `src/ulo_videos/schema.py`
  - `src/ulo_videos/templates.py`
  - `tests/test_schema.py`
- Task 1 implementation validates the interruption template and serializes stable JSON.
- Task 1 tests verified passing (5/5) on Python 3.14.6 by the recovering controller.

## Worker/process state

The surviving `codex exec` worker was terminated on purpose during handoff. No worker process should remain.

## Immediate next steps

1. Run `PYTHONPATH=src python -m unittest tests.test_schema -v`.
2. Inspect Task 1 diff, add a report, and commit it.
3. Continue Tasks 2–6 from the implementation plan using the SDD workflow: tests first, implementation, task review, commit.
4. Add the Task 7 deployment work only after end-to-end local verification.
5. For Vercel, deploy the browser interface only; Blender/FFmpeg/Piper/Rhubarb remain local because native long-running rendering is not suitable for Vercel functions.
6. Create and push GitHub repository `ulo-videos` only when source is ready.

## Important constraints

- Do not edit the career-ops repository for this app.
- No provider API keys are required for the baseline.
- Do not bundle user media or secrets in the public repository.
- Verify actual render output before claiming completion.
- On this machine (`/Users/claw`): FFmpeg 8.1.1 is installed. Blender, Piper, and Rhubarb are NOT installed, so their adapters must capability-detect as missing and report status instead of failing.
- career-ops update check previously reported `v1.23.0 → v1.31.0`; it was not applied.
