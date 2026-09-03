"""Local renderer command planning and shell-free command execution.

Planners are pure: they validate scene assets, resolve them against a project
root, and return JSON-safe command plans (plain dicts, lists, strings, and
numbers). Plans never execute anything; `run_command` executes a planned argv
without shell interpolation. Missing tools raise `MissingToolError`; missing
asset files surface as the named plan status `missing_assets`.
"""

import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath

from .schema import validate_pause

DEFAULT_TOOLS = ("ffmpeg", "blender")
PREVIEW_OUTPUT_NAME = "build/preview.mp4"
DEFAULT_FREEZE_SECONDS = 2.0
CAPTION_NOT_RENDERED_REASON = (
    "drawtext filter unavailable in the installed ffmpeg; dialogue.text is kept "
    "in the plan so captions can be burned in by a capable build or adapter"
)
CAPTION_STYLE_NONE_REASON = (
    "branding.caption_style is 'none'; no burned-in caption was requested"
)
BLENDER_CAPTION_REASON = (
    "blender renders the character plate; captions are burned in at the ffmpeg "
    "assembly stage"
)
CAPTION_POSITIONS = {
    "lower_third": ("x=(w-text_w)/2", "y=h-th-60"),
    "top": ("x=(w-text_w)/2", "y=60"),
    "center": ("x=(w-text_w)/2", "y=(h-text_h)/2"),
}
DEFAULT_CAPTION_STYLE = "lower_third"
_ASSET_KEYS = {
    "background_video": ("background_video",),
    "character.asset": ("character", "asset"),
    "branding.logo": ("branding", "logo"),
}


class RendererError(Exception):
    """Base class for renderer planning and execution errors."""


class MissingToolError(RendererError):
    """Raised when a required local executable is not available."""


class AssetPathError(RendererError):
    """Raised when an asset path is not a safe relative path inside the project."""


class CommandTimeoutError(RendererError):
    """Raised when a planned command exceeds its time budget."""


class Toolchain:
    """Resolves local executables by name; missing tools are status, not failures."""

    def __init__(self, lookup=None, tools=DEFAULT_TOOLS, filter_probe=None):
        self._lookup = lookup if lookup is not None else shutil.which
        self._tools = tuple(tools)
        self._filter_probe = filter_probe
        self._filter_support = {}

    def resolve(self, tool):
        """Return the executable path for `tool`, or None when unavailable."""
        return self._lookup(str(tool))

    def require(self, tool):
        """Return the executable path for `tool` or raise a named error."""
        path = self.resolve(tool)
        if not path:
            raise MissingToolError(
                f"{tool} executable not found. Install {tool} and make sure it is on PATH."
            )
        return path

    def status(self):
        """Return a JSON-safe availability report for the known tools."""
        report = {}
        for tool in self._tools:
            path = self.resolve(tool)
            report[tool] = {"available": bool(path), "path": path}
        return report

    def supports_filter(self, tool, filter_name):
        """Return True when the resolved executable exposes `filter_name`.

        Probing runs the executable only when this capability is queried and
        is cached per Toolchain instance. Tests inject `filter_probe`.
        """
        cache_key = (str(tool), str(filter_name))
        if cache_key not in self._filter_support:
            self._filter_support[cache_key] = self._probe_filter(tool, filter_name)
        return self._filter_support[cache_key]

    def _probe_filter(self, tool, filter_name):
        if self._filter_probe is not None:
            return bool(self._filter_probe(tool, filter_name))
        executable = self.resolve(tool)
        if not executable:
            return False
        return _ffmpeg_filter_support(executable, filter_name)


def _ffmpeg_filter_support(executable, filter_name):
    """Probe filter support by asking the executable for its filter list."""
    try:
        result = run_command([str(executable), "-hide_banner", "-filters"], timeout=15)
    except (MissingToolError, CommandTimeoutError, OSError):
        return False
    if result["returncode"] != 0:
        return False
    pattern = rf"(?m)^\s*\S+\s+{re.escape(filter_name)}\s"
    return re.search(pattern, result["stdout"]) is not None


def resolve_relative_path(project_root, value, field):
    """Resolve `value` relative to `project_root`, rejecting unsafe paths.

    Absolute paths, `..` traversal, and symlinks that resolve outside the
    project root are rejected. The file does not need to exist; existence is a
    planner-reported status, not a path-safety concern.
    """
    if isinstance(value, bool) or not isinstance(value, str) or not value.strip():
        raise AssetPathError(f"{field} must be a non-empty relative path, got {value!r}")
    for pure in (PurePosixPath(value), PureWindowsPath(value)):
        if pure.is_absolute():
            raise AssetPathError(f"{field} must be a relative path, got {value!r}")
        if ".." in pure.parts:
            raise AssetPathError(f"{field} must not escape the project root: {value!r}")
    root = Path(project_root).resolve()
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root):
        raise AssetPathError(f"{field} must stay inside the project root: {value!r}")
    return str(resolved)


def run_command(argv, *, timeout=None, cwd=None):
    """Run `argv` directly (never through a shell) and capture a JSON-safe result."""
    if isinstance(argv, (str, bytes)) or not isinstance(argv, (list, tuple)):
        raise RendererError("command must be a list or tuple of argument strings; shell strings are not allowed")
    if not argv:
        raise RendererError("command must contain at least the executable")
    if any(isinstance(arg, bool) or not isinstance(arg, str) for arg in argv):
        raise RendererError("command arguments must all be strings")
    try:
        completed = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            cwd=cwd,
            shell=False,
        )
    except FileNotFoundError:
        raise MissingToolError(
            f"{argv[0]} executable not found. Install it and make sure it is on PATH."
        ) from None
    except subprocess.TimeoutExpired:
        raise CommandTimeoutError(
            f"{Path(str(argv[0])).name} timed out after {timeout} seconds"
        ) from None
    return {
        "argv": list(argv),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def prepare_output(plan):
    """Create the output directory a plan writes into; callers then run its argv.

    Planners stay read-only, so directory creation is an explicit step between
    planning and execution.
    """
    path = (plan.get("output") or {}).get("path") if isinstance(plan, dict) else None
    if not path:
        return None
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def plan_ffmpeg_render(
    scene,
    project_root,
    toolchain=None,
    *,
    output_name=PREVIEW_OUTPUT_NAME,
    freeze_seconds=DEFAULT_FREEZE_SECONDS,
):
    """Plan the deterministic baseline FFmpeg command for a compiled scene.

    Baseline: play the background video to `pause_at`, freeze on the last
    frame for `freeze_seconds`, scale to the output resolution and fps, and
    export silently (`-an`) in the requested format. Burned-in captions are
    planned when the installed ffmpeg exposes the drawtext filter; otherwise
    the plan keeps dialogue.text as metadata with the capability reason.
    """
    _require_scene(scene)
    if isinstance(freeze_seconds, bool) or not isinstance(freeze_seconds, (int, float)) or freeze_seconds < 0:
        raise RendererError("freeze_seconds must be a non-negative number")
    chain = _toolchain(toolchain)
    executable = chain.require("ffmpeg")
    assets = _resolve_assets(scene, project_root, tuple(_ASSET_KEYS))
    output_path = resolve_relative_path(project_root, output_name, "output_name")

    output = _scene_value(scene, "output")
    pause_at = validate_pause(_scene_value(scene, "pause_at"))
    width, height = _scene_value(output, "resolution")
    fps = _scene_value(output, "fps")
    fmt = _scene_value(output, "format")
    caption_style = _scene_value(_scene_value(scene, "branding"), "caption_style")
    caption_text = _scene_value(_scene_value(scene, "dialogue"), "text")
    if caption_style == "none":
        captions_applied = False
        captions_reason = CAPTION_STYLE_NONE_REASON
    elif chain.supports_filter("ffmpeg", "drawtext"):
        captions_applied = True
        captions_reason = None
    else:
        captions_applied = False
        captions_reason = CAPTION_NOT_RENDERED_REASON
    filter_parts = [
        f"trim=end={_number(pause_at)}",
        f"tpad=stop_mode=clone:stop_duration={_number(freeze_seconds)}",
        f"scale={width}:{height}",
        f"fps={fps}",
    ]
    if captions_applied:
        filter_parts.append(_caption_filter(caption_style, caption_text))
    filters = ",".join(filter_parts)
    argv = [
        executable,
        "-y",
        "-i",
        assets["background_video"],
        "-vf",
        filters,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-an",
        "-f",
        str(fmt),
        output_path,
    ]
    return _finish_plan(
        "ffmpeg",
        executable,
        assets,
        argv,
        {"path": output_path, "format": str(fmt), "resolution": [width, height], "fps": fps},
        scene,
        captions_applied,
        captions_reason,
    )


def plan_blender_render(scene, project_root, toolchain=None):
    """Plan a headless Blender render of the character asset (frame 1, PNG)."""
    _require_scene(scene)
    executable = _toolchain(toolchain).require("blender")
    assets = _resolve_assets(scene, project_root, ("character.asset",))
    prefix = str(Path(project_root).resolve() / "build" / "blender-frame")
    argv = [
        executable,
        "-b",
        assets["character.asset"],
        "--factory-startup",
        "-o",
        prefix,
        "-F",
        "PNG",
        "-f",
        "1",
    ]
    return _finish_plan(
        "blender",
        executable,
        assets,
        argv,
        {"path": prefix + "0001.png", "format": "png", "frame": 1},
        scene,
        False,
        BLENDER_CAPTION_REASON,
    )


def _require_scene(scene):
    if not isinstance(scene, dict):
        raise RendererError("scene must be an object compiled by templates.compile_scene")


def _toolchain(toolchain):
    return toolchain if toolchain is not None else Toolchain()


def _scene_value(mapping, key):
    try:
        return mapping[key]
    except (KeyError, TypeError):
        raise RendererError(f"scene is missing required key: {key}") from None


def _resolve_assets(scene, project_root, fields):
    assets = {}
    for field in fields:
        value = scene
        for key in _ASSET_KEYS[field]:
            value = _scene_value(value, key)
        assets[field] = resolve_relative_path(project_root, value, field)
    return assets


def _missing_assets(assets):
    return [
        {"field": field, "path": path}
        for field, path in assets.items()
        if not Path(path).is_file()
    ]


def _number(value):
    """Format a filter timestamp with bounded, deterministic precision."""
    return f"{float(value):.6f}".rstrip("0").rstrip(".") or "0"


def _finish_plan(tool, executable, assets, argv, output, scene, captions_applied, captions_reason):
    missing = _missing_assets(assets)
    dialogue = _scene_value(scene, "dialogue")
    branding = _scene_value(scene, "branding")
    return {
        "status": "missing_assets" if missing else "ready",
        "tool": tool,
        "executable": executable,
        "argv": [str(arg) for arg in argv],
        "assets": dict(assets),
        "missing_assets": missing,
        "output": output,
        "captions": {
            "text": _scene_value(dialogue, "text"),
            "style": _scene_value(branding, "caption_style"),
            "applied": captions_applied,
            "reason": captions_reason,
        },
    }


def _escape_drawtext_text(text):
    """Escape caption text for a drawtext option inside a filtergraph.

    Two escaping levels apply (ffmpeg-utils "Notes on filtergraph escaping"):
    the option level escapes ':', quotes, and backslashes; the filtergraph
    level escapes the remaining ',', ';', and bracket separators. Newlines
    are flattened because the option value is a single argv element, and
    `expansion=none` keeps '%' literal.
    """
    flat = text.replace("\r", " ").replace("\n", " ")
    option_level = flat.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
    return option_level.replace("\\", "\\\\").replace("'", "\\'").replace(",", "\\,").replace(";", "\\;").replace("[", "\\[").replace("]", "\\]")


def _caption_filter(caption_style, dialogue_text):
    position_x, position_y = CAPTION_POSITIONS.get(caption_style, CAPTION_POSITIONS[DEFAULT_CAPTION_STYLE])
    text = _escape_drawtext_text(dialogue_text)
    return f"drawtext=text={text}:expansion=none:{position_x}:{position_y}"
