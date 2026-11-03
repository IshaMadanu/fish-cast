"""Streamlit chat UI for the policy chatbot.

Run from the repository root:

    streamlit run viz/chatbot/ui.py

The disclaimer stays on screen. Citations for the latest answer are shown under
the reply, and the sources endpoint can be reloaded for the same conversation.
"""

from __future__ import annotations

import json
import os
import uuid

import httpx
import streamlit as st

from viz.chatbot.errors import detail_from_body, http_error_message
from viz.chatbot.prompt import DISCLAIMER, HUMAN_REVIEW_NOTE

DOC_TYPES = ["model_output", "project_doc", "policy", "literature", "limitations"]
SKILL_STATUS = ["no_skill", "partial", "not_applicable", "unknown"]


def _auth() -> httpx.BasicAuth | None:
    user = st.session_state.get("auth_user") or ""
    password = st.session_state.get("auth_password") or ""
    if not password:
        return None
    return httpx.BasicAuth(user or "fishcast", password)


def _filters() -> dict | None:
    filters: dict = {}
    if st.session_state.get("filter_doc_type"):
        filters["doc_type"] = st.session_state["filter_doc_type"]
    if st.session_state.get("filter_skill"):
        filters["skill_status"] = st.session_state["filter_skill"]
    if st.session_state.get("filter_region"):
        filters["region"] = st.session_state["filter_region"].strip()
    if st.session_state.get("filter_year"):
        filters["year"] = st.session_state["filter_year"].strip()
    if st.session_state.get("filter_preprocessing"):
        filters["preprocessing_version"] = st.session_state["filter_preprocessing"].strip()
    return filters or None


def _read_sse(response: httpx.Response):
    event = "message"
    data_lines: list[str] = []
    for line in response.iter_lines():
        if line == "":
            if data_lines:
                yield event, json.loads("\n".join(data_lines))
            event = "message"
            data_lines = []
            continue
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].strip())
    if data_lines:
        yield event, json.loads("\n".join(data_lines))


def _post_chat(message: str) -> dict:
    url = st.session_state["api_url"].rstrip("/") + "/chat"
    payload = {
        "message": message,
        "conversation_id": st.session_state["conversation_id"],
        "filters": _filters(),
        "stream": True,
    }
    tokens: list[str] = []
    done: dict = {}
    box = st.empty()
    with httpx.stream("POST", url, json=payload, auth=_auth(), timeout=st.session_state["timeout"]) as response:
        if response.status_code >= 400:
            detail = detail_from_body(response.read())
            raise RuntimeError(detail or f"The chat service returned {response.status_code}.")
        for event, data in _read_sse(response):
            if event == "token":
                tokens.append(data.get("text") or "")
                box.markdown("".join(tokens))
            elif event == "error":
                raise RuntimeError(data.get("detail") or "The chat request failed.")
            elif event == "done":
                done = data
    answer = (done.get("answer") or "".join(tokens)).strip()
    box.markdown(answer)
    return done


def _show_passages(passages: list[dict]) -> None:
    if not passages:
        st.caption("No passages were returned for this answer.")
        return
    for passage in passages:
        label = passage.get("file_name") or passage.get("file_id") or passage.get("uri") or "passage"
        score = passage.get("score")
        title = f"{label}" if score is None else f"{label} (score {score})"
        with st.expander(title):
            quote = passage.get("quote") or ""
            if quote:
                st.markdown("> " + quote.replace("\n", "\n> "))
            else:
                st.caption("The collection cited this file without returning a text chunk.")


def main() -> None:
    st.set_page_config(page_title="Marine Populations Policy Chatbot", layout="centered")
    st.title("Marine Populations Policy Chatbot")
    st.warning(DISCLAIMER)
    st.caption(HUMAN_REVIEW_NOTE)

    if "conversation_id" not in st.session_state:
        st.session_state["conversation_id"] = uuid.uuid4().hex
    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    with st.sidebar:
        st.header("Connection")
        st.text_input("API URL", os.environ.get("CHATBOT_API_URL", "http://localhost:8000"), key="api_url")
        st.text_input("Basic auth user", os.environ.get("CHATBOT_BASIC_AUTH_USER", ""), key="auth_user")
        st.text_input(
            "Basic auth password",
            type="password",
            value=os.environ.get("CHATBOT_BASIC_AUTH_PASSWORD", ""),
            key="auth_password",
        )
        st.number_input("Timeout (seconds)", min_value=10, max_value=600, value=180, key="timeout")
        st.header("Filters")
        st.multiselect("Document type", DOC_TYPES, key="filter_doc_type")
        st.multiselect("Skill status", SKILL_STATUS, key="filter_skill")
        st.text_input("Region", key="filter_region")
        st.text_input("Year", key="filter_year")
        st.text_input("Preprocessing version", key="filter_preprocessing")
        st.caption("Filters are sent to the API and recorded in the audit log.")
        if st.button("New conversation"):
            st.session_state["conversation_id"] = uuid.uuid4().hex
            st.session_state["messages"] = []
            st.rerun()

    for item in st.session_state["messages"]:
        with st.chat_message(item["role"]):
            st.markdown(item["content"])
            if item["role"] == "assistant":
                st.caption(DISCLAIMER)
                _show_passages(item.get("passages") or [])

    message = st.chat_input("Ask about krill, climate, MPAs, or model limitations")
    if message:
        st.session_state["messages"].append({"role": "user", "content": message})
        with st.chat_message("user"):
            st.markdown(message)
        with st.chat_message("assistant"):
            try:
                done = _post_chat(message)
            except Exception as exc:  # noqa: BLE001 — show the failure in the page, do not hide it.
                st.error(http_error_message(exc))
                st.warning(DISCLAIMER)
                return
            answer = done.get("answer") or ""
            st.caption(DISCLAIMER)
            if done.get("human_review_required"):
                st.info(done.get("human_review_note") or HUMAN_REVIEW_NOTE)
            _show_passages(done.get("passages") or [])
            if done.get("collection_version"):
                st.caption(f"Collection version {done['collection_version']} · model {done.get('model', '')}")
        st.session_state["messages"].append(
            {"role": "assistant", "content": answer, "passages": done.get("passages") or []}
        )

    st.divider()
    st.subheader("One-page brief")
    topic = st.text_area("Brief topic", placeholder="Climate-only skill and what it means for a future MPA discussion")
    if st.button("Write brief", disabled=not topic.strip()):
        url = st.session_state["api_url"].rstrip("/") + "/brief"
        payload = {
            "topic": topic.strip(),
            "conversation_id": st.session_state["conversation_id"],
            "filters": _filters(),
        }
        try:
            response = httpx.post(url, json=payload, auth=_auth(), timeout=st.session_state["timeout"])
            response.raise_for_status()
            body = response.json()
        except Exception as exc:  # noqa: BLE001
            st.error(http_error_message(exc))
            st.warning(DISCLAIMER)
        else:
            st.warning(DISCLAIMER)
            if body.get("human_review_required"):
                st.error(body.get("human_review_note") or HUMAN_REVIEW_NOTE)
            st.markdown(body.get("markdown") or body.get("answer") or "")
            _show_passages(body.get("passages") or [])
            st.session_state["messages"].append({"role": "user", "content": topic.strip()})
            st.session_state["messages"].append(
                {
                    "role": "assistant",
                    "content": body.get("markdown") or body.get("answer") or "",
                    "passages": body.get("passages") or [],
                }
            )

    if st.button("Reload sources for this conversation"):
        url = st.session_state["api_url"].rstrip("/") + "/sources"
        try:
            response = httpx.get(
                url,
                params={"conversation_id": st.session_state["conversation_id"]},
                auth=_auth(),
                timeout=30,
            )
            response.raise_for_status()
            body = response.json()
        except Exception as exc:  # noqa: BLE001
            st.error(http_error_message(exc))
            st.warning(DISCLAIMER)
        else:
            st.caption(body.get("disclaimer") or DISCLAIMER)
            _show_passages(body.get("passages") or [])


if __name__ == "__main__":
    main()
