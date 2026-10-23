"""Test di F14 T7 (ADR-0032): persistenza scritta dal router ed endpoint sessioni."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.provider import AIAnswer, AIProvider, AIProviderError, AIProviderNotConfigured, ToolCall
from app.db import Base, get_session
from app.models import Account, ChatMessage, ChatSession, Transaction
from app.routers import ai as ai_router


class _Fake(AIProvider):
    def __init__(self):
        self.history_len = None
        self.error: Exception | None = None
        self.tool_calls: list[ToolCall] = []
        self.truncated = False

    def answer(self, question, session, history=None):
        self.history_len = len(history) if history is not None else None
        if self.error is not None:
            raise self.error
        return AIAnswer(text=f"risposta a {question}", tool_calls=self.tool_calls, truncated=self.truncated)


@pytest.fixture
def env():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    def override_get_session():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    fake = _Fake()
    app = FastAPI()
    app.include_router(ai_router.router)
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[ai_router.get_ai_provider] = lambda: fake
    return TestClient(app), fake, Session


def _count(Session, model):
    with Session() as s:
        return s.execute(select(func.count()).select_from(model)).scalar_one()


def test_first_question_creates_session_and_two_messages(env):
    client, _, Session = env
    long_q = "x" * 100
    resp = client.post("/ai/query", json={"question": f"  {long_q}  "})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"answer", "tools_used", "truncated", "session_id"}
    with Session() as s:
        chat = s.get(ChatSession, body["session_id"])
        assert chat.title == "x" * 80 + "…"
        msgs = s.scalars(
            select(ChatMessage).order_by(ChatMessage.created_at, ChatMessage.id)
        ).all()
        assert [m.role for m in msgs] == ["user", "assistant"]


def test_short_title_not_truncated(env):
    client, _, Session = env
    sid = client.post("/ai/query", json={"question": " ciao "}).json()["session_id"]
    with Session() as s:
        assert s.get(ChatSession, sid).title == "ciao"


def test_follow_up_reuses_session_and_passes_history(env):
    client, fake, Session = env
    sid = client.post("/ai/query", json={"question": "uno"}).json()["session_id"]
    with Session() as s:
        first_updated = s.get(ChatSession, sid).updated_at
    resp = client.post("/ai/query", json={"question": "due", "session_id": sid})
    assert resp.json()["session_id"] == sid
    assert fake.history_len == 2
    assert _count(Session, ChatSession) == 1
    assert _count(Session, ChatMessage) == 4
    with Session() as s:
        assert s.get(ChatSession, sid).updated_at > first_updated


def test_unknown_session_id_is_404(env):
    client, _, Session = env
    resp = client.post("/ai/query", json={"question": "q", "session_id": 999})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Conversazione non trovata."
    assert _count(Session, ChatSession) == 0


@pytest.mark.parametrize(
    "error,status",
    [(AIProviderNotConfigured("x"), 400), (AIProviderError("boom"), 502)],
)
def test_provider_errors_persist_nothing(env, error, status):
    client, fake, Session = env
    # nuova sessione
    fake.error = error
    assert client.post("/ai/query", json={"question": "q"}).status_code == status
    assert _count(Session, ChatSession) == 0
    assert _count(Session, ChatMessage) == 0
    # sessione esistente
    fake.error = None
    sid = client.post("/ai/query", json={"question": "ok"}).json()["session_id"]
    fake.error = error
    assert client.post("/ai/query", json={"question": "q", "session_id": sid}).status_code == status
    assert _count(Session, ChatSession) == 1
    assert _count(Session, ChatMessage) == 2


def test_session_deleted_during_answer_creates_new_session_even_with_live_orm_ref(env):
    """I2: sessione cancellata da un'altra Session MENTRE il provider risponde ->
    nessun errore, risposta persistita in una sessione nuova. Il provider tiene un
    riferimento forte all'oggetto ORM nella Session di richiesta: con `session.get`
    la rilettura lo rivedrebbe dalla identity map (500 al flush)."""
    client, fake, Session = env
    sid = client.post("/ai/query", json={"question": "uno"}).json()["session_id"]

    held = []

    def answer(question, session, history=None):
        held.append(session.get(ChatSession, sid))  # riferimento forte vivo
        assert held[0] is not None
        with Session() as other:  # un'ALTRA Session cancella la conversazione
            other.execute(delete(ChatMessage).where(ChatMessage.session_id == sid))
            other.execute(delete(ChatSession).where(ChatSession.id == sid))
            other.commit()
        return AIAnswer(text="risposta tardiva", tool_calls=[], truncated=False)

    fake.answer = answer
    resp = client.post("/ai/query", json={"question": "due", "session_id": sid})

    assert resp.status_code == 200
    new_sid = resp.json()["session_id"]
    assert new_sid is not None
    with Session() as s:
        assert s.get(ChatSession, new_sid) is not None
        msgs = s.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == new_sid)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        ).all()
        assert [(m.role, m.content) for m in msgs] == [("user", "due"), ("assistant", "risposta tardiva")]
        assert s.get(ChatSession, new_sid).title == "due"


def test_502_detail_is_redacted(env, monkeypatch):
    """M7: il detail del 502 non lascia filtrare il valore di AI_API_KEY."""
    from app.config import settings

    sentinel = "SENTINELLA-KEY-9f3a2c"
    monkeypatch.setattr(settings, "ai_api_key", sentinel)
    client, fake, _ = env
    fake.error = AIProviderError(f"401 Unauthorized, key={sentinel} rejected")
    resp = client.post("/ai/query", json={"question": "q"})
    assert resp.status_code == 502
    assert sentinel not in resp.text
    assert "<ai_api_key>" in resp.json()["detail"]


def test_tools_json_and_truncated_persisted(env):
    client, fake, Session = env
    fake.tool_calls = [ToolCall(name="get_accounts", args={"a": 1}, result_summary="2 conti")]
    fake.truncated = True
    body = client.post("/ai/query", json={"question": "con tool"}).json()
    with Session() as s:
        user, assistant = s.scalars(
            select(ChatMessage).order_by(ChatMessage.created_at, ChatMessage.id)
        ).all()
        assert user.tools_json is None
        assert json.loads(assistant.tools_json) == body["tools_used"]
        assert assistant.truncated is True
    detail = client.get(f"/ai/sessions/{body['session_id']}").json()
    assert detail["messages"][0]["tools_used"] is None
    assert detail["messages"][0]["truncated"] is False
    assert detail["messages"][1]["tools_used"] == body["tools_used"]
    assert detail["messages"][1]["truncated"] is True

    fake.tool_calls = []
    fake.truncated = False
    client.post("/ai/query", json={"question": "senza", "session_id": body["session_id"]})
    with Session() as s:
        last = s.scalars(select(ChatMessage).order_by(ChatMessage.id.desc())).first()
        assert last.tools_json == "[]"


def test_get_session_404(env):
    client, _, _ = env
    resp = client.get("/ai/sessions/42")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Conversazione non trovata."


def test_delete_single_session(env):
    client, _, Session = env
    a = client.post("/ai/query", json={"question": "a"}).json()["session_id"]
    b = client.post("/ai/query", json={"question": "b"}).json()["session_id"]
    resp = client.delete(f"/ai/sessions/{a}")
    assert resp.status_code == 204
    with Session() as s:
        assert s.scalars(select(ChatMessage).where(ChatMessage.session_id == a)).all() == []
        assert s.get(ChatSession, a) is None
        assert s.get(ChatSession, b) is not None
        assert len(s.scalars(select(ChatMessage).where(ChatMessage.session_id == b)).all()) == 2
    assert client.delete(f"/ai/sessions/{a}").status_code == 404


def test_delete_all_requires_confirm(env):
    client, _, Session = env
    client.post("/ai/query", json={"question": "a"})
    client.post("/ai/query", json={"question": "b"})
    expected = "Azzera storico richiede 'confirm: true' (operazione distruttiva, ADR-0032)."

    resp = client.delete("/ai/sessions")
    assert resp.status_code == 400 and resp.json()["detail"] == expected
    resp = client.request("DELETE", "/ai/sessions", json={"confirm": False})
    assert resp.status_code == 400 and resp.json()["detail"] == expected
    assert _count(Session, ChatSession) == 2

    resp = client.request("DELETE", "/ai/sessions", json={"confirm": True})
    assert resp.status_code == 200
    assert resp.json() == {"deleted_sessions": 2, "deleted_messages": 4}
    assert _count(Session, ChatSession) == 0
    assert _count(Session, ChatMessage) == 0


def test_list_sessions_order_and_message_count(env):
    client, _, _ = env
    a = client.post("/ai/query", json={"question": "a"}).json()["session_id"]
    b = client.post("/ai/query", json={"question": "b"}).json()["session_id"]
    client.post("/ai/query", json={"question": "a2", "session_id": a})
    sessions = client.get("/ai/sessions").json()["sessions"]
    assert [s["id"] for s in sessions] == [a, b]
    assert sessions[0]["message_count"] == 4
    assert sessions[1]["message_count"] == 2
    assert set(sessions[0]) == {"id", "title", "created_at", "updated_at", "message_count"}


def test_query_sequence_does_not_touch_financial_tables(env):
    client, _, Session = env
    with Session() as s:
        s.add(Account(name="Conto"))
        s.commit()
    before = (_count(Session, Transaction), _count(Session, Account))
    sid = client.post("/ai/query", json={"question": "a"}).json()["session_id"]
    client.post("/ai/query", json={"question": "b", "session_id": sid})
    client.delete(f"/ai/sessions/{sid}")
    assert (_count(Session, Transaction), _count(Session, Account)) == before
