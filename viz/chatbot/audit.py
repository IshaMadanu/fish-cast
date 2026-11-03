"""Append-only JSONL audit log of queries, retrieved passages, and answers."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def redact(value: Any, secrets: list[str]) -> Any:
    """Replace secret values anywhere in a JSON-like structure."""
    live = [secret for secret in secrets if secret]
    if isinstance(value, str):
        for secret in live:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [redact(item, live) for item in value]
    if isinstance(value, dict):
        return {str(key): redact(item, live) for key, item in value.items()}
    return value


class AuditLog:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def write(self, record: dict, secrets: list[str] | None = None) -> None:
        safe = redact(record, secrets or [])
        safe.setdefault("ts", datetime.now(timezone.utc).isoformat())
        line = json.dumps(safe, ensure_ascii=False, default=str)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
