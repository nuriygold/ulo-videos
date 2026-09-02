#!/usr/bin/env python3
"""End-to-end smoke render for the prompt-to-shot repository.

`python3 scripts/smoke-render.py` is the repository's end-to-end gate. It runs
from a plain checkout with no network access, no downloads, and no PYTHONPATH
setup (the script puts the repository's `src/` on `sys.path` itself), and it
does real work end to end:

1. reports toolchain presence and the installed ffmpeg's caption capability;
2. builds a throwaway project under `<build-dir>/smoke-project/`: the example
   references `house_leak.mp4` and `logo.svg`, which do not exist in the
   repository, so the script synthesizes both — an ffmpeg `testsrc` video
   sized to the scene's resolution and long enough to cover `pause_at`, plus a
   minimal placeholder `logo.svg` — and copies the committed
   `assets/characters/lizard.blend` into the project. The example scene is
   therefore fully reproducible from the repository alone;
3. validates `examples/lizard-insurance.json` through
   `templates.compile_scene` and checks the file is the canonical
   serialization of its own compiled scene;
4. plans the baseline FFmpeg render and the Blender character-plate render;
5. executes each plan's argv through `renderers.run_command` (never a shell);
6. verifies every produced artifact exists, is non-empty, and is valid media
   (ffprobe plus a full ffmpeg null-decode for the video, PNG signature and
   IHDR for the character plate); and
7. starts the real HTTP server on an ephemeral port and verifies the browser
   form surface over HTTP.

Missing optional tools (piper, rhubarb) and missing ffmpeg capabilities
(drawtext captions) are reported as named statuses, never failures, mirroring
the library's "status, not failure" contract. Exit code 0 means every executed
render produced a valid artifact; any failure exits non-zero.

Usage:
    python3 scripts/smoke-render.py
    python3 scripts/smoke-render.py --build-dir /tmp/smoke

The default build directory `<repo>/build` is gitignored; a `--build-dir`
override is not, so the smoke-project/ outputs land in that directory.
"""

import argparse
import hashlib
import json
import math
import shutil
import struct
import sys
import threading
import traceback
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from prompt_to_shot import adapters, renderers, server
from prompt_to_shot.renderers import (
    MissingToolError,
    Toolchain,
    prepare_output,
    run_command,
)
from prompt_to_shot.templates import compile_scene, serialize_scene

EXAMPLE_NAME = "examples/lizard-insurance.json"
SMOKE_PROJECT_NAME = "smoke-project"
RENDER_TIMEOUT_SECONDS = 300
PROBE_TIMEOUT_SECONDS = 60
FORM_TIMEOUT_SECONDS = 30
LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="96" '
    'viewBox="0 0 320 96">'
    '<rect width="320" height="96" fill="#101820"/>'
    '<text x="160" y="60" font-family="sans-serif" font-size="32" '
    'fill="#f5f7fa" text-anchor="middle">LOGO</text>'
    "</svg>\n"
)


class SmokeFailure(Exception):
    """Raised when a smoke step fails; main turns it into a non-zero exit."""


def main(argv=None):
    """Run every smoke stage and return the process exit code."""
    args = parse_args(argv)
    try:
        run(Path(args.build_dir).expanduser())
    except SmokeFailure as error:
        print(f"\nSMOKE FAILED: {error}")
        return 1
    except Exception:
        print("\nSMOKE FAILED: unexpected error")
        traceback.print_exc()
        return 1
    print("SMOKE OK")
    return 0


def run(build_dir):
    """Execute the smoke stages; each stage prints its own status block."""
    project_root = (build_dir / SMOKE_PROJECT_NAME).resolve()
    print("prompt-to-shot smoke render")
    print(f"repo: {REPO_ROOT}")
    print(f"build dir: {build_dir.resolve()}")
    print()
    chain = Toolchain(tools=adapters.ADAPTER_TOOLS)
    report_tools(chain)
    scene = compile_example()
    build_project(project_root, scene, chain)
    plans = plan_renders(scene, project_root, chain)
    artifacts = execute_renders(plans)
    verify_artifacts(scene, artifacts, chain)
    report_adapters(scene, project_root, chain)
    verify_form(scene, project_root)
    print("[summary]")
    for tool, path in artifacts.items():
        print(f"  {tool} artifact: {_display(path)}")
    print()


def report_tools(chain):
    """Print toolchain presence and caption capability as status, not failure."""
    print("[tools]")
    for name in adapters.ADAPTER_TOOLS:
        path = chain.resolve(name)
        state = f"available   {path}" if path else "unavailable (not on PATH; optional)"
        print(f"  {name:<8} {state}")
    if chain.supports_filter("ffmpeg", "drawtext"):
        print("  captions available: the installed ffmpeg exposes drawtext")
    else:
        print(f"  captions not available: {renderers.CAPTION_NOT_RENDERED_REASON}")
    print()


def compile_example():
    """Validate the example through the compiler and its canonical round-trip."""
    print("[compile]")
    path = REPO_ROOT / EXAMPLE_NAME
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise SmokeFailure(f"cannot read {EXAMPLE_NAME}: {error}") from None
    try:
        scene = compile_scene(json.loads(raw))
    except ValueError as error:
        raise SmokeFailure(f"{EXAMPLE_NAME} does not compile: {error}") from None
    _check(
        serialize_scene(scene) == raw,
        f"{EXAMPLE_NAME}: compiled against template {scene['template']!r}",
    )
    print("  canonical round-trip holds: file == serialize_scene(compile_scene(file))")
    print()
    return scene


def build_project(project_root, scene, chain):
    """Create the smoke project: synthesized media plus the committed character."""
    print(f"[project] {project_root}")
    if project_root.exists():
        # The script only ever removes this directory that it itself generates.
        shutil.rmtree(project_root)
    for directory in ("assets/characters", "assets/voices"):
        (project_root / directory).mkdir(parents=True, exist_ok=True)
    _synthesize_background(project_root / scene["background_video"], scene, chain)
    logo = project_root / scene["branding"]["logo"]
    logo.parent.mkdir(parents=True, exist_ok=True)
    logo.write_text(LOGO_SVG, encoding="utf-8")
    print(f"  {scene['branding']['logo']}: placeholder logo written")
    source = REPO_ROOT / scene["character"]["asset"]
    if not source.is_file():
        raise SmokeFailure(f"committed character asset is missing: {source}")
    shutil.copyfile(source, project_root / scene["character"]["asset"])
    shutil.copyfile(
        REPO_ROOT / "assets/characters/ATTRIBUTION.md",
        project_root / "assets/characters/ATTRIBUTION.md",
    )
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    print(
        f"  {scene['character']['asset']}: copied from the committed asset "
        f"(sha256 {digest[:16]}...)"
    )
    print()


def _synthesize_background(target, scene, chain):
    """Render the synthetic background video with an ffmpeg testsrc source."""
    executable = str(chain.require("ffmpeg"))
    pause_at = scene["pause_at"]
    duration = math.ceil(pause_at + renderers.DEFAULT_FREEZE_SECONDS + 1.0)
    width, height = scene["output"]["resolution"]
    argv = [
        executable,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size={width}x{height}:rate={scene['output']['fps']}:duration={duration}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        str(target),
    ]
    print(
        f"  {scene['background_video']}: synthesizing testsrc {width}x{height} "
        f"for {duration}s (covers pause_at={pause_at})"
    )
    result = run_command(argv, timeout=RENDER_TIMEOUT_SECONDS)
    if result["returncode"] != 0 or not target.is_file() or target.stat().st_size == 0:
        raise SmokeFailure(
            f"could not synthesize {target.name} "
            f"(exit {result['returncode']}):\n{_tail(result['stderr'])}"
        )
    print(f"  {scene['background_video']}: written ({target.stat().st_size} bytes)")


def plan_renders(scene, project_root, chain):
    """Plan both renders and require every resolved asset to exist."""
    print("[plans]")
    try:
        plans = {
            "ffmpeg": renderers.plan_ffmpeg_render(scene, project_root, chain),
            "blender": renderers.plan_blender_render(scene, project_root, chain),
        }
    except MissingToolError as error:
        raise SmokeFailure(f"cannot plan the renders: {error}") from None
    for tool, plan in plans.items():
        missing = ", ".join(entry["field"] for entry in plan["missing_assets"])
        suffix = f", missing assets: {missing}" if missing else ""
        _check(plan["status"] == "ready" and not plan["missing_assets"],
               f"{tool}: plan status={plan['status']}{suffix}")
    captions = plans["ffmpeg"]["captions"]
    if captions["applied"]:
        print("  captions applied by the installed ffmpeg")
    else:
        _check(bool(captions["reason"]), "unapplied captions carry a named reason")
        print(f"  captions not applied (reason: {captions['reason']})")
    for tool, plan in plans.items():
        print(f"  {tool} -> {_display(plan['output']['path'])}")
    print()
    return plans


def execute_renders(plans):
    """Execute each plan's argv and collect the produced artifact paths."""
    print("[renders]")
    artifacts = {}
    for tool, plan in plans.items():
        prepare_output(plan)
        result = run_command(plan["argv"], timeout=RENDER_TIMEOUT_SECONDS)
        produced = Path(plan["output"]["path"])
        if result["returncode"] != 0:
            raise SmokeFailure(
                f"{tool} render exited {result['returncode']}:\n{_tail(result['stderr'])}"
            )
        _check(produced.is_file(), f"{tool}: exit 0, wrote {_display(produced)}")
        artifacts[tool] = produced
    print()
    return artifacts


def verify_artifacts(scene, artifacts, chain):
    """Prove each artifact is a non-empty, decodable media file."""
    print("[artifacts]")
    for tool, path in artifacts.items():
        size = path.stat().st_size
        _check(size > 0, f"{_display(path)}: non-empty ({size} bytes)")
        if path.suffix.lower() == ".png":
            width, height = _png_dimensions(path)
            _check(_null_decode(path, chain) == "",
                   f"{_display(path)}: valid PNG {width}x{height}, ffmpeg decode clean")
        else:
            _verify_video(scene, path, chain)
    print()


def _verify_video(scene, path, chain):
    """Probe the rendered video and null-decode it end to end."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        result = run_command(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,width,height",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            timeout=PROBE_TIMEOUT_SECONDS,
        )
        if result["returncode"] != 0:
            raise SmokeFailure(
                f"ffprobe could not read {_display(path)}:\n{_tail(result['stderr'])}"
            )
        report = json.loads(result["stdout"])
        stream = report["streams"][0]
        width, height = scene["output"]["resolution"]
        _check(
            (stream.get("width"), stream.get("height")) == (width, height),
            f"{_display(path)}: {stream.get('codec_name')} {width}x{height}",
        )
        expected = scene["pause_at"] + renderers.DEFAULT_FREEZE_SECONDS
        duration = float(report["format"]["duration"])
        _check(
            duration >= expected - 0.5,
            f"{_display(path)}: duration {duration:.2f}s covers "
            f"pause_at + freeze ({expected:.2f}s)",
        )
    _check(_null_decode(path, chain) == "", f"{_display(path)}: ffmpeg null-decode clean")


def _null_decode(path, chain):
    """Decode every frame of `path` to null and return ffmpeg's stderr."""
    result = run_command(
        [str(chain.require("ffmpeg")), "-v", "error", "-i", str(path), "-f", "null", "-"],
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    if result["returncode"] != 0:
        raise SmokeFailure(f"ffmpeg could not decode {_display(path)}:\n{_tail(result['stderr'])}")
    return result["stderr"].strip()


def _png_dimensions(path):
    """Return (width, height) after checking the PNG signature and IHDR."""
    data = path.read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise SmokeFailure(f"{_display(path)} is not a valid PNG file")
    return struct.unpack(">II", data[16:24])


def report_adapters(scene, project_root, chain):
    """Report optional adapter capability; a missing tool is status, not failure."""
    print("[adapters]")
    plans = {
        "piper": adapters.plan_piper_speech(scene, project_root, chain),
        "rhubarb": adapters.plan_rhubarb_lipsync(scene, project_root, chain),
    }
    for tool, plan in plans.items():
        missing = ", ".join(entry["field"] for entry in plan["missing_assets"])
        suffix = f"; unmet asset: {missing}" if missing else ""
        print(f"  {tool}: status={plan['status']}, applied={plan['applied']}{suffix}")
        print(f"    reason: {plan['reason']}")
    print()


def verify_form(scene, project_root):
    """Serve the real form on an ephemeral port and verify it over HTTP."""
    print("[form]")
    http_server = server.make_server("127.0.0.1", 0, project_root=project_root)
    host, port = http_server.server_address[:2]
    worker = threading.Thread(target=http_server.serve_forever, daemon=True)
    worker.start()
    try:
        _check_form_surface(host, port, scene)
    finally:
        http_server.shutdown()
        worker.join(timeout=FORM_TIMEOUT_SECONDS)
        http_server.server_close()
    print()


def _check_form_surface(host, port, scene):
    """Verify the form HTML, tool status, spec compile, and canonical download."""
    base = f"http://{host}:{port}"
    with urllib.request.urlopen(f"{base}/", timeout=FORM_TIMEOUT_SECONDS) as response:
        html = response.read().decode("utf-8")
        _check(response.status == 200, f"GET / -> {response.status}")
        _check("text/html" in response.headers.get("Content-Type", ""),
               "GET / serves text/html")
        for marker in ('id="scene-form"', "interruption_spokescharacter_v1"):
            _check(marker in html, f"GET / serves the form (found {marker})")
    with urllib.request.urlopen(f"{base}/api/tools", timeout=FORM_TIMEOUT_SECONDS) as response:
        tools = json.load(response)
        _check("ffmpeg" in tools and "blender" in tools,
               f"GET /api/tools -> {response.status}, reports ffmpeg/blender")
        _check(tools["ffmpeg"]["available"], "GET /api/tools: ffmpeg available")
    request = urllib.request.Request(
        f"{base}/api/spec",
        data=json.dumps(scene).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=FORM_TIMEOUT_SECONDS) as response:
        result = json.load(response)
        _check(response.status == 200, f"POST /api/spec -> {response.status}")
        _check(result["scene"] == scene, "POST /api/spec returns the compiled scene")
        _check(result["plan_error"] is None, "POST /api/spec reports no plan_error")
        _check(result["plan"] is not None and result["plan"]["status"] == "ready",
               "POST /api/spec returns a ready ffmpeg plan")
    with urllib.request.urlopen(f"{base}/api/spec/download", timeout=FORM_TIMEOUT_SECONDS) as response:
        body = response.read().decode("utf-8")
        _check("attachment" in response.headers.get("Content-Disposition", ""),
               f"GET /api/spec/download -> {response.status} as an attachment")
        _check(body == serialize_scene(scene),
               "GET /api/spec/download returns the canonical scene JSON")


def _check(condition, message):
    """Print `message` as a passing check, or raise SmokeFailure with it."""
    if not condition:
        raise SmokeFailure(message)
    print(f"  {message}")


def _display(path):
    """Show `path` relative to the repository root when it lives inside it."""
    absolute = Path(path)
    try:
        return str(absolute.relative_to(REPO_ROOT))
    except ValueError:
        return str(absolute)


def _tail(text, lines=4):
    """Return the last `lines` non-empty lines of tool output, indented."""
    trimmed = [line for line in (text or "").strip().splitlines() if line.strip()]
    return "\n".join(f"    {line}" for line in trimmed[-lines:])


def parse_args(argv):
    """Parse the smoke script's command line."""
    parser = argparse.ArgumentParser(
        prog="smoke-render.py",
        description=(
            "End-to-end smoke render: compiles examples/lizard-insurance.json, "
            "synthesizes the media the repository does not ship into a gitignored "
            "build directory, executes the planned FFmpeg and Blender renders, "
            "verifies the artifacts, and checks the browser form over HTTP."
        ),
    )
    parser.add_argument(
        "--build-dir",
        default=str(REPO_ROOT / "build"),
        help=(
            "build directory for the throwaway smoke project "
            "(default: <repo>/build, which is gitignored; a non-default "
            "directory is not gitignored and the smoke-project/ outputs "
            "land there)"
        ),
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
