"""Pull citation URIs and collection passages off an xAI chat response.

The SDK objects are protocol buffers. Tests pass simple stand-ins, so every
access goes through getattr or dict lookup.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlparse


def _mapping_get(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _parse_collection_uri(uri: str) -> dict:
    """collections://collection_id/files/file_id -> ids, when the URI matches."""
    parsed = urlparse(uri)
    passage = {"uri": uri, "quote": "", "file_id": None, "collection_id": None, "file_name": None, "score": None}
    if parsed.scheme != "collections":
        return passage
    collection_id = parsed.netloc
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    file_id = parts[-1] if len(parts) >= 2 and parts[-2] == "files" else None
    passage["collection_id"] = collection_id or None
    passage["file_id"] = file_id
    return passage


def _passage_from_collection_citation(citation: Any) -> dict | None:
    coll = _mapping_get(citation, "collections_citation")
    if not coll:
        return None
    collection_ids = _mapping_get(coll, "collection_ids") or []
    return {
        "uri": None,
        "file_id": _mapping_get(coll, "file_id"),
        "chunk_id": _mapping_get(coll, "chunk_id"),
        "quote": _mapping_get(coll, "chunk_content") or "",
        "score": _mapping_get(coll, "score"),
        "collection_ids": list(collection_ids),
        "file_name": _mapping_get(coll, "file_name") or _mapping_get(citation, "file_name"),
    }


def _text_pieces(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    pieces: list[str] = []
    for item in content:
        if isinstance(item, str):
            pieces.append(item)
        else:
            text = _mapping_get(item, "text")
            if text:
                pieces.append(str(text))
    return "\n".join(pieces)


def extract_sources(response: Any) -> tuple[list[dict], list[dict]]:
    """Return (citations, passages) from a finished chat response."""
    citations: list[dict] = []
    for item in list(_mapping_get(response, "citations") or []):
        citations.append({"uri": str(item)})

    passages: list[dict] = []
    for citation in list(_mapping_get(response, "inline_citations") or []):
        passage = _passage_from_collection_citation(citation)
        if passage is not None:
            passages.append(passage)

    if not passages:
        for uri_item in citations:
            passages.append(_parse_collection_uri(uri_item["uri"]))

    for output in list(_mapping_get(response, "tool_outputs") or []):
        message = _mapping_get(output, "message") or output
        text = _text_pieces(_mapping_get(message, "content"))
        if text and not any(passage.get("quote") == text for passage in passages):
            passages.append({"uri": None, "quote": text, "file_id": None, "file_name": None, "score": None})
    return citations, passages
