"""Runtime configuration. Secrets come from the environment, never from the repo."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PIN_PATH = PACKAGE_DIR / "collection_pin.json"

DEFAULT_MODEL = "grok-4.7"
DEFAULT_COLLECTION_VERSION = "fishcast-policy-2026-11-03"
DEFAULT_SDK = "xai-sdk==1.21.0"


def load_pin() -> dict:
    if not PIN_PATH.is_file():
        return {
            "collection_version": DEFAULT_COLLECTION_VERSION,
            "sdk": DEFAULT_SDK,
            "default_model": DEFAULT_MODEL,
        }
    return json.loads(PIN_PATH.read_text(encoding="utf-8"))


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def load_local_dotenv() -> None:
    """Load viz/chatbot/.env when python-dotenv is installed. Existing variables win."""
    env_path = PACKAGE_DIR / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(env_path, override=False)


@dataclass
class Settings:
    xai_api_key: str = ""
    xai_management_api_key: str = ""
    model: str = DEFAULT_MODEL
    reasoning_effort: str = "high"
    collection_id: str = ""
    collection_version: str = DEFAULT_COLLECTION_VERSION
    search_limit: int = 8
    enable_web_search: bool = False
    basic_auth_user: str = ""
    basic_auth_password: str = ""
    rate_limit_per_minute: int = 30
    audit_log_path: str = "viz/chatbot/audit/audit.jsonl"
    request_timeout_s: float = 180.0
    sdk_pin: str = DEFAULT_SDK

    @classmethod
    def from_env(cls) -> Settings:
        load_local_dotenv()
        pin = load_pin()
        version = os.environ.get("FISHCAST_COLLECTION_VERSION", "").strip() or pin.get(
            "collection_version", DEFAULT_COLLECTION_VERSION
        )
        model = os.environ.get("XAI_MODEL", "").strip() or pin.get("default_model", DEFAULT_MODEL)
        return cls(
            xai_api_key=os.environ.get("XAI_API_KEY", "").strip(),
            xai_management_api_key=os.environ.get("XAI_MANAGEMENT_API_KEY", "").strip(),
            model=model,
            reasoning_effort=os.environ.get("XAI_REASONING_EFFORT", "high").strip(),
            collection_id=os.environ.get("XAI_COLLECTION_ID", "").strip(),
            collection_version=version,
            search_limit=env_int("CHATBOT_SEARCH_LIMIT", 8),
            enable_web_search=env_bool("CHATBOT_ENABLE_WEB_SEARCH", False),
            basic_auth_user=os.environ.get("CHATBOT_BASIC_AUTH_USER", "").strip(),
            basic_auth_password=os.environ.get("CHATBOT_BASIC_AUTH_PASSWORD", ""),
            rate_limit_per_minute=env_int("CHATBOT_RATE_LIMIT_PER_MINUTE", 30),
            audit_log_path=os.environ.get("CHATBOT_AUDIT_LOG", "viz/chatbot/audit/audit.jsonl"),
            request_timeout_s=float(os.environ.get("XAI_TIMEOUT_SECONDS", "180") or "180"),
            sdk_pin=pin.get("sdk", DEFAULT_SDK),
        )

    @property
    def secrets(self) -> list[str]:
        return [value for value in (self.xai_api_key, self.xai_management_api_key, self.basic_auth_password) if value]

    @property
    def auth_enabled(self) -> bool:
        return bool(self.basic_auth_password)
