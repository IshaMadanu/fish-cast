"""Turn an HTTP error body into the message the API actually sent."""

from __future__ import annotations

import json


def detail_from_body(raw: bytes) -> str | None:
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail
    return None


def http_error_message(exc: BaseException) -> str:
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            raw = response.content
        except Exception:
            raw = b""
        detail = detail_from_body(raw) if raw else None
        if detail:
            return detail
        try:
            parsed = response.json()
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            detail = parsed.get("detail")
            if isinstance(detail, str) and detail.strip():
                return detail
    return str(exc)
