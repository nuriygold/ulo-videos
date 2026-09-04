"""Authentication and message parsing shared by the external HTTP service."""

import hmac
import json
import re


RENDER_JOB_ID_PATTERN = re.compile(r"^rj_[A-Za-z0-9_-]{1,120}$")


def authenticate_render_request(raw_body, authorization, expected_secret):
    if not isinstance(expected_secret, str) or not expected_secret:
        raise PermissionError("worker authorization is not configured")
    expected = f"Bearer {expected_secret}"
    if not isinstance(authorization, str) or not hmac.compare_digest(authorization, expected):
        raise PermissionError("worker authorization required")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("request body must be JSON") from error
    job_id = payload.get("renderJobId") if isinstance(payload, dict) else None
    if not isinstance(job_id, str) or not RENDER_JOB_ID_PATTERN.fullmatch(job_id):
        raise ValueError("renderJobId is required")
    return job_id
