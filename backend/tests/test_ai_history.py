"""Test ROSSO tempo 1 di F14 (ADR-0032 p.3): la history completa arriva al provider
dal router; il troncamento avviene nell'adapter, non nel router."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.ai.providers.gemini as gemini_module
from app.ai.provider import AIAnswer, AIProvider
from app.ai.providers.gemini import GeminiProvider
from app.db import Base, get_session
from app.models import ChatMessage, ChatSession
from app.routers import ai as ai_router


class _RecordingProvider(AIProvider):
    def __init__(self):
        self.calls = 0
        self.history = None
        self.history_len = None

    def answer(self, question, session, history=None):
        self.calls += 1
        self.history = history
        self.history_len = len(history) if history is not None else None
        return AIAnswer(text="ok", tool_calls=[], truncated=False)


def _turns():
    out = []
    for i in range(1, 10):
        out.append(("user", f"q{i}"))
        out.append(("assistant", f"a{i}"))
    return out


def test_router_passes_complete_history_to_provider():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    seeded = _turns()
    base = datetime(2026, 1, 1, 12, 0, 0)
    with Session() as s:
        chat = ChatSession(title="t", created_at=base, updated_at=base)
        s.add(chat)
        s.flush()
        for n, (role, content) in enumerate(seeded):
            s.add(
                ChatMessage(
                    session_id=chat.id,
                    role=role,
                    content=content,
                    created_at=base + timedelta(seconds=n),
                )
            )
        s.commit()
        session_id = chat.id

    def override_get_session():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    fake = _RecordingProvider()
    app = FastAPI()
    app.include_router(ai_router.router)
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[ai_router.get_ai_provider] = lambda: fake
    client = TestClient(app)

    resp = client.post("/ai/query", json={"question": "e il mese prima?", "session_id": session_id})

    assert fake.calls == 1
    assert fake.history_len == 18
    assert [(t.role, t.content) for t in fake.history] == seeded
    assert resp.status_code == 200


def test_gemini_adapter_truncates_history_before_provider_call(monkeypatch):
    monkeypatch.setattr(gemini_module.settings, "ai_api_key", "test-key")
    monkeypatch.setattr(gemini_module.settings, "ai_model", "gemini-3.1-flash-lite")

    class _Interactions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(id="i-1", output_text="risposta", steps=[])

    client = SimpleNamespace(interactions=_Interactions())
    provider = GeminiProvider(client_factory=lambda: client)

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    history = [SimpleNamespace(role=role, content=content) for role, content in _turns()]

    with Session() as session:
        provider.answer("e il mese prima?", session, history=history)

    first = client.interactions.calls[0]
    steps = first["input"]
    assert len(steps) == 13
    expected = _turns()[-12:]
    assert [s["type"] for s in steps[:12]] == [
        "user_input" if role == "user" else "model_output" for role, _ in expected
    ]
    assert [s["content"] for s in steps[:12]] == [
        [{"type": "text", "text": content}] for _, content in expected
    ]
    assert steps[12] == {"type": "user_input", "content": [{"type": "text", "text": "e il mese prima?"}]}
    assert "previous_interaction_id" not in first
