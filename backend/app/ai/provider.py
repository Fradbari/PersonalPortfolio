"""Interfaccia astratta `AIProvider` + dispatch `get_provider()` (F6, ADR-0023 p.2).

Un solo adapter concreto oggi (`app.ai.providers.gemini.GeminiProvider`).
Anthropic/OpenAI: interfaccia pronta, non implementati (ADR-0023 p.2) — nessun
`elif` per loro qui finche' non esistono davvero (YAGNI).

Nessun import del SDK di alcun provider a livello di modulo: questo file resta
importabile (e l'app non crasha, ADR-0018 p.3) anche se `google-genai` non e'
installato — l'import vero e proprio e' lazy, dentro l'adapter concreto."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.config import settings


@dataclass
class ToolCall:
    """Una chiamata tool eseguita durante il loop — mostrata sempre in UI accanto
    alla risposta (ADR-0023 p.11): i numeri restano ricontrollabili."""

    name: str
    args: dict
    result_summary: str


@dataclass
class AIAnswer:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    truncated: bool = False


class AIProviderError(Exception):
    """Errore runtime del provider (chiamata HTTP fallita, risposta inattesa,
    timeout, ...). Il router (Task 4) lo mappa a 502."""


class AIProviderNotConfigured(AIProviderError):
    """Config assente o incompleta: `AI_PROVIDER`/`AI_API_KEY`/`AI_MODEL` vuoti, o
    `AI_PROVIDER` non riconosciuto. Il router (Task 4) lo mappa a 400 — mai un
    crash dell'app (ADR-0018 p.3, ADR-0023 p.8)."""


class AIProvider(ABC):
    @abstractmethod
    def answer(self, question: str, session) -> AIAnswer:
        """Risponde alla domanda in linguaggio naturale usando solo i tool
        read-only del registry (`app.ai.tools`). Stateless: nessuna memoria tra
        chiamate (ADR-0023 p.6)."""
        ...


def get_provider() -> AIProvider:
    """Dispatch su `settings.ai_provider`. Oggi supporta solo `"gemini"`.

    Vuoto -> `AIProviderNotConfigured`. Valore non riconosciuto -> anch'esso
    `AIProviderNotConfigured` (e' comunque un problema di configurazione, non un
    fallimento a runtime di un provider che si e' correttamente avviato — quindi
    4xx, non 502, coerente con ADR-0023 p.8). La validazione di `AI_API_KEY`/
    `AI_MODEL` vive nel costruttore dell'adapter concreto (Task 3, ognuno ha i
    propri requisiti di config)."""
    provider_name = settings.ai_provider
    if not provider_name:
        raise AIProviderNotConfigured("AI_PROVIDER non configurato")
    if provider_name == "gemini":
        from app.ai.providers.gemini import GeminiProvider

        return GeminiProvider()
    raise AIProviderNotConfigured(f"AI_PROVIDER sconosciuto: {provider_name!r}")
