# Prompt-to-Shot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local form-driven prompt-to-shot application with a JSON scene contract and deterministic FFmpeg/Blender adapter boundaries.

**Architecture:** A Python standard-library HTTP server serves the form and JSON endpoints. Pure Python modules validate and compile scene specifications; renderer adapters plan and execute local commands. The browser is an authoring surface, not the source of truth.

**Tech Stack:** Python 3.11+, HTML/CSS/vanilla JavaScript, FFmpeg, optional Blender/Piper/Rhubarb.

**Spec:** `docs/superpowers/specs/2026-09-02-prompt-to-shot-design.md`

## Global Constraints

- No cloud provider or API key is required.
- No LLM or diffusion model is required for the baseline.
- JSON is the canonical generated scene format; YAML support is optional after the JSON flow is stable.
- Rendering must be reproducible for the same inputs, pinned tool versions, and scene specification.
- Uploaded assets remain local to the project directory.

### Task 1: Scene contract and template compiler

**Files:** Create `src/prompt_to_shot/schema.py`, `src/prompt_to_shot/templates.py`, `tests/test_schema.py`.

- [ ] Write failing tests for required fields, timestamp validation, output normalization, and deterministic JSON serialization.
- [ ] Run `python -m unittest tests.test_schema -v` and confirm failure because modules are absent.
- [ ] Implement typed validation and `compile_scene(payload) -> dict` for `interruption_spokescharacter_v1`.
- [ ] Run the test and confirm it passes.

### Task 2: Local render command planning

**Files:** Create `src/prompt_to_shot/renderers.py`, `tests/test_renderers.py`.

- [ ] Write failing tests for safe relative asset resolution, FFmpeg preview command planning, and clear missing-tool errors.
- [ ] Run the targeted tests and confirm failure.
- [ ] Implement `Toolchain`, `plan_ffmpeg_render`, `plan_blender_render`, and `run_command` without shell interpolation.
- [ ] Run targeted and full tests.

### Task 3: HTTP application and browser form

**Files:** Create `src/prompt_to_shot/server.py`, `src/prompt_to_shot/__main__.py`, `templates/index.html`, `templates/app.js`, `templates/styles.css`, `tests/test_server.py`.

- [ ] Write failing tests for `GET /`, `POST /api/spec`, and JSON download behavior.
- [ ] Run targeted tests and confirm failure.
- [ ] Implement the local server, static form, validation response, and generated-spec panel.
- [ ] Run the test suite.

### Task 4: Asset storage and job manifests

**Files:** Modify `src/prompt_to_shot/server.py`; create `src/prompt_to_shot/projects.py`, `tests/test_projects.py`.

- [ ] Write failing tests for accepted media extensions, collision-safe filenames, and manifest persistence.
- [ ] Implement local project directories and upload handling.
- [ ] Run all tests.

### Task 5: Optional speech, lip-sync, and Blender adapters

**Files:** Modify `src/prompt_to_shot/renderers.py`; create `src/prompt_to_shot/adapters.py`, `tests/test_adapters.py`, `README.md`, `requirements.txt`.

- [ ] Write failing tests for capability detection and adapter plan generation for Piper, Rhubarb, and Blender.
- [ ] Implement executable detection and adapter commands with explicit status reporting.
- [ ] Document macOS setup and the exact baseline/render modes.
- [ ] Run all tests.

### Task 6: End-to-end verification

**Files:** Create `examples/lizard-insurance.json`, `scripts/smoke-render.py`.

- [ ] Validate the example scene through the compiler.
- [ ] Run the server and verify the form in a browser.
- [ ] Render a short sample if FFmpeg is installed; otherwise verify the generated command and report the missing dependency.

### Task 7: Public delivery

**Files:** Modify `README.md`, add deployment configuration appropriate to the selected web runtime, and update the repository metadata.

- [ ] Verify the project has no secrets, local absolute paths, or bundled user assets.
- [ ] Create the GitHub repository `ulo-videos` and push the completed source.
- [ ] Deploy the browser UI/API surface to a Vercel project whose name begins with `ulo`.
- [ ] Verify the deployed URL serves the form and clearly labels native local rendering requirements.
