"""Test per `app/ai/provider.py` + `app/ai/providers/gemini.py` (F6, ADR-0023).

Nessuna rete, nessun client Gemini reale. L'unico mock ammesso in questa fase e'
l'adapter/il client esterno del provider (ADR-0018 p.7, richiamato da ADR-0023
p.12): qui si fake-a il client `google-genai` sottostante (un `types.SimpleNamespace`
che imita la forma di `client.interactions.create()`) per esercitare il loop
manuale del vero `GeminiProvider.answer()` senza rete — mai il DB, mai il tool
registry (quelli restano testati su DB reale, vedi test_ai_tools.py)."""
from __future__ import annotations

import inspect
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.ai.provider as provider_module
import app.ai.providers.gemini as gemini_module
from app.ai.provider import AIAnswer, AIProvider, AIProviderError, AIProviderNotConfigured, ToolCall, get_provider
from app.ai.providers.gemini import GeminiProvider
from app.db import Base
from app.models import Account


def _build_test_session():
    # Stesso pattern di test_ai_tools.py: SQLite in-memory, connessione unica condivisa.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    return Session


# --- get_provider(): config assente/ignota -> errore esplicito, mai un crash ----


def test_get_provider_raises_when_ai_provider_empty(monkeypatch):
    monkeypatch.setattr(provider_module.settings, "ai_provider", "")
    monkeypatch.setattr(provider_module.settings, "ai_api_key", "key")
    monkeypatch.setattr(provider_module.settings, "ai_model", "gemini-3.1-flash-lite")

    with pytest.raises(AIProviderNotConfigured):
        get_provider()


def test_get_provider_raises_when_ai_api_key_empty(monkeypatch):
    monkeypatch.setattr(provider_module.settings, "ai_provider", "gemini")
    monkeypatch.setattr(provider_module.settings, "ai_api_key", "")
    monkeypatch.setattr(provider_module.settings, "ai_model", "gemini-3.1-flash-lite")

    with pytest.raises(AIProviderNotConfigured):
        get_provider()


def test_get_provider_raises_when_ai_model_empty(monkeypatch):
    monkeypatch.setattr(provider_module.settings, "ai_provider", "gemini")
    monkeypatch.setattr(provider_module.settings, "ai_api_key", "key")
    monkeypatch.setattr(provider_module.settings, "ai_model", "")

    with pytest.raises(AIProviderNotConfigured):
        get_provider()


def test_get_provider_raises_explicit_error_for_unknown_provider(monkeypatch):
    monkeypatch.setattr(provider_module.settings, "ai_provider", "not-a-real-provider")
    monkeypatch.setattr(provider_module.settings, "ai_api_key", "key")
    monkeypatch.setattr(provider_module.settings, "ai_model", "gemini-3.1-flash-lite")

    with pytest.raises(AIProviderError) as excinfo:
        get_provider()
    assert "not-a-real-provider" in str(excinfo.value)


def test_get_provider_returns_gemini_provider_when_configured(monkeypatch):
    monkeypatch.setattr(provider_module.settings, "ai_provider", "gemini")
    monkeypatch.setattr(provider_module.settings, "ai_api_key", "key")
    monkeypatch.setattr(provider_module.settings, "ai_model", "gemini-3.1-flash-lite")

    result = get_provider()

    assert isinstance(result, GeminiProvider)
    assert isinstance(result, AIProvider)


def test_gemini_provider_direct_construction_also_validates_config(monkeypatch):
    # Il contratto vale anche istanziando l'adapter direttamente, non solo via
    # get_provider() (nessuna via per bypassare il guardrail di configurazione).
    monkeypatch.setattr(gemini_module.settings, "ai_api_key", "")
    monkeypatch.setattr(gemini_module.settings, "ai_model", "gemini-3.1-flash-lite")

    with pytest.raises(AIProviderNotConfigured):
        GeminiProvider()


# --- contratto AIAnswer/ToolCall, rispettato da un fake AIProvider --------------


class _FakeProvider(AIProvider):
    def answer(self, question: str, session) -> AIAnswer:
        return AIAnswer(
            text="risposta finta",
            tool_calls=[ToolCall(name="get_accounts", args={}, result_summary="2 conti")],
            truncated=False,
        )


def test_fake_ai_provider_respects_the_answer_contract():
    fake = _FakeProvider()

    result = fake.answer("quanti conti ho?", session=None)

    assert isinstance(result, AIAnswer)
    assert result.text == "risposta finta"
    assert result.tool_calls == [ToolCall(name="get_accounts", args={}, result_summary="2 conti")]
    assert result.truncated is False


# --- GeminiProvider.answer(): loop manuale su un client Gemini fake -------------


def _configure_valid_settings(monkeypatch):
    monkeypatch.setattr(gemini_module.settings, "ai_api_key", "test-key")
    monkeypatch.setattr(gemini_module.settings, "ai_model", "gemini-3.1-flash-lite")


class _FakeInteractions:
    """Fake di `client.interactions` — imita solo la forma usata dal loop
    (`.create(**kwargs) -> oggetto con .id/.output_text/.steps`)."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        current = self._responses[0]
        if callable(current):
            # factory riusabile all'infinito (usata per il test del cap iterazioni):
            # mai "consumata" dalla lista, cosi' puo' rispondere per sempre.
            return current(kwargs)
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


class _FakeClient:
    def __init__(self, responses):
        self.interactions = _FakeInteractions(responses)


def _text_interaction(text: str, interaction_id: str = "interaction-1"):
    return SimpleNamespace(id=interaction_id, output_text=text, steps=[])


def _function_call_interaction(name: str, arguments: dict, call_id: str = "call-1", interaction_id: str = "interaction-1"):
    step = SimpleNamespace(type="function_call", name=name, arguments=arguments, id=call_id)
    return SimpleNamespace(id=interaction_id, output_text="", steps=[step])


def test_gemini_provider_answer_returns_text_when_model_needs_no_tool(monkeypatch):
    _configure_valid_settings(monkeypatch)
    fake_client = _FakeClient([_text_interaction("non hai bisogno di alcun tool per questo")])
    fake_provider = GeminiProvider(client_factory=lambda: fake_client)

    result = fake_provider.answer("ciao", session=None)

    assert result.text == "non hai bisogno di alcun tool per questo"
    assert result.tool_calls == []
    assert result.truncated is False
    assert len(fake_client.interactions.calls) == 1
    first_call = fake_client.interactions.calls[0]
    assert first_call["model"] == "gemini-3.1-flash-lite"
    assert first_call["input"] == "ciao"
    assert "previous_interaction_id" not in first_call
    assert first_call["tools"]  # dichiarazioni tool passate al provider
    assert first_call["system_instruction"]  # system prompt presente


def test_gemini_provider_answer_executes_tool_and_returns_final_text(monkeypatch):
    _configure_valid_settings(monkeypatch)
    Session = _build_test_session()
    with Session() as session:
        session.add(Account(name="principale", display_name=None))
        session.commit()

    responses = [
        _function_call_interaction("get_accounts", {}, call_id="call-1", interaction_id="interaction-1"),
        _text_interaction("hai un conto: principale", interaction_id="interaction-2"),
    ]
    fake_client = _FakeClient(responses)
    fake_provider = GeminiProvider(client_factory=lambda: fake_client)

    with Session() as session:
        result = fake_provider.answer("quanti conti ho?", session)

    assert result.text == "hai un conto: principale"
    assert result.truncated is False
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "get_accounts"
    assert "principale" in result.tool_calls[0].result_summary or "1" in result.tool_calls[0].result_summary

    calls = fake_client.interactions.calls
    assert len(calls) == 2
    # la seconda chiamata rimanda il risultato del tool con previous_interaction_id propagato
    assert calls[1]["previous_interaction_id"] == "interaction-1"
    second_input = calls[1]["input"]
    assert isinstance(second_input, list)
    assert second_input[0]["type"] == "function_result"
    assert second_input[0]["call_id"] == "call-1"
    assert second_input[0]["name"] == "get_accounts"


def test_gemini_provider_answer_coerces_date_string_args_to_datetime(monkeypatch):
    # I parametri con formato JSON-schema "date" arrivano dal modello come stringa
    # ISO; i tool si aspettano `datetime` (vedi app/ai/tools.py). Verifica che
    # l'adapter faccia la conversione prima di invocare il tool.
    _configure_valid_settings(monkeypatch)
    Session = _build_test_session()

    captured_args: dict = {}

    import app.ai.providers.gemini as gm

    original_tools = gm.TOOLS

    def _spy_list_transactions(session, **kwargs):
        captured_args.update(kwargs)
        return original_tools["list_transactions"](session, **kwargs)

    monkeypatch.setitem(gm.TOOLS, "list_transactions", _spy_list_transactions)

    responses = [
        _function_call_interaction(
            "list_transactions", {"date_from": "2026-01-01", "date_to": "2026-01-31"}, call_id="call-1"
        ),
        _text_interaction("nessuna transazione trovata"),
    ]
    fake_client = _FakeClient(responses)
    fake_provider = GeminiProvider(client_factory=lambda: fake_client)

    with Session() as session:
        fake_provider.answer("quanto ho speso a gennaio?", session)

    assert isinstance(captured_args["date_from"], datetime)
    assert captured_args["date_from"] == datetime(2026, 1, 1)
    assert isinstance(captured_args["date_to"], datetime)
    assert captured_args["date_to"] == datetime(2026, 1, 31)


def test_gemini_provider_answer_hits_iteration_cap_and_marks_truncated(monkeypatch):
    # Fake che chiede un tool all'infinito: mai testato sul client Gemini reale
    # (nessuna rete), verifica solo che il loop del vero GeminiProvider si fermi.
    _configure_valid_settings(monkeypatch)
    Session = _build_test_session()

    def _always_function_call(_kwargs):
        return _function_call_interaction("get_accounts", {})

    fake_client = _FakeClient([_always_function_call])
    fake_provider = GeminiProvider(client_factory=lambda: fake_client)

    with Session() as session:
        result = fake_provider.answer("domanda senza fine", session)

    assert result.truncated is True
    assert len(fake_client.interactions.calls) == GeminiProvider.MAX_ITERATIONS
    assert len(result.tool_calls) == GeminiProvider.MAX_ITERATIONS


def test_gemini_provider_wraps_transport_errors_as_provider_error(monkeypatch):
    _configure_valid_settings(monkeypatch)

    class _BrokenInteractions:
        def create(self, **kwargs):
            raise ConnectionError("timeout simulato")

    class _BrokenClient:
        def __init__(self):
            self.interactions = _BrokenInteractions()

    fake_provider = GeminiProvider(client_factory=lambda: _BrokenClient())

    with pytest.raises(AIProviderError):
        fake_provider.answer("ciao", session=None)


def test_gemini_provider_malformed_step_becomes_provider_error_not_raw_attribute_error(monkeypatch):
    # Regressione (review Task 3): uno step di forma inattesa (es. un futuro
    # drift dell'SDK che rimuove/rinomina un campo) deve diventare
    # AIProviderError, mai un AttributeError/TypeError grezzo propagato fuori
    # da answer() — la docstring del modulo promette esplicitamente questo.
    _configure_valid_settings(monkeypatch)

    malformed_step = SimpleNamespace(type="function_call", name="get_accounts")  # niente .id / .arguments
    malformed_interaction = SimpleNamespace(id="interaction-1", output_text="", steps=[malformed_step])
    fake_client = _FakeClient([malformed_interaction])
    fake_provider = GeminiProvider(client_factory=lambda: fake_client)

    with pytest.raises(AIProviderError):
        fake_provider.answer("ciao", session=None)


def test_gemini_provider_unknown_tool_name_reported_as_error_not_a_crash(monkeypatch):
    _configure_valid_settings(monkeypatch)

    responses = [
        _function_call_interaction("tool_che_non_esiste", {}, call_id="call-1"),
        _text_interaction("gestito senza crash"),
    ]
    fake_client = _FakeClient(responses)
    fake_provider = GeminiProvider(client_factory=lambda: fake_client)

    result = fake_provider.answer("ciao", session=None)

    assert result.text == "gestito senza crash"
    assert result.tool_calls[0].name == "tool_che_non_esiste"
    assert "errore" in result.tool_calls[0].result_summary.lower()


# --- niente import del SDK a livello di modulo (import lazy) --------------------


def test_gemini_module_does_not_import_sdk_at_module_level():
    # Solo statement `import`/`from` veri e propri a colonna zero, non
    # occorrenze del testo dentro docstring/commenti (che lo citano di proposito
    # per documentare la forma dell'SDK verificata).
    source = inspect.getsource(gemini_module)
    top_level_import_lines = [
        line for line in source.splitlines() if line.startswith(("import ", "from "))
    ]
    for line in top_level_import_lines:
        assert "google" not in line, f"import del SDK trovato a livello di modulo: {line!r}"


def test_max_iterations_is_five():
    assert GeminiProvider.MAX_ITERATIONS == 5
