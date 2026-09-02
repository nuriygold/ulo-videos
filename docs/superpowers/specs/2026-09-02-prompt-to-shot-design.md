# Prompt-to-Shot Design

## Goal

Build a local application that turns a reusable interruption-spokescharacter template into a rendered video by collecting structured inputs in a form and compiling them into JSON/YAML scene specifications.

## Product shape

The first release is a local web application served on `127.0.0.1`. It provides a form for background video, pause time, character, dialogue, gesture, voice, captions, branding, and output settings. The form generates a visible, downloadable JSON scene specification and can preview or render a job.

## Architecture

The scene specification is the source of truth. A template compiler validates it and produces an execution plan. Rendering adapters are independent: FFmpeg handles video operations and final assembly; Blender handles character/compositing when available; Piper and Rhubarb are optional local speech adapters. If an adapter is missing, the UI reports the exact missing capability and keeps the scene specification usable.

The first renderer supports a deterministic baseline: import video, freeze at a timestamp, add optional captions, and export MP4. Blender character compositing is the next adapter boundary, using the same specification. ComfyUI is explicitly deferred and must not be required for the core workflow.

## Scene contract

```json
{
  "template": "interruption_spokescharacter_v1",
  "background_video": "assets/house_leak.mp4",
  "pause_at": 7.4,
  "character": {
    "asset": "assets/characters/lizard.blend",
    "position": "foreground_right",
    "entrance": "pop_in",
    "gesture": "shrug_and_point"
  },
  "dialogue": {
    "text": "Every landlord knows real estate isn't passive.",
    "voice": "local_voice_01",
    "lip_sync": "rhubarb"
  },
  "branding": {
    "logo": "assets/logo.svg",
    "caption_style": "lower_third"
  },
  "output": {
    "format": "mp4",
    "resolution": [1920, 1080],
    "fps": 30
  }
}
```

## UI and behavior

The form has a template selector, file upload controls, timestamp validation, character and gesture selectors, dialogue and voice controls, caption/branding controls, output controls, a generated-spec panel, capability status, preview, and render buttons. Uploaded files are stored under a local project directory and referenced by relative paths. Preview renders a short deterministic draft; render produces the final artifact and a job manifest.

## Reuse and extension

Templates are Python modules with a stable `compile_scene(scene)` interface. New templates can add fields without changing the renderer contract. A future node editor will read and write the same scene specification, so it is an alternate authoring surface rather than a second data model.

## Constraints

- No cloud provider or API key is required.
- No LLM or diffusion model is required for the baseline.
- Human-facing errors must identify the missing executable, file, or invalid field.
- Rendering must be reproducible for the same inputs, pinned tool versions, and scene specification.
- No application submission or external publishing behavior is in scope.

## Verification

Tests cover scene validation, form-to-spec compilation, safe asset paths, command planning, and a smoke render when FFmpeg is available. A manual verification opens the local GUI, submits a sample specification, downloads JSON, and renders a short test video.

## Delivery

The completed source will be published in a GitHub repository named `ulo-videos`. A Vercel deployment will host the browser UI and metadata/API surface under a project name beginning with `ulo`. Native Blender, FFmpeg, Piper, and Rhubarb execution remains local; the hosted UI must communicate that local rendering is required for those capabilities.
