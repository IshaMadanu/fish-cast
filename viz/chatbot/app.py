"""FastAPI service for the Marine Populations Policy Chatbot.

Phase 1: POST /chat, streaming by default.
Phase 2: POST /brief and GET /sources, with citations on both.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Iterator
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict, Field, field_validator

from viz.chatbot.audit import AuditLog
from viz.chatbot.filters import FilterError, filter_expression, normalize_filters
from viz.chatbot.grok import ChatbotError, CollectionNotConfigured, GrokBackend, MissingApiKey
from viz.chatbot.prompt import DISCLAIMER, HUMAN_REVIEW_NOTE
from viz.chatbot.sessions import SessionStore
from viz.chatbot.settings import Settings

security = HTTPBasic(auto_error=False)


def _secret_equal(supplied: str, expected: str) -> bool:
    if len(supplied) != len(expected):
        return False
    return secrets.compare_digest(supplied, expected)

MAX_MESSAGE_CHARS = 8000


class RateLimiter:
    """Fixed window of 60 seconds, counted in memory for a single process."""

    def __init__(self, per_minute: int) -> None:
        import threading
        import time

        self.per_minute = per_minute
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._time = time.monotonic

    def check(self, key: str) -> None:
        if self.per_minute <= 0:
            return
        now = self._time()
        with self._lock:
            recent = [stamp for stamp in self._hits.get(key, []) if now - stamp < 60]
            if len(recent) >= self.per_minute:
                raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again in a minute.")
            recent.append(now)
            self._hits[key] = recent


class ChatFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doc_type: list[str] | str | None = None
    year: str | int | None = None
    region: str | None = None
    skill_status: list[str] | str | None = None
    preprocessing_version: str | int | None = None

    @field_validator("year", "preprocessing_version", mode="before")
    @classmethod
    def _stringify(cls, value: Any) -> Any:
        if value is None:
            return None
        return str(value)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    conversation_id: str | None = Field(default=None, max_length=80)
    filters: ChatFilters | None = None
    stream: bool = True


class BriefRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    conversation_id: str | None = Field(default=None, max_length=80)
    filters: ChatFilters | None = None


def _client_key(request: Request) -> str:
    import hashlib

    authorization = request.headers.get("authorization")
    if authorization:
        return hashlib.sha256(authorization.encode("utf-8")).hexdigest()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def enforce_auth(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(security),
) -> None:
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        return
    expected_user = settings.basic_auth_user or "fishcast"
    supplied_user = "" if credentials is None else credentials.username
    supplied_password = "" if credentials is None else credentials.password
    user_ok = _secret_equal(supplied_user, expected_user)
    password_ok = _secret_equal(supplied_password, settings.basic_auth_password)
    if credentials is None or not (user_ok and password_ok):
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Basic"},
        )


def enforce_rate_limit(request: Request) -> None:
    request.app.state.limiter.check(_client_key(request))


def _filters_dict(filters: ChatFilters | None) -> dict | None:
    if filters is None:
        return None
    raw = filters.model_dump(exclude_none=True)
    return raw or None


def _checked_filters(filters: ChatFilters | None) -> tuple[dict | None, str | None]:
    raw = _filters_dict(filters)
    try:
        normalize_filters(raw)
        expression = filter_expression(raw)
    except FilterError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return raw, expression


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _redact_text(text: str, settings: Settings) -> str:
    for secret in settings.secrets:
        text = text.replace(secret, "[redacted]")
    return text


def create_app(settings: Settings | None = None, backend: Any = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Marine Populations Policy Chatbot", version=settings.collection_version)
    app.state.settings = settings
    app.state.backend = backend or GrokBackend(settings)
    app.state.sessions = SessionStore()
    app.state.audit = AuditLog(settings.audit_log_path)
    app.state.limiter = RateLimiter(settings.rate_limit_per_minute)

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "disclaimer": DISCLAIMER,
            "collection_version": settings.collection_version,
            "model": settings.model,
        }

    def reject_if_unconfigured(endpoint: str, session, message: str, raw_filters: dict | None, expression: str | None) -> None:
        """Real Grok calls need a key and a pinned collection. Fakes have no settings."""
        configured = getattr(app.state.backend, "settings", None)
        if configured is None:
            return
        if not configured.xai_api_key:
            detail = MissingApiKey.detail
        elif not configured.collection_id:
            detail = CollectionNotConfigured.detail
        else:
            return
        app.state.audit.write(
            {
                "endpoint": endpoint,
                "conversation_id": session.conversation_id,
                "message": message,
                "filters": raw_filters,
                "filter_expression": expression,
                "collection_id": settings.collection_id,
                "collection_version": settings.collection_version,
                "model": settings.model,
                "passages": [],
                "citations": [],
                "answer": "",
                "error": detail,
                "disclaimer": DISCLAIMER,
                "human_review_required": True,
            },
            settings.secrets,
        )
        raise HTTPException(status_code=503, detail=detail)

    def run_turn(session, message: str, raw_filters: dict | None, mode: str) -> Iterator[dict]:
        history = list(session.messages)
        try:
            yield from app.state.backend.stream(history=history, message=message, filters=raw_filters, mode=mode)
        except ChatbotError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    def finish(session, endpoint: str, message: str, raw_filters: dict | None, expression: str | None, final: dict) -> dict:
        answer = _redact_text(final.get("answer") or "", settings)
        passages = final.get("passages") or []
        citations = final.get("citations") or []
        app.state.sessions.remember(session, message, answer, passages, citations)
        record = {
            "endpoint": endpoint,
            "conversation_id": session.conversation_id,
            "message": message,
            "filters": raw_filters,
            "filter_expression": expression,
            "collection_id": settings.collection_id,
            "collection_version": settings.collection_version,
            "model": settings.model,
            "passages": passages,
            "citations": citations,
            "answer": answer,
            "disclaimer": DISCLAIMER,
            "human_review_required": True,
        }
        app.state.audit.write(record, settings.secrets)
        return {
            "conversation_id": session.conversation_id,
            "disclaimer": DISCLAIMER,
            "human_review_required": True,
            "human_review_note": HUMAN_REVIEW_NOTE,
            "collection_id": settings.collection_id,
            "collection_version": settings.collection_version,
            "model": settings.model,
            "filter_expression": expression,
            "answer": answer,
            "citations": citations,
            "passages": passages,
        }

    def consume(session, endpoint: str, message: str, raw_filters: dict | None, expression: str | None) -> dict:
        final = None
        for event in run_turn(session, message, raw_filters, "brief" if endpoint == "brief" else "chat"):
            if event["type"] == "final":
                final = event
        if final is None:
            final = {"answer": "", "citations": [], "passages": []}
        return finish(session, endpoint, message, raw_filters, expression, final)

    @app.post("/chat", dependencies=[Depends(enforce_auth), Depends(enforce_rate_limit)])
    def chat(body: ChatRequest):
        raw_filters, expression = _checked_filters(body.filters)
        session = app.state.sessions.get_or_create(body.conversation_id)
        reject_if_unconfigured("chat", session, body.message, raw_filters, expression)
        if not body.stream:
            payload = consume(session, "chat", body.message, raw_filters, expression)
            return payload

        def events() -> Iterator[str]:
            meta = {
                "conversation_id": session.conversation_id,
                "disclaimer": DISCLAIMER,
                "human_review_required": True,
                "human_review_note": HUMAN_REVIEW_NOTE,
                "collection_version": settings.collection_version,
                "model": settings.model,
                "filter_expression": expression,
            }
            yield _sse("meta", meta)
            final = None
            try:
                for event in run_turn(session, body.message, raw_filters, "chat"):
                    if event["type"] == "token":
                        yield _sse("token", {"text": _redact_text(event.get("text") or "", settings)})
                    elif event["type"] == "final":
                        final = event
            except HTTPException as exc:
                app.state.audit.write(
                    {
                        "endpoint": "chat",
                        "conversation_id": session.conversation_id,
                        "message": body.message,
                        "filters": raw_filters,
                        "filter_expression": expression,
                        "collection_version": settings.collection_version,
                        "model": settings.model,
                        "answer": "",
                        "error": exc.detail,
                        "disclaimer": DISCLAIMER,
                        "human_review_required": True,
                    },
                    settings.secrets,
                )
                yield _sse("error", {"detail": exc.detail, "disclaimer": DISCLAIMER})
                return
            payload = finish(session, "chat", body.message, raw_filters, expression, final or {})
            yield _sse("done", payload)

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/brief", dependencies=[Depends(enforce_auth), Depends(enforce_rate_limit)])
    def brief(body: BriefRequest) -> dict:
        raw_filters, expression = _checked_filters(body.filters)
        session = app.state.sessions.get_or_create(body.conversation_id)
        reject_if_unconfigured("brief", session, body.topic, raw_filters, expression)
        payload = consume(session, "brief", body.topic, raw_filters, expression)
        body_text = payload["answer"]
        markdown = (
            f"{DISCLAIMER}\n\n"
            f"**Human review:** {HUMAN_REVIEW_NOTE}\n\n"
            f"Collection version: {settings.collection_version}\n\n"
            f"{body_text}"
        )
        payload["markdown"] = markdown
        payload["title"] = _title_from_markdown(body_text) or "Policy brief"
        payload["human_review_required"] = True
        return payload

    @app.get("/sources", dependencies=[Depends(enforce_auth), Depends(enforce_rate_limit)])
    def sources(conversation_id: str) -> dict:
        session = app.state.sessions.get(conversation_id)
        if session is None or not session.last_answer:
            raise HTTPException(status_code=404, detail="No answer is stored for that conversation_id.")
        return {
            "conversation_id": conversation_id,
            "disclaimer": DISCLAIMER,
            "human_review_required": True,
            "human_review_note": HUMAN_REVIEW_NOTE,
            "collection_version": settings.collection_version,
            "citations": session.citations,
            "passages": session.passages,
        }

    return app


def _title_from_markdown(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


app = create_app()
