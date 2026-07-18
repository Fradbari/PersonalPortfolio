"""`/ai` — `POST /ai/query`, domanda in linguaggio naturale sola lettura sui
propri dati finanziari (F6, ADR-0023). Stateless: nessuna memoria fra chiamate
(ADR-0023 p.6), ogni richiesta e' indipendente.

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

from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.ai.provider import AIProvider, AIProviderError, AIProviderNotConfigured, get_provider
from app.db import get_session

router = APIRouter(tags=["ai"])

_NOT_CONFIGURED_MESSAGE = "layer AI non configurato: imposta AI_PROVIDER, AI_API_KEY, AI_MODEL in .env"


def _raise_http_for(exc: AIProviderError) -> NoReturn:
    if isinstance(exc, AIProviderNotConfigured):
        raise HTTPException(status_code=400, detail=_NOT_CONFIGURED_MESSAGE) from exc
    raise HTTPException(status_code=502, detail=str(exc)) from exc


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
    try:
        answer = provider.answer(body.question, session)
    except AIProviderError as exc:
        _raise_http_for(exc)

    return {
        "answer": answer.text,
        "tools_used": [
            {"name": tc.name, "args": tc.args, "result_summary": tc.result_summary}
            for tc in answer.tool_calls
        ],
        "truncated": answer.truncated,
    }
