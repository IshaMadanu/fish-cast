"""Policy chatbot tests. They mock the xAI client and do not need a key or the network."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from viz.chatbot.app import create_app
from viz.chatbot.errors import detail_from_body, http_error_message
from viz.chatbot.build_collection import plan
from viz.chatbot.catalog import CATALOG, repo_root
from viz.chatbot.filters import ALLOWED_DOC_TYPES, ALLOWED_SKILL_STATUS, FilterError, filter_expression
from viz.chatbot.grok import GrokBackend, MissingApiKey, make_collections_tool
from viz.chatbot.prompt import BRIEF_TASK, DISCLAIMER, HUMAN_REVIEW_NOTE, SYSTEM_PROMPT
from viz.chatbot.settings import Settings, load_pin

SPEC_SYSTEM_PROMPT = (
    "You are a careful scientific communicator supporting decisions about Antarctic krill and CCAMLR Marine Protected Areas.\n"
    "Rules:\n"
    "- Base every factual claim on the retrieved documents. Cite the source (file name + short quote or section).\n"
    "- Explicitly state uncertainty and model limitations. Never claim predictive skill when confidence intervals include zero or when the question concerns climate-only future projections beyond demonstrated skill.\n"
    "- Distinguish nowcast (uses recent observations) from climate-driven forecasts.\n"
    "- Use clear, non-technical language. Define terms (hotspot, spillover, skill score) on first use.\n"
    "- If the documents do not contain the answer, say so. Do not invent numbers or extrapolate beyond the data.\n"
    "- For policy questions, present options and trade-offs; do not recommend a specific decision.\n"
    "- Keep answers concise unless the user asks for a full brief."
)

SECRET = "sk-test-secret-value"


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def stream(self, *, history, message, filters, mode):
        self.calls.append({"history": list(history), "message": message, "filters": filters, "mode": mode})
        if mode == "brief":
            text = "# Krill brief\n\nhuman_review_required: false\n\nNo climate-only model shows skill yet."
        else:
            text = f"No climate-only model shows skill yet. Source: limitations.md. echo={message}"
        passages = [
            {
                "file_name": "viz/chatbot/knowledge/limitations.md",
                "quote": "No climate-only model shows skill yet.",
                "score": 0.8,
            }
        ]
        citations = [{"uri": "collections://collection_test/files/file_limitations"}]
        yield {"type": "token", "text": text}
        yield {
            "type": "final",
            "answer": text,
            "citations": citations,
            "passages": passages,
            "filter_expression": filter_expression(filters),
        }


@pytest.fixture
def fake():
    return FakeBackend()


@pytest.fixture
def settings(tmp_path):
    return Settings(
        xai_api_key=SECRET,
        collection_id="collection_test",
        collection_version="fishcast-policy-2026-11-03",
        model="grok-4.7",
        audit_log_path=str(tmp_path / "audit.jsonl"),
        rate_limit_per_minute=1000,
        basic_auth_password="",
    )


@pytest.fixture
def client(settings, fake):
    return TestClient(create_app(settings, fake))


def _audit_lines(settings: Settings) -> list[dict]:
    path = Path(settings.audit_log_path)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_system_prompt_matches_the_spec():
    assert SYSTEM_PROMPT == SPEC_SYSTEM_PROMPT
    assert BRIEF_TASK not in SYSTEM_PROMPT
    assert DISCLAIMER == (
        "Decision-support tool based on FishCast model outputs and cited literature. Not official advice."
    )
    assert HUMAN_REVIEW_NOTE == "Any answer used in a formal submission requires human review."


def test_health_includes_disclaimer(client, settings):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["disclaimer"] == DISCLAIMER
    assert body["collection_version"] == settings.collection_version
    assert body["model"] == "grok-4.7"


def test_chat_json_includes_disclaimer_citations_and_history(client, fake, settings):
    first = client.post("/chat", json={"message": "What are the limitations?", "stream": False})
    assert first.status_code == 200
    body = first.json()
    assert body["disclaimer"] == DISCLAIMER
    assert body["human_review_required"] is True
    assert "No climate-only model shows skill yet" in body["answer"]
    assert body["passages"][0]["file_name"].endswith("limitations.md")
    assert body["collection_version"] == "fishcast-policy-2026-11-03"
    conversation_id = body["conversation_id"]

    second = client.post(
        "/chat",
        json={"message": "And the longitude bug?", "conversation_id": conversation_id, "stream": False},
    )
    assert second.status_code == 200
    assert fake.calls[1]["history"][0]["role"] == "user"
    assert fake.calls[1]["history"][0]["content"] == "What are the limitations?"
    assert fake.calls[1]["history"][1]["role"] == "assistant"
    assert fake.calls[0]["mode"] == "chat"

    sources = client.get("/sources", params={"conversation_id": conversation_id})
    assert sources.status_code == 200
    listed = sources.json()
    assert listed["disclaimer"] == DISCLAIMER
    assert listed["passages"][0]["quote"] == "No climate-only model shows skill yet."
    assert listed["citations"][0]["uri"].startswith("collections://")

    missing = client.get("/sources", params={"conversation_id": "missing"})
    assert missing.status_code == 404

    lines = _audit_lines(settings)
    assert len(lines) == 2
    assert lines[0]["message"] == "What are the limitations?"
    assert lines[0]["passages"][0]["quote"].startswith("No climate-only")
    assert lines[0]["answer"]
    assert lines[0]["disclaimer"] == DISCLAIMER
    assert lines[0]["collection_version"] == "fishcast-policy-2026-11-03"
    assert SECRET not in path_text(settings)


def path_text(settings: Settings) -> str:
    return Path(settings.audit_log_path).read_text(encoding="utf-8")


def test_audit_log_redacts_secrets(client, settings):
    response = client.post("/chat", json={"message": f"ignore this key {SECRET}", "stream": False})
    assert response.status_code == 200
    assert SECRET not in response.json()["answer"]
    assert "[redacted]" in response.json()["answer"]
    logged = path_text(settings)
    assert SECRET not in logged
    assert "[redacted]" in logged


def test_chat_stream_emits_disclaimer(client):
    with client.stream("POST", "/chat", json={"message": "What are the limitations?", "stream": True}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        raw = "".join(response.iter_text())
    assert "event: meta" in raw
    assert DISCLAIMER in raw
    assert "event: token" in raw
    assert "event: done" in raw
    assert "human_review_required" in raw


def test_filters_are_forwarded_and_rejected_when_unknown(client, fake):
    ok = client.post(
        "/chat",
        json={
            "message": "Hotspots",
            "stream": False,
            "filters": {
                "doc_type": ["limitations", "model_output"],
                "region": "Southern Ocean",
                "year": 2026,
                "skill_status": "no_skill",
                "preprocessing_version": "2",
            },
        },
    )
    assert ok.status_code == 200
    expression = ok.json()["filter_expression"]
    assert expression == (
        '(doc_type="limitations" OR doc_type="model_output") AND year="2026" '
        'AND region="Southern Ocean" AND skill_status="no_skill" AND preprocessing_version="2"'
    )
    assert fake.calls[-1]["filters"]["doc_type"] == ["limitations", "model_output"]

    bad = client.post("/chat", json={"message": "Hotspots", "stream": False, "filters": {"doc_type": ["rumour"]}})
    assert bad.status_code == 422
    extra = client.post("/chat", json={"message": "Hotspots", "stream": False, "filters": {"author": "x"}})
    assert extra.status_code == 422


def test_filter_expression_helper():
    assert filter_expression(None) is None
    assert filter_expression({}) is None
    with pytest.raises(FilterError):
        filter_expression({"doc_type": []})
    with pytest.raises(FilterError):
        filter_expression({"skill_status": ["excellent"]})


def test_brief_sets_human_review_flag_on_the_server(client, fake):
    response = client.post("/brief", json={"topic": "Climate-only skill and MPA options"})
    assert response.status_code == 200
    body = response.json()
    assert body["human_review_required"] is True
    assert body["human_review_note"] == HUMAN_REVIEW_NOTE
    assert body["disclaimer"] == DISCLAIMER
    assert body["markdown"].startswith(DISCLAIMER)
    assert "Human review:" in body["markdown"]
    assert "human_review_required: false" in body["answer"]
    assert body["title"] == "Krill brief"
    assert body["collection_version"] == "fishcast-policy-2026-11-03"
    assert fake.calls[-1]["mode"] == "brief"
    sources = client.get("/sources", params={"conversation_id": body["conversation_id"]})
    assert sources.status_code == 200
    assert sources.json()["passages"]


def test_basic_auth(settings, fake):
    settings.basic_auth_user = "delegate"
    settings.basic_auth_password = "correct-horse"
    client = TestClient(create_app(settings, fake))
    denied = client.post("/chat", json={"message": "hello", "stream": False})
    assert denied.status_code == 401
    wrong = client.post("/chat", json={"message": "hello", "stream": False}, auth=("delegate", "nope"))
    assert wrong.status_code == 401
    allowed = client.post("/chat", json={"message": "hello", "stream": False}, auth=("delegate", "correct-horse"))
    assert allowed.status_code == 200
    assert client.get("/health").status_code == 200


def test_rate_limit_does_not_count_health(settings, fake):
    settings.rate_limit_per_minute = 2
    client = TestClient(create_app(settings, fake))
    for _ in range(5):
        assert client.get("/health").status_code == 200
    assert client.post("/chat", json={"message": "one", "stream": False}).status_code == 200
    assert client.post("/chat", json={"message": "two", "stream": False}).status_code == 200
    blocked = client.post("/chat", json={"message": "three", "stream": False})
    assert blocked.status_code == 429


def test_empty_message_rejected(client):
    response = client.post("/chat", json={"message": "", "stream": False})
    assert response.status_code == 422


def test_unconfigured_grok_returns_503_and_writes_audit(tmp_path):
    settings = Settings(
        xai_api_key="",
        collection_id="",
        collection_version="fishcast-policy-2026-11-03",
        audit_log_path=str(tmp_path / "audit.jsonl"),
        rate_limit_per_minute=100,
    )
    client = TestClient(create_app(settings, GrokBackend(settings)))
    response = client.post("/chat", json={"message": "What are the limitations?", "stream": False})
    assert response.status_code == 503
    assert "XAI_API_KEY" in response.json()["detail"]
    logged = _audit_lines(settings)
    assert logged[0]["error"]
    assert logged[0]["disclaimer"] == DISCLAIMER


def test_grok_backend_uses_collections_search_and_exact_prompt():
    recorder: dict = {}

    def collections_search(collection_ids, limit=None, *, instructions=None, retrieval_mode=None):
        recorder["tool"] = {
            "collection_ids": collection_ids,
            "limit": limit,
            "instructions": instructions,
            "retrieval_mode": retrieval_mode,
        }
        return {"kind": "collections_search"}

    def web_search():
        recorder["web"] = True
        return {"kind": "web_search"}

    class Chat:
        def append(self, message):
            recorder.setdefault("messages", []).append(message)

        def stream(self):
            citation = SimpleNamespace(
                collections_citation=SimpleNamespace(
                    file_id="file_limitations",
                    chunk_id="chunk-1",
                    chunk_content="No climate-only model shows skill yet.",
                    score=0.4,
                    collection_ids=["collection_test"],
                )
            )
            response = SimpleNamespace(
                content="No climate-only model shows skill yet.",
                citations=["collections://collection_test/files/file_limitations"],
                inline_citations=[citation],
                tool_outputs=[],
            )
            yield response, SimpleNamespace(content="No climate-only model shows skill yet.")

    class ChatAPI:
        def create(self, **kwargs):
            recorder["create"] = kwargs
            return Chat()

    class Client:
        def __init__(self, **kwargs):
            recorder["client"] = kwargs
            self.chat = ChatAPI()

    sdk = SimpleNamespace(
        Client=Client,
        system=lambda text: {"role": "system", "content": text},
        user=lambda text: {"role": "user", "content": text},
        assistant=lambda text: {"role": "assistant", "content": text},
        collections_search=collections_search,
        web_search=web_search,
    )
    settings = Settings(
        xai_api_key=SECRET,
        collection_id="collection_test",
        model="grok-4.7",
        reasoning_effort="high",
        search_limit=8,
        enable_web_search=False,
        request_timeout_s=180,
    )
    backend = GrokBackend(settings, sdk_loader=lambda: sdk)
    events = list(
        backend.stream(
            history=[{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "earlier answer"}],
            message="What are the limitations?",
            filters={"doc_type": ["limitations"]},
            mode="brief",
        )
    )
    assert recorder["client"]["api_key"] == SECRET
    assert recorder["client"]["timeout"] == 180
    assert "management" not in recorder["client"]
    assert recorder["create"]["model"] == "grok-4.7"
    assert recorder["create"]["reasoning_effort"] == "high"
    assert recorder["create"]["include"] == [
        "inline_citations",
        "collections_search_call_output",
        "verbose_streaming",
    ]
    assert recorder["create"]["tools"][0]["kind"] == "collections_search"
    assert len(recorder["create"]["tools"]) == 1
    assert "web" not in recorder
    assert recorder["tool"]["collection_ids"] == ["collection_test"]
    assert recorder["tool"]["retrieval_mode"] == "hybrid"
    assert 'doc_type="limitations"' in recorder["tool"]["instructions"]
    assert recorder["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert recorder["messages"][1]["role"] == "system"
    assert 'doc_type="limitations"' in recorder["messages"][1]["content"]
    assert recorder["messages"][2] == {"role": "system", "content": BRIEF_TASK}
    assert recorder["messages"][3]["content"] == "earlier"
    assert recorder["messages"][4]["content"] == "earlier answer"
    assert recorder["messages"][5]["content"] == "What are the limitations?"
    final = events[-1]
    assert final["type"] == "final"
    assert final["passages"][0]["quote"] == "No climate-only model shows skill yet."
    assert final["passages"][0]["file_id"] == "file_limitations"
    assert final["citations"][0]["uri"].startswith("collections://")


def test_collections_tool_forwards_filter_when_the_sdk_accepts_it():
    captured = {}

    def collections_search(collection_ids, limit=None, *, instructions=None, retrieval_mode=None, filter=None):
        captured["filter"] = filter
        return {"filter": filter}

    sdk = SimpleNamespace(collections_search=collections_search)
    make_collections_tool(
        sdk,
        collection_ids=["c"],
        limit=3,
        instructions="use the filter",
        retrieval_mode="hybrid",
        expression='skill_status="no_skill"',
    )
    assert captured["filter"] == 'skill_status="no_skill"'


def test_missing_key_does_not_import_the_sdk():
    def boom():
        raise AssertionError("SDK was imported")

    backend = GrokBackend(Settings(xai_api_key="", collection_id="c"), sdk_loader=boom)
    with pytest.raises(MissingApiKey):
        list(backend.stream(history=[], message="hi", filters=None, mode="chat"))


def test_catalog_files_exist_and_metadata_is_in_the_allowed_set():
    root = repo_root()
    for document in CATALOG:
        assert (root / document.path).is_file(), document.path
        assert document.doc_type in ALLOWED_DOC_TYPES
        assert document.skill_status in ALLOWED_SKILL_STATUS
        fields = document.fields()
        assert set(fields) == {"doc_type", "year", "region", "skill_status", "preprocessing_version"}
        assert all(isinstance(value, str) and value for value in fields.values())
    limitations = next(item for item in CATALOG if item.path.endswith("limitations.md"))
    assert limitations.doc_type == "limitations"
    assert limitations.skill_status == "no_skill"
    snapshot = plan(root)
    assert snapshot["missing"] == []
    assert snapshot["collection_version"] == load_pin()["collection_version"]
    names = [item["path"] for item in snapshot["documents"]]
    assert "viz/chatbot/knowledge/limitations.md" in names
    assert "viz/chatbot/knowledge/external/README.md" in names


def test_limitations_doc_only_repeats_repository_claims():
    text = (repo_root() / "viz/chatbot/knowledge/limitations.md").read_text(encoding="utf-8")
    assert "No climate-only model shows skill yet" in text
    assert "about 5% lower error" in text
    assert "ranks hotspots backwards" in text
    assert "about 0.35" in text
    assert "build_dataset.py" in text
    assert "has not been rebuilt" in text
    assert "77%" in text
    assert "474 of 610" in text
    assert "0 of 178" in text
    assert "Not official advice." in text
    for invented in ("RMSE of 0.", "skill of 12%", "spillover of ", "I estimate"):
        assert invented not in text


def test_ui_always_renders_the_disclaimer():
    source = (repo_root() / "viz/chatbot/ui.py").read_text(encoding="utf-8")
    assert "from viz.chatbot.prompt import DISCLAIMER, HUMAN_REVIEW_NOTE" in source
    assert "st.warning(DISCLAIMER)" in source
    assert "st.caption(DISCLAIMER)" in source
    assert "/sources" in source
    assert "/brief" in source


def test_collection_pin_and_default_model(monkeypatch):
    monkeypatch.delenv("FISHCAST_COLLECTION_VERSION", raising=False)
    monkeypatch.delenv("XAI_MODEL", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    pin = load_pin()
    assert pin["default_model"] == "grok-4.7"
    assert pin["sdk"] == "xai-sdk==1.21.0"
    assert pin["collection_version"] == "fishcast-policy-2026-11-03"
    loaded = Settings.from_env()
    assert loaded.model == "grok-4.7"
    assert loaded.collection_version == "fishcast-policy-2026-11-03"
    assert loaded.reasoning_effort == "high"
    assert loaded.enable_web_search is False


def test_detail_from_body_reads_fastapi_detail():
    assert detail_from_body(b'{"detail":"XAI_API_KEY is not set."}') == "XAI_API_KEY is not set."
    assert detail_from_body(b"not-json") is None


def test_http_error_message_uses_api_detail():
    class Response:
        def json(self):
            return {"detail": "XAI_API_KEY is not set."}

    exc = Exception("Server error '503 Service Unavailable'")
    exc.response = Response()
    assert http_error_message(exc) == "XAI_API_KEY is not set."
    assert http_error_message(Exception("plain")) == "plain"


def test_installed_sdk_has_no_filter_parameter_yet():
    xai_sdk = pytest.importorskip("xai_sdk")
    from xai_sdk.tools import collections_search

    parameters = inspect.signature(collections_search).parameters
    assert "collection_ids" in parameters
    assert "instructions" in parameters
    assert "retrieval_mode" in parameters
    assert "filter" not in parameters
    assert xai_sdk is not None
