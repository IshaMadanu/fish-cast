"""Turn a /chat filters object into an AIP-160 metadata expression.

xai-sdk 1.21.0's collections_search helper accepts collection_ids, limit,
instructions, and retrieval_mode. It has no filter argument. The expression
built here is passed in instructions, and also as filter= if a future SDK
exposes that parameter. Document fields are strings, so every value is quoted.
"""

from __future__ import annotations

ALLOWED_DOC_TYPES = ("model_output", "project_doc", "policy", "literature", "limitations")
ALLOWED_SKILL_STATUS = ("no_skill", "partial", "not_applicable", "unknown")
FILTER_KEYS = ("doc_type", "year", "region", "skill_status", "preprocessing_version")


class FilterError(ValueError):
    """The caller sent a filter this service does not know how to apply."""


def _quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _as_list(value: object, key: str) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        items = [str(value)]
    elif isinstance(value, (list, tuple)):
        items = [str(item) for item in value]
    else:
        raise FilterError(f"{key} must be a string or a list of strings.")
    cleaned = [item.strip() for item in items if str(item).strip()]
    if not cleaned:
        raise FilterError(f"{key} must not be empty.")
    return cleaned


def _eq_clause(key: str, values: list[str]) -> str:
    parts = [f"{key}={_quote(value)}" for value in values]
    if len(parts) == 1:
        return parts[0]
    return "(" + " OR ".join(parts) + ")"


def normalize_filters(filters: dict | None) -> dict[str, list[str]]:
    """Return a dict of field name to allowed values. Empty input returns {}."""
    if not filters:
        return {}
    unknown = sorted(set(filters) - set(FILTER_KEYS))
    if unknown:
        raise FilterError(f"Unknown filter field: {', '.join(unknown)}.")
    normalized: dict[str, list[str]] = {}
    doc_types = _as_list(filters.get("doc_type"), "doc_type")
    if doc_types is not None:
        bad = [item for item in doc_types if item not in ALLOWED_DOC_TYPES]
        if bad:
            raise FilterError(
                "doc_type must be one of: " + ", ".join(ALLOWED_DOC_TYPES) + f". Got {', '.join(bad)}."
            )
        normalized["doc_type"] = doc_types
    skill = _as_list(filters.get("skill_status"), "skill_status")
    if skill is not None:
        bad = [item for item in skill if item not in ALLOWED_SKILL_STATUS]
        if bad:
            raise FilterError(
                "skill_status must be one of: " + ", ".join(ALLOWED_SKILL_STATUS) + f". Got {', '.join(bad)}."
            )
        normalized["skill_status"] = skill
    for key in ("year", "region", "preprocessing_version"):
        values = _as_list(filters.get(key), key)
        if values is not None:
            if len(values) != 1:
                raise FilterError(f"{key} accepts a single value.")
            normalized[key] = values
    return normalized


def filter_expression(filters: dict | None) -> str | None:
    """AIP-160 expression, or None when the caller did not filter."""
    normalized = normalize_filters(filters)
    if not normalized:
        return None
    clauses = [_eq_clause(key, normalized[key]) for key in FILTER_KEYS if key in normalized]
    return " AND ".join(clauses)
