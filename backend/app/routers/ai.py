"""`/ai` — `POST /ai/query`, domanda in linguaggio naturale sola lettura sui
propri dati finanziari (F6, ADR-0023). Non piu' stateless (F14, ADR-0032): le
conversazioni sono persistite in `chat_sessions`/`chat_messages` e la
persistenza e' scritta SOLO da questo router, mai da un tool del registry.

Il router non parla mai direttamente con `google-genai`: delega tutto a un
`AIProvider` (contratto in `app.ai.provider`), iniettato via `Depends(get_ai_provider)`
cosi' i test possono sostituirlo con un fake deterministico via
`dependency_overrides` — l'unico mock ammesso in questa fase (ADR-0018 p.7). Il
DB resta reale in ogni test.

Mappatura errori (ADR-0023 p.8, mai un 500 non gestito, mai un crash dell'app):
- `AIProviderNotConfigured` (config assente/incompleta) -> 400, messaggio esplicito.
- `AIProviderError` (tutto il resto: errore di trasporto, risposta inattesa) -> 502.
`AIProviderNotConfigured` puo' emergere in due punti distinti: alla risoluzione
della dependency (`get_ai_provider()`, che chiama `get_provider()` — succede
PRIMA che il corpo dell'endpoint venga eseguito) oppure durante `.answer()` (nel
caso reale odierno non succede mai li', ma il guardrail resta difensivo: nessuna
via di fuga verso un 500 grezzo indipendentemente da dove l'eccezione origina)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import NoReturn

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.ai.provider import (
    AIProvider,
    AIProviderError,
    AIProviderNotConfigured,
    ChatTurn,
    get_provider,
)
from app.db import get_session
from app.drive import redact
from app.models import ChatMessage, ChatSession

router = APIRouter(tags=["ai"])

_TITLE_MAX = 80
_NOT_CONFIGURED_MESSAGE = "layer AI non configurato: imposta AI_PROVIDER, AI_API_KEY, AI_MODEL in .env"


def _raise_http_for(exc: AIProviderError) -> NoReturn:
    if isinstance(exc, AIProviderNotConfigured):
        raise HTTPException(status_code=400, detail=_NOT_CONFIGURED_MESSAGE) from exc
    raise HTTPException(status_code=502, detail=redact(str(exc))) from exc


def get_ai_provider() -> AIProvider:
    """Dependency di default: dispatch reale su `app.ai.provider.get_provider()`.

    Punto di iniezione separato dall'endpoint (non chiamato inline nel body)
    cosi' i test possono sovrascriverlo con un `AIProvider` fake via
    `app.dependency_overrides[get_ai_provider]`, senza toccare configurazione o
    rete reali. Avvolto in try/except perche' `get_provider()` puo' sollevare
    `AIProviderNotConfigured` gia' in fase di risoluzione della dependency, cioe'
    prima che il corpo dell'endpoint (e il suo try/except su `.answer()`) venga
    mai eseguito — senza questo guardrail qui, un `AI_PROVIDER` non configurato
    (lo stato di default) farebbe crashare ogni richiesta con un 500 grezzo."""
    try:
        return get_provider()
    except AIProviderError as exc:
        _raise_http_for(exc)


class QueryRequest(BaseModel):
    question: str
    session_id: int | None = None

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question non puo' essere vuota")
        return value


@router.post("/ai/query")
def query(
    body: QueryRequest,
    provider: AIProvider = Depends(get_ai_provider),
    session: Session = Depends(get_session),
):
    history: list[ChatTurn] = []
    if body.session_id is not None:
        if session.get(ChatSession, body.session_id) is None:
            raise HTTPException(status_code=404, detail="Conversazione non trovata.")
        rows = session.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == body.session_id)
            .order_by(ChatMessage.created_at, ChatMessage.id)
        ).all()
        history = [ChatTurn(role=m.role, content=m.content) for m in rows]

    try:
        answer = provider.answer(body.question, session, history=history)
    except AIProviderError as exc:
        _raise_http_for(exc)

    tools_used = [
        {"name": tc.name, "args": tc.args, "result_summary": tc.result_summary}
        for tc in answer.tool_calls
    ]

    now = datetime.utcnow()
    # Rilettura che bypassa davvero l'identity map (`populate_existing` + SELECT,
    # non `session.get`): se la sessione e' stata cancellata da un'altra richiesta
    # mentre il provider rispondeva, un oggetto ORM ancora vivo nella identity map
    # farebbe credere che esista (poi 500 al flush). Comportamento approvato al CP1:
    # nessun errore, la risposta finisce in una NUOVA sessione.
    chat = None
    if body.session_id is not None:
        chat = session.scalars(
            select(ChatSession)
            .where(ChatSession.id == body.session_id)
            .execution_options(populate_existing=True)
        ).one_or_none()
    if chat is None:
        title = body.question.strip()
        if len(title) > _TITLE_MAX:
            title = title[:_TITLE_MAX] + "…"
        chat = ChatSession(title=title, created_at=now, updated_at=now)
        session.add(chat)
        session.flush()
    session.add(
        ChatMessage(
            session_id=chat.id, role="user", content=body.question,
            tools_json=None, truncated=False, created_at=now,
        )
    )
    session.add(
        ChatMessage(
            session_id=chat.id, role="assistant", content=answer.text,
            tools_json=json.dumps(tools_used), truncated=answer.truncated,
            created_at=now + timedelta(microseconds=1),
        )
    )
    chat.updated_at = now + timedelta(microseconds=1)
    session.commit()

    return {
        "answer": answer.text,
        "tools_used": tools_used,
        "truncated": answer.truncated,
        "session_id": chat.id,
    }


@router.get("/ai/sessions")
def list_sessions(session: Session = Depends(get_session)):
    counts = (
        select(ChatMessage.session_id, func.count().label("n"))
        .group_by(ChatMessage.session_id)
        .subquery()
    )
    rows = session.execute(
        select(ChatSession, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.session_id == ChatSession.id)
        .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
    ).all()
    return {
        "sessions": [
            {
                "id": c.id,
                "title": c.title,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
                "message_count": n,
            }
            for c, n in rows
        ]
    }


@router.get("/ai/sessions/{session_id}")
def get_chat_session(session_id: int, session: Session = Depends(get_session)):
    chat = session.get(ChatSession, session_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Conversazione non trovata.")
    rows = session.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at, ChatMessage.id)
    ).all()
    return {
        "id": chat.id,
        "title": chat.title,
        "created_at": chat.created_at.isoformat(),
        "updated_at": chat.updated_at.isoformat(),
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "tools_used": json.loads(m.tools_json) if m.tools_json is not None else None,
                "truncated": m.truncated,
                "created_at": m.created_at.isoformat(),
            }
            for m in rows
        ],
    }


@router.delete("/ai/sessions/{session_id}", status_code=204)
def delete_chat_session(session_id: int, session: Session = Depends(get_session)):
    if session.get(ChatSession, session_id) is None:
        raise HTTPException(status_code=404, detail="Conversazione non trovata.")
    session.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
    session.execute(delete(ChatSession).where(ChatSession.id == session_id))
    session.commit()
    return Response(status_code=204)


class DeleteAllRequest(BaseModel):
    confirm: bool = False


@router.delete("/ai/sessions")
def delete_all_sessions(
    body: DeleteAllRequest | None = Body(default=None),
    session: Session = Depends(get_session),
):
    if body is None or body.confirm is not True:
        raise HTTPException(
            status_code=400,
            detail="Azzera storico richiede 'confirm: true' (operazione distruttiva, ADR-0032).",
        )
    deleted_messages = session.execute(delete(ChatMessage)).rowcount
    deleted_sessions = session.execute(delete(ChatSession)).rowcount
    session.commit()
    return {"deleted_sessions": deleted_sessions, "deleted_messages": deleted_messages}
