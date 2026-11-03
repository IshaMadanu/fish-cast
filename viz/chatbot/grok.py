"""Grok chat over an xAI Collection.

Call shape checked against xai-sdk 1.21.0 (PyPI, 23 October 2026) and the
collections_search example in the xAI docs, which uses model grok-4.7:

    from xai_sdk import Client
    from xai_sdk.chat import system, user
    from xai_sdk.tools import collections_search, web_search

    client = Client(api_key=..., timeout=...)
    chat = client.chat.create(
        model="grok-4.7",
        tools=[collections_search(collection_ids=[...], instructions=..., retrieval_mode="hybrid")],
        include=["inline_citations", "collections_search_call_output", "verbose_streaming"],
        reasoning_effort="high",
    )
    chat.append(system(...))
    chat.append(user(...))
    for response, chunk in chat.stream():
        ...

collections_search does not take a metadata filter in this SDK version.
``make_collections_tool`` passes ``filter=`` only when the installed helper
declares that parameter.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

from viz.chatbot.citations import extract_sources
from viz.chatbot.filters import filter_expression
from viz.chatbot.prompt import BRIEF_TASK, FILTER_TASK, SYSTEM_PROMPT
from viz.chatbot.settings import Settings

logger = logging.getLogger(__name__)


class ChatbotError(Exception):
    status_code = 502
    detail = "The model request failed."


class CollectionNotConfigured(ChatbotError):
    status_code = 503
    detail = "XAI_COLLECTION_ID is not set. Build the collection and set the id before chatting."


class MissingApiKey(ChatbotError):
    status_code = 503
    detail = "XAI_API_KEY is not set."


def load_sdk() -> SimpleNamespace:
    """Import the official SDK. Kept behind a function so tests can replace it."""
    from xai_sdk import Client
    from xai_sdk.chat import assistant, system, user
    from xai_sdk.tools import collections_search, web_search

    return SimpleNamespace(
        Client=Client,
        system=system,
        user=user,
        assistant=assistant,
        collections_search=collections_search,
        web_search=web_search,
    )


def _explicit_param(function: Any, name: str) -> bool:
    try:
        parameters = inspect.signature(function).parameters
    except (TypeError, ValueError):
        return False
    parameter = parameters.get(name)
    if parameter is None:
        return False
    return parameter.kind in (
        inspect.Parameter.KEYWORD_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )


def make_collections_tool(
    sdk: SimpleNamespace,
    *,
    collection_ids: list[str],
    limit: int,
    instructions: str,
    retrieval_mode: str,
    expression: str | None,
) -> Any:
    kwargs: dict[str, Any] = {"collection_ids": collection_ids}
    if _explicit_param(sdk.collections_search, "limit"):
        kwargs["limit"] = limit
    if _explicit_param(sdk.collections_search, "instructions"):
        kwargs["instructions"] = instructions
    if _explicit_param(sdk.collections_search, "retrieval_mode"):
        kwargs["retrieval_mode"] = retrieval_mode
    if expression and _explicit_param(sdk.collections_search, "filter"):
        kwargs["filter"] = expression
    return sdk.collections_search(**kwargs)


def search_instructions(expression: str | None) -> str:
    base = (
        "Search the FishCast policy collection. Prefer passages that state model limitations "
        "when the question is about skill, forecasts, or marine protected areas. "
        "Return chunks that can be cited by file name."
    )
    if not expression:
        return base
    return (
        base
        + " Apply this metadata filter and skip documents that do not match it: "
        + expression
    )


class GrokBackend:
    def __init__(self, settings: Settings, sdk_loader: Any = load_sdk) -> None:
        self.settings = settings
        self._sdk_loader = sdk_loader

    def stream(self, *, history: list[dict], message: str, filters: dict | None, mode: str) -> Iterator[dict]:
        if not self.settings.xai_api_key:
            raise MissingApiKey()
        if not self.settings.collection_id:
            raise CollectionNotConfigured()

        expression = filter_expression(filters)
        sdk = self._sdk_loader()
        client = sdk.Client(api_key=self.settings.xai_api_key, timeout=self.settings.request_timeout_s)
        instructions = search_instructions(expression)
        tools = [
            make_collections_tool(
                sdk,
                collection_ids=[self.settings.collection_id],
                limit=self.settings.search_limit,
                instructions=instructions,
                retrieval_mode="hybrid",
                expression=expression,
            )
        ]
        if self.settings.enable_web_search:
            tools.append(sdk.web_search())

        create_kwargs: dict[str, Any] = {
            "model": self.settings.model,
            "tools": tools,
            "include": ["inline_citations", "collections_search_call_output", "verbose_streaming"],
        }
        if self.settings.reasoning_effort:
            create_kwargs["reasoning_effort"] = self.settings.reasoning_effort
        chat = client.chat.create(**create_kwargs)
        chat.append(sdk.system(SYSTEM_PROMPT))
        if expression:
            chat.append(sdk.system(FILTER_TASK.format(expression=expression)))
        if mode == "brief":
            chat.append(sdk.system(BRIEF_TASK))
        for turn in history:
            role = turn.get("role")
            content = turn.get("content") or ""
            if role == "assistant":
                chat.append(sdk.assistant(content))
            elif role == "user":
                chat.append(sdk.user(content))
        chat.append(sdk.user(message))

        tokens: list[str] = []
        latest: Any = None
        try:
            for response, chunk in chat.stream():
                latest = response
                text = getattr(chunk, "content", None) or ""
                if text:
                    tokens.append(text)
                    yield {"type": "token", "text": text}
        except ChatbotError:
            raise
        except Exception as exc:
            logger.error("grok request failed: %s", type(exc).__name__)
            raise ChatbotError() from exc

        answer = (getattr(latest, "content", None) or "").strip() or "".join(tokens).strip()
        citations, passages = extract_sources(latest) if latest is not None else ([], [])
        yield {
            "type": "final",
            "answer": answer,
            "citations": citations,
            "passages": passages,
            "filter_expression": expression,
        }
