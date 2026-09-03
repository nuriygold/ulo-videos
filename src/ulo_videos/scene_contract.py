"""Normalized, versioned scene contract for cloud render jobs."""

import math

from .schema import SceneValidationError


class SceneContractError(SceneValidationError):
    """Raised when a normalized scene cannot be rendered deterministically."""


POSITIONS = {"foreground_left", "foreground_center", "foreground_right"}
ENTRANCES = {"pop_in", "fade_in", "slide_left", "slide_right"}
GESTURES = {"shrug_and_point", "wave", "nod", "talk_idle"}
CAPTION_STYLES = {"none", "lower_third", "top", "center"}


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise SceneContractError(f"{field} must be a non-empty string")
    return value


def _number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise SceneContractError(f"{field} must be a finite non-negative number")
    return value


def _choice(value, field, choices):
    _text(value, field)
    if value not in choices:
        raise SceneContractError(f"{field} must be one of {', '.join(sorted(choices))}")
    return value


def normalize_scene(payload):
    """Convert the existing flat scene payload to the versioned generic shape."""
    if not isinstance(payload, dict):
        raise SceneContractError("scene payload must be an object")
    if payload.get("version") == 1 and "source" in payload:
        return validate_scene(payload)
    required = ("template", "background_video", "pause_at", "character", "dialogue", "branding", "output")
    missing = next((field for field in required if field not in payload), None)
    if missing:
        raise SceneContractError(f"missing required field: scene.{missing}")
    character = payload["character"]
    dialogue = payload["dialogue"]
    branding = payload["branding"]
    output = payload["output"]
    scene = {
        "template": _text(payload["template"], "template"),
        "version": 1,
        "source": {"video": _text(payload["background_video"], "source.video")},
        "trigger": {"type": "timestamp", "value": _number(payload["pause_at"], "trigger.value")},
        "background": {"action": "freeze"},
        "elements": [{
            "id": "spokesperson",
            "type": "character",
            "asset": _text(character["asset"], "elements[0].asset"),
            "position": _choice(character["position"], "elements[0].position", POSITIONS),
            "entrance": {"type": _choice(character["entrance"], "elements[0].entrance.type", ENTRANCES)},
            "performance": {"gesture": _choice(character["gesture"], "elements[0].performance.gesture", GESTURES)},
            "dialogue": {
                "text": _text(dialogue["text"], "elements[0].dialogue.text"),
                "voice": _text(dialogue["voice"], "elements[0].dialogue.voice"),
                "lip_sync": _text(dialogue["lip_sync"], "elements[0].dialogue.lip_sync"),
            },
        }],
        "captions": {"enabled": branding.get("caption_style") != "none", "style": _choice(branding["caption_style"], "captions.style", CAPTION_STYLES)},
        "branding": {"logo": _text(branding["logo"], "branding.logo")},
        "continuation": {"action": "resume"},
        "output": {
            "format": _text(output.get("format", "mp4"), "output.format"),
            "width": output["resolution"][0],
            "height": output["resolution"][1],
            "fps": output.get("fps", 30),
        },
    }
    return validate_scene(scene)


def validate_scene(scene):
    """Validate the normalized scene and return it unchanged."""
    if not isinstance(scene, dict) or scene.get("version") != 1:
        raise SceneContractError("scene.version must be 1")
    trigger = scene.get("trigger") or {}
    if trigger.get("type") != "timestamp":
        raise SceneContractError("trigger.type must be timestamp")
    _number(trigger.get("value"), "trigger.value")
    elements = scene.get("elements")
    if not isinstance(elements, list):
        raise SceneContractError("elements must be a list")
    for index, element in enumerate(elements):
        prefix = f"elements[{index}]"
        if element.get("type") != "character":
            raise SceneContractError(f"{prefix}.type must be character")
        _text(element.get("asset"), f"{prefix}.asset")
        _choice(element.get("position"), f"{prefix}.position", POSITIONS)
        _choice((element.get("entrance") or {}).get("type"), f"{prefix}.entrance.type", ENTRANCES)
        _choice((element.get("performance") or {}).get("gesture"), f"{prefix}.performance.gesture", GESTURES)
    output = scene.get("output") or {}
    for key in ("width", "height", "fps"):
        value = output.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise SceneContractError(f"output.{key} must be a positive integer")
    _choice((scene.get("captions") or {}).get("style"), "captions.style", CAPTION_STYLES)
    return scene
