"""Deterministic Blender plate rendering and FFmpeg assembly for Scene v1."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union
from urllib.parse import urlparse


HOLD_SECONDS = 2
FONT_FILE = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


@dataclass(frozen=True)
class CompositePlan:
    source_url: str
    character_url: str
    character_format: str
    logo_url: str
    source: Path
    character: Path
    imported_blend: Optional[Path]
    logo_source: Path
    logo_image: Path
    rasterize_logo: bool
    character_frames: Path
    blender_argv: list[str]
    ffmpeg_argv: list[str]
    output: str


def _url_filename(url: str, fallback: str) -> str:
    name = Path(urlparse(url).path).name
    return name if name and name not in {".", ".."} else fallback


def _character_format(url: str) -> str:
    extension = Path(urlparse(url).path).suffix.lower()
    if extension not in {".blend", ".gltf", ".glb", ".fbx"}:
        raise ValueError("character.asset must use a .blend, .gltf, .glb, or .fbx URL")
    return extension


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _character(scene: dict) -> dict:
    elements = scene.get("elements")
    if not isinstance(elements, list):
        raise ValueError("scene.elements must be a list")
    character = next((item for item in elements if isinstance(item, dict) and item.get("type") == "character"), None)
    if character is None:
        raise ValueError("scene requires a character element")
    return character


def _ffmpeg_text(value: str) -> str:
    """Quote the text fragment used inside a filtergraph, not a shell command."""
    return value.replace("\\", r"\\").replace("'", r"\'").replace(":", r"\:").replace("%", r"\%").replace("\n", r"\n")


def _number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def _character_position(position: str) -> tuple[str, str]:
    positions = {
        "foreground_left": ("0", "0"),
        "foreground_center": ("0", "0"),
        "foreground_right": ("0", "0"),
    }
    try:
        return positions[position]
    except KeyError as error:
        raise ValueError("character.position is unsupported") from error


def build_composite_plan(scene: dict, workdir: Union[str, Path]) -> CompositePlan:
    """Build the commands for a source + character + logo + caption render.

    The Blender job renders a transparent PNG plate from the selected `.blend`
    and FFmpeg overlays that plate only during the deterministic freeze window.
    """
    if not isinstance(scene, dict):
        raise ValueError("scene must be an object")
    root = Path(workdir).resolve()
    source_url = _text((scene.get("source") or {}).get("video"), "source.video")
    character = _character(scene)
    character_url = _text(character.get("asset"), "character.asset")
    logo_url = _text((scene.get("branding") or {}).get("logo"), "branding.logo")
    trigger = (scene.get("trigger") or {}).get("value")
    output = scene.get("output") or {}
    if isinstance(trigger, bool) or not isinstance(trigger, (int, float)) or trigger < 0:
        raise ValueError("trigger.value must be a non-negative number")
    width, height, fps = output.get("width"), output.get("height"), output.get("fps")
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (width, height, fps)):
        raise ValueError("output width, height, and fps must be positive integers")
    position = _text(character.get("position"), "character.position")
    x, y = _character_position(position)
    entrance = _text((character.get("entrance") or {}).get("type"), "character.entrance.type")
    gesture = _text((character.get("performance") or {}).get("gesture"), "character.performance.gesture")
    dialogue = character.get("dialogue") or {}
    caption_text = _text(dialogue.get("text"), "character.dialogue.text")
    captions = scene.get("captions") or {}
    caption_style = captions.get("style") if captions.get("enabled") else "none"
    if caption_style not in {"none", "lower_third", "top", "center"}:
        raise ValueError("captions.style is unsupported")

    source = root / "input" / _url_filename(source_url, "source.mp4")
    character_format = _character_format(character_url)
    character_file = root / "input" / _url_filename(character_url, f"character{character_format}")
    imported_blend = None if character_format == ".blend" else root / "input" / "imported-character.blend"
    logo_source = root / "input" / _url_filename(logo_url, "logo.svg")
    rasterize_logo = logo_source.suffix.lower() == ".svg"
    logo_image = root / "input" / "logo.png" if rasterize_logo else logo_source
    character_frames = root / "character" / "character_%05d.png"
    output_path = root / "output.mp4"
    hold_frames = HOLD_SECONDS * fps
    blender_script = Path(__file__).with_name("blender_character.py").resolve()
    blender_argv = ["blender", "-b"]
    if character_format == ".blend":
        blender_argv.append(str(character_file))
    blender_argv.extend(["-P", str(blender_script), "--"])
    if imported_blend is not None:
        blender_argv.extend([
            "--character", str(character_file), "--character-format", character_format,
            "--imported-blend", str(imported_blend),
        ])
    blender_argv.extend([
        "--output-dir", str(character_frames.parent), "--width", str(width), "--height", str(height),
        "--fps", str(fps), "--frames", str(hold_frames), "--position", position,
        "--entrance", entrance, "--gesture", gesture,
    ])
    before = f"[before_source]trim=end={trigger},setpts=PTS-STARTPTS[before]"
    after = f"[after_source]trim=start={trigger},setpts=PTS-STARTPTS[after]"
    hold = (
        f"[freeze_source]trim=start={_number(float(trigger))}:end={_number(float(trigger) + (1 / fps))},"
        f"setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={HOLD_SECONDS}[hold]"
    )
    caption_filter = ""
    if caption_style != "none":
        caption_y = {"lower_third": "h-th-60", "top": "60", "center": "(h-th)/2"}[caption_style]
        caption_filter = f",drawtext=text='{_ffmpeg_text(caption_text)}':fontfile='{FONT_FILE}':x=(w-text_w)/2:y={caption_y}:fontcolor=white:fontsize=48:box=1:boxcolor=black@0.65:boxborderw=22:enable='between(t,{trigger},{trigger + HOLD_SECONDS})'"
    filters = ";".join([
        "[0:v]split=3[before_source][freeze_source][after_source]",
        before,
        hold,
        after,
        f"[before][hold][after]concat=n=3:v=1:a=0[assembled]",
        f"[assembled]scale={width}:{height},fps={fps}[scene]",
        f"[2:v]setpts=PTS+{trigger}/TB[character]",
        f"[scene][character]overlay=x={x}:y={y}:format=auto:eof_action=pass:repeatlast=0[with_character]",
        "[1:v]scale=240:-1[logo]",
        f"[with_character][logo]overlay=W-w-48:H-h-48:shortest=1{caption_filter}[out]",
    ])
    ffmpeg_argv = [
        "ffmpeg", "-y", "-i", str(source), "-loop", "1", "-i", str(logo_image),
        "-framerate", str(fps), "-start_number", "1", "-i", str(character_frames),
        "-filter_complex", filters, "-map", "[out]", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(output_path),
    ]
    return CompositePlan(source_url, character_url, character_format, logo_url, source, character_file, imported_blend, logo_source, logo_image, rasterize_logo, character_frames, blender_argv, ffmpeg_argv, str(output_path))
