"""Test per `app/routers/ai.py` — endpoint `POST /ai/query` (F6, ADR-0023).

Unico mock ammesso: `AIProvider` (ADR-0018 p.7). Qui iniettiamo un `AIProvider`
fake deterministico via `dependency_overrides` (mai il client Gemini reale, mai
rete) — il DB resta reale (SQLite in-memory di test), stesso pattern di
`test_insights.py`. Il fake vive in questo file, non in `app/ai/provider.py`
(quel modulo ha gia' il proprio `_FakeProvider` di contratto in
`test_ai_provider.py`; qui serve un fake diverso per riga di test, non un
singolo fake condiviso)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ai.provider import AIAnswer, AIProvider, AIProviderError, AIProviderNotConfigured, ToolCall
from app.db import Base, get_session
from app.routers import ai as ai_router


def _build_test_app(fake_provider: AIProvider | None = None):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    # StaticPool: stesso motivo di test_insights.py — un'unica connessione
    # in-memory condivisa fra il thread di test e il thread pool di FastAPI.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    def override_get_session():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    app.include_router(ai_router.router)
    app.dependency_overrides[get_session] = override_get_session
    if fake_provider is not None:
        app.dependency_overrides[ai_router.get_ai_provider] = lambda: fake_provider
    return TestClient(app)


class _HappyProvider(AIProvider):
    def answer(self, question: str, session) -> AIAnswer:
        return AIAnswer(
            text=f"risposta a: {question}",
            tool_calls=[ToolCall(name="get_accounts", args={}, result_summary="2 conti")],
            truncated=False,
        )


class _NotConfiguredProvider(AIProvider):
    def answer(self, question: str, session) -> AIAnswer:
        raise AIProviderNotConfigured("AI_PROVIDER non configurato")


class _RuntimeErrorProvider(AIProvider):
    def answer(self, question: str, session) -> AIAnswer:
        raise AIProviderError("timeout simulato verso il provider")


# --- 200: risposta popolata, tool_calls tracciati -------------------------------


def test_query_returns_200_with_answer_and_tools_used():
    client = _build_test_app(fake_provider=_HappyProvider())

    resp = client.post("/ai/query", json={"question": "quanti conti ho?"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "risposta a: quanti conti ho?"
    assert body["truncated"] is False
    assert body["tools_used"] == [{"name": "get_accounts", "args": {}, "result_summary": "2 conti"}]


def test_query_propagates_truncated_flag():
    class _TruncatedProvider(AIProvider):
        def answer(self, question: str, session) -> AIAnswer:
            return AIAnswer(text="parziale", tool_calls=[], truncated=True)

    client = _build_test_app(fake_provider=_TruncatedProvider())

    resp = client.post("/ai/query", json={"question": "domanda lunga"})

    assert resp.status_code == 200
    assert resp.json()["truncated"] is True


# --- 400: provider non configurato, messaggio esplicito -------------------------


def test_query_returns_400_when_provider_not_configured():
    client = _build_test_app(fake_provider=_NotConfiguredProvider())

    resp = client.post("/ai/query", json={"question": "quanto ho speso?"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == (
        "layer AI non configurato: imposta AI_PROVIDER, AI_API_KEY, AI_MODEL in .env"
    )


def test_query_returns_400_when_real_get_ai_provider_dependency_is_unconfigured(monkeypatch):
    # Nessun override di get_ai_provider qui: esercita il vero dispatch
    # (app.ai.provider.get_provider(), chiamato dalla dependency reale del router)
    # con AI_PROVIDER vuoto — copre il percorso di produzione reale, non solo il
    # fake iniettato nei test sopra (quel ramo altrimenti resterebbe non testato).
    import app.ai.provider as provider_module

    monkeypatch.setattr(provider_module.settings, "ai_provider", "")
    client = _build_test_app(fake_provider=None)

    resp = client.post("/ai/query", json={"question": "quanto ho speso?"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == (
        "layer AI non configurato: imposta AI_PROVIDER, AI_API_KEY, AI_MODEL in .env"
    )


# --- 502: errore runtime del provider --------------------------------------------


def test_query_returns_502_when_provider_raises_runtime_error():
    client = _build_test_app(fake_provider=_RuntimeErrorProvider())

    resp = client.post("/ai/query", json={"question": "quanto ho speso?"})

    assert resp.status_code == 502
    assert "timeout simulato" in resp.json()["detail"]


# --- 422: domanda vuota / solo whitespace ----------------------------------------


def test_query_returns_422_for_empty_question():
    client = _build_test_app(fake_provider=_HappyProvider())

    resp = client.post("/ai/query", json={"question": ""})

    assert resp.status_code == 422


def test_query_returns_422_for_whitespace_only_question():
    client = _build_test_app(fake_provider=_HappyProvider())

    resp = client.post("/ai/query", json={"question": "   "})

    assert resp.status_code == 422


def test_query_returns_422_when_question_field_missing():
    client = _build_test_app(fake_provider=_HappyProvider())

    resp = client.post("/ai/query", json={})

    assert resp.status_code == 422


# --- ordine di montaggio: la route non deve cadere nel catch-all SPA ------------


def test_ai_query_route_is_registered_before_spa_catchall_in_real_app():
    # Verifica DIRETTA sulla route table dell'app reale assemblata da
    # app.main (stesso ordine di registrazione di produzione), senza fare
    # nessuna richiesta HTTP — cosi' non dipende da quale ramo di main.py e'
    # attivo in questo processo (con o senza frontend_dist buildato) e non
    # rischia mai di innescare una chiamata di rete reale se un giorno questo
    # processo girasse con una chiave AI vera configurata.
    #
    # Regressione reale scoperta in E2E Docker (frontend_dist presente,
    # quindi il catch-all `GET /{full_path:path}` e' registrato): una prima
    # versione di questo test faceva `GET /ai/query` e assumeva 405 (Method
    # Not Allowed) come prova che il path fosse in tabella per POST. Ma
    # quando il catch-all esiste, una GET su QUALSIASI path da' 200 (serve
    # index.html, comportamento F5 corretto e voluto per il client-side
    # routing) — non 405. L'assunzione 405 valeva solo nell'ambiente locale
    # senza frontend_dist, dove il catch-all non e' mai registrato. La vera
    # garanzia richiesta da ADR-0021 e' sull'ORDINE di registrazione, non su
    # un particolare status HTTP osservabile dall'esterno (che cambia a
    # seconda di quale ramo di main.py e' attivo) — quindi va verificata
    # ispezionando `app.routes` direttamente, unico modo che funziona
    # identico in entrambi gli ambienti (con e senza frontend_dist).
    from app.main import app as real_app

    routes = real_app.routes
    ai_indexes = [i for i, r in enumerate(routes) if getattr(r, "path", None) == "/ai/query"]
    assert ai_indexes, "POST /ai/query non registrata nell'app reale"

    catchall_indexes = [i for i, r in enumerate(routes) if getattr(r, "path", None) == "/{full_path:path}"]
    if catchall_indexes:  # presente solo se frontend_dist esiste (build di produzione/Docker)
        assert ai_indexes[0] < min(catchall_indexes)
