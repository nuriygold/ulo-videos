# ulo-videos

A local prompt-to-video app: a browser form authors a JSON scene specification,
and the app turns it into deterministic, JSON-safe command plans for a
background-video "shot" — play the background, freeze at `pause_at`, and
optionally layer on a Blender character plate, local Piper speech, Rhubarb
lip-sync mouth cues, and burned-in captions.

The scene specification is the source of truth. Planning is pure: nothing is
rendered or executed as a side effect, plans carry no wall-clock data, and a
missing tool is always reported as status instead of failing the request. The
whole app runs on the Python standard library — `requirements.txt` documents
zero Python dependencies.

## How it works

1. The form (or any client) posts a scene payload to `POST /api/spec`.
2. `ulo_videos.templates.compile_scene` validates it against the
   `interruption_spokescharacter_v1` template and returns the compiled scene.
3. `ulo_videos.renderers` plans the baseline FFmpeg preview command.
4. `ulo_videos.adapters` plans the optional Piper speech, Rhubarb
   lip-sync, and Blender character-plate steps, each with explicit capability
   status.

Plans are plain dicts of strings, numbers, booleans, lists, and `null`, so they
serialize with the repository's canonical JSON convention (indented,
key-sorted). `renderers.run_command` is the library-level executor for a
planned argv — it never uses a shell. The server itself plans and displays
commands; it does not execute renders.

## Requirements

- Python 3.11 or newer (developed and tested on 3.14). Standard library only;
  there is nothing to `pip install` for this project.
- Optional system executables, capability-detected on `PATH` at runtime:
  `ffmpeg` (required for any rendering), `blender`, `piper`, `rhubarb`.

## macOS setup

```sh
brew install ffmpeg              # required: baseline render and final assembly
brew install --cask blender      # optional: character plate render
```

Piper and Rhubarb are not in Homebrew; install them directly:

- **Piper** (local text-to-speech): `pip install piper-tts` installs the
  `piper` command, or download a release build from
  [github.com/rhasspy/piper](https://github.com/rhasspy/piper). Voice models
  come from [huggingface.co/rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices)
  — put a model at `assets/voices/<voice>.onnx` (keep the `.onnx.json` sidecar
  next to it) and name that stem in the scene's `dialogue.voice`.
- **Rhubarb** (lip sync): download a release from
  [github.com/DanielSWolf/rhubarb-lip-sync/releases](https://github.com/DanielSWolf/rhubarb-lip-sync/releases)
  and place the `rhubarb` executable on your `PATH` (for example
  `/usr/local/bin` or `/opt/homebrew/bin`).

Detection is deliberately simple: `renderers.Toolchain` resolves tool names
with `shutil.which`, so anything on your `PATH` is found and there is no
configuration file. Nothing is auto-installed. A tool that is not on `PATH` is
reported as unavailable with a named reason — it never raises.

## Render modes

### Baseline (ffmpeg only)

With just `ffmpeg` installed, a render is a silent draft: the background video
plays to `pause_at`, the last frame is frozen for 2 seconds, the result is
scaled to the requested resolution and fps, and it is exported with `-an` to
`build/preview.mp4` (libx264, crf 18, yuv420p). The form still compiles and
lets you download the scene JSON, and the plan displays its command.

Captions are the one conditional inside the baseline: when the installed
ffmpeg build exposes the `drawtext` filter and `branding.caption_style` is not
`none`, the dialogue text is burned in at the chosen position. ffmpeg builds
vary — some, including the current Homebrew installation on this project's
development machine, omit `drawtext`. In that case the plan reports
`captions.applied: false` with a reason naming the missing filter, and keeps
`dialogue.text` in the plan for a capable build or adapter.

### What each optional tool unlocks

| Tool | Unlocks | Planned output |
| --- | --- | --- |
| `ffmpeg` + `drawtext` | Burned-in captions per `branding.caption_style` (`lower_third`, `top`, `center`) | inside `build/preview.mp4` |
| `blender` | Character plate: headless render of `character.asset`, frame 1, PNG | `build/blender-frame0001.png` |
| `piper` | Speech: `dialogue.text` synthesized with the `dialogue.voice` model (text is delivered on stdin) | `build/speech.wav` |
| `rhubarb` | Lip sync: `mouthCues` timings derived from the speech wav (requires `dialogue.lip_sync: "rhubarb"`) | `build/mouth-cues.json` |

### Adapter status, not failure

Every adapter plan carries `status` (`ready`, `missing_assets`, or
`unavailable`), an `applied` flag, and a `reason`. When a tool is missing the
plan keeps the scene data and paths it can resolve and names the missing
capability, mirroring how the captions pattern reports the `drawtext` filter:

```json
{
  "applied": false,
  "argv": null,
  "assets": {
    "dialogue.voice_model": "/path/to/project/assets/voices/local_voice_01.onnx"
  },
  "executable": null,
  "input": {
    "kind": "stdin",
    "text": "Every landlord knows real estate isn't passive."
  },
  "missing_assets": [
    {
      "field": "dialogue.voice_model",
      "path": "/path/to/project/assets/voices/local_voice_01.onnx"
    }
  ],
  "output": {
    "format": "wav",
    "path": "/path/to/project/build/speech.wav"
  },
  "reason": "piper executable not found; dialogue.text is kept in the plan so speech can be synthesized by a capable build or adapter",
  "status": "unavailable",
  "tool": "piper",
  "voice": "local_voice_01"
}
```

`ulo_videos.adapters.adapter_status()` returns the one-call capability
report: per-tool availability for `ffmpeg`, `blender`, `piper`, `rhubarb`
plus the captions capability. The browser's tool panel (`GET /api/tools`)
lists the core `ffmpeg`/`blender` toolchain status.

## Run the server

From the repository root:

```sh
PYTHONPATH=src python3 -m ulo_videos            # http://127.0.0.1:8000
PYTHONPATH=src python3 -m ulo_videos --port 8080
```

Endpoints:

- `GET /` — the browser form (`templates/`).
- `GET /api/tools` — core toolchain availability.
- `POST /api/spec` — compile a scene payload and return it with the planned
  FFmpeg command.
- `GET /api/spec/download` — the last generated spec as the canonical
  `scene.json`.
- `POST /api/upload?filename=NAME` — store a media asset under `assets/`;
  accepted extensions are `.mp4 .mov .webm .mkv .png .jpg .jpeg .svg .blend
  .wav .mp3`, up to 256 MiB, recorded in `assets/manifest.json`.

## Deploy the form to Vercel

The local app is the source of truth, and the deployment is the public read of
the same app: the browser form, the scene compiler, the render planner, and
toolchain status, served by the same `dispatch_request` routing the local
`http.server` app uses. A serverless function has no FFmpeg or Blender and
mounts a read-only filesystem, so the hosted page compiles and plans commands
and clearly labels that rendering itself runs locally — it never executes a
render, and it never fails a request for a missing tool.

Deploy with the Vercel CLI from the repository root:

```sh
npm install -g vercel          # or: brew install vercel-cli
vercel login
vercel                         # link the repo; name the project ulo-videos
vercel --prod                  # promote the current deployment to production
```

Use a project name beginning with `ulo` (for example `ulo-videos`) when the
CLI asks. Configuration lives in the repository:

- `api/index.py` — the Vercel entry point: a WSGI callable that delegates
  every route to `ulo_videos.server.make_wsgi_app`, with nothing
  Vercel-specific in the app itself.
- `vercel.json` — CDN rewrites that serve the form and its scripts at `/`,
  `/app.js`, and `/styles.css` straight from the repository's `templates/`
  files, while the `/api/*` routes reach the function natively; plus
  `excludeFiles` that keeps tests, docs, examples, scripts, media assets,
  and build output out of the function bundle. Anything else in the
  repository rides along inert.
- `.python-version` — pins the runtime to Python 3.14, matching local
  development. The function stays standard-library only; `requirements.txt`
  documents zero Python dependencies.

What works deployed:

- `GET /` — the form, with the local-rendering requirement labeled on the page.
- `GET /api/tools` — reports `ffmpeg`/`blender` as `available: false` because
  the function has no media tools; it is status, never an error.
- `POST /api/spec` — compiles and validates the scene and returns HTTP 200
  with the scene, `plan: null`, and a named `plan_error` (the host has no
  ffmpeg); the compiled scene remains fully usable and downloadable.
- `GET /api/spec/download` — the last spec generated by that function
  instance, as canonical JSON.

What requires the local machine:

- Rendering. The planned FFmpeg command, the Blender character plate, Piper
  speech, and Rhubarb lip sync all execute native executables against a local
  project checkout — run the local server for that.
- `POST /api/upload`. Uploads write into the project's `assets/` directory and
  `assets/manifest.json`, which a deployment mounts read-only, so the request
  fails with a clean JSON error (`could not store …`) instead of storing
  anything. The 256 MiB upload limit is also a local-machine rule: serverless
  request bodies are capped at a few MiB by the platform, so large uploads
  never reach the app there.

Everything else — validation, canonical JSON, and the 400/404/405/413/422
error semantics of the API surface — is shared behavior, because both the
local handler and the deployed function call the same dispatcher. Two
deployment nuances: unknown non-API paths 404 at the CDN edge rather than
through the dispatcher's JSON, and asset paths resolve after the ffmpeg
requirement is checked, so on a host without ffmpeg a malformed asset path
surfaces as a named `plan_error` rather than a validation error.

## Run the tests

From the repository root; no network, media files, or installed tools are
required because tests inject tool lookups and filter probes:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Layout

- `src/ulo_videos/schema.py` — scene contract primitives.
- `src/ulo_videos/templates.py` — `compile_scene` / `serialize_scene`.
- `src/ulo_videos/renderers.py` — `Toolchain`, command planning and
  shell-free execution.
- `src/ulo_videos/adapters.py` — optional Piper / Rhubarb / Blender
  adapter planning and capability status.
- `src/ulo_videos/projects.py` — upload storage and manifests.
- `src/ulo_videos/server.py` — stdlib HTTP application and browser form,
  with the shared request dispatcher and the WSGI adapter factory.
- `api/index.py` — the Vercel function entry (see "Deploy the form to
  Vercel").
- `templates/` — the static form assets.
