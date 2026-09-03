"""Template compilers for scene specifications."""

import json

from .schema import (
    SceneValidationError,
    normalize_resolution,
    require_fields,
    required_mapping,
    required_text,
    validate_pause,
)


TEMPLATE_NAME = "interruption_spokescharacter_v1"
_NESTED_FIELDS = {
    "character": ("asset", "position", "entrance", "gesture"),
    "dialogue": ("text", "voice", "lip_sync"),
    "branding": ("logo", "caption_style"),
}


def compile_scene(payload) -> dict:
    """Validate and normalize a scene payload for the supported template."""
    if not isinstance(payload, dict):
        raise SceneValidationError("scene payload must be an object")

    required = ("template", "background_video", "pause_at", "character", "dialogue", "branding", "output")
    require_fields(payload, "scene", required)
    if payload["template"] != TEMPLATE_NAME:
        raise SceneValidationError(f"template must be {TEMPLATE_NAME!r}")

    background_video = required_text(payload["background_video"], "background_video")
    pause_at = validate_pause(payload["pause_at"])
    compiled = {
        "template": TEMPLATE_NAME,
        "background_video": background_video,
        "pause_at": pause_at,
    }

    for field, children in _NESTED_FIELDS.items():
        source = required_mapping(payload[field], field)
        require_fields(source, field, children)
        compiled[field] = dict(source)
        for child in children:
            required_text(source[child], f"{field}.{child}")

    output = required_mapping(payload["output"], "output")
    require_fields(output, "output", ("resolution",))
    compiled["output"] = dict(output)
    compiled["output"]["resolution"] = normalize_resolution(output["resolution"])
    compiled["output"].setdefault("fps", 30)
    compiled["output"].setdefault("format", "mp4")
    if isinstance(compiled["output"]["fps"], bool) or not isinstance(compiled["output"]["fps"], int) or compiled["output"]["fps"] <= 0:
        raise SceneValidationError("output.fps must be a positive integer")
    required_text(compiled["output"]["format"], "output.format")
    return compiled


def serialize_scene(scene: dict) -> str:
    """Serialize a compiled scene deterministically as indented JSON."""
    if not isinstance(scene, dict):
        raise SceneValidationError("scene must be an object")
    return json.dumps(scene, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
