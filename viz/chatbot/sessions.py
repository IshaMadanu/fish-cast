"""Short-lived, process-local conversation history."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field


MAX_MESSAGES = 20


@dataclass
class Session:
    conversation_id: str
    messages: list[dict] = field(default_factory=list)
    passages: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    last_answer: str = ""


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def get_or_create(self, conversation_id: str | None) -> Session:
        with self._lock:
            if conversation_id:
                existing = self._sessions.get(conversation_id)
                if existing is not None:
                    return existing
                session = Session(conversation_id=conversation_id)
                self._sessions[conversation_id] = session
                return session
            new_id = uuid.uuid4().hex
            session = Session(conversation_id=new_id)
            self._sessions[new_id] = session
            return session

    def get(self, conversation_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(conversation_id)

    def remember(self, session: Session, user_message: str, answer: str, passages: list[dict], citations: list[dict]) -> None:
        with self._lock:
            session.messages.append({"role": "user", "content": user_message})
            session.messages.append({"role": "assistant", "content": answer})
            del session.messages[:-MAX_MESSAGES]
            session.passages = passages
            session.citations = citations
            session.last_answer = answer
