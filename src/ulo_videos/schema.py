"""Validation helpers for ulo-videos scene specifications."""


class SceneValidationError(ValueError):
    """Raised when a scene does not satisfy the scene contract."""


def required_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise SceneValidationError(f"{field} must be a non-empty string")
    return value


def required_mapping(value, field):
    if not isinstance(value, dict):
        raise SceneValidationError(f"{field} must be an object")
    return value


def require_fields(mapping, field, fields):
    for child in fields:
        if child not in mapping:
            raise SceneValidationError(f"missing required field: {field}.{child}")


def validate_pause(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SceneValidationError("pause_at must be numeric")
    if value < 0:
        raise SceneValidationError("pause_at must be non-negative")
    return value


def normalize_resolution(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise SceneValidationError("output.resolution must contain exactly two integers")
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in value):
        raise SceneValidationError("output.resolution must contain positive integers")
    return list(value)
