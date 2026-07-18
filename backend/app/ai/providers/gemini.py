"""Adapter Gemini per `AIProvider` (F6, ADR-0023 p.2/p.7).

SDK `google-genai` (`from google import genai`), **Interactions API**
(`client.interactions.create()`), function calling a **loop manuale**: il modello
non esegue nulla, questo modulo intercetta gli step `function_call`, li esegue
localmente via `app.ai.tools.TOOLS` (registry read-only, Task 2) e rimanda uno
step `function_result` con `name`/`call_id` propagato identico e `result`.

Forma verificata contro l'SDK installato in data 2026-07-18 (vedi report Task 3):
`client.interactions` espone `.create(model, input, tools, system_instruction,
previous_interaction_id, timeout, ...) -> Interaction`; `Interaction` ha `.id`,
`.output_text`, `.steps`; uno step `function_call` ha `.type == "function_call"`,
`.name`, `.arguments` (dict), `.id`. Se una futura versione dell'SDK diverge da
questa forma, il loop qui sotto fallira' in modo esplicito (AttributeError
incapsulato in AIProviderError) — non silenziosamente.

Nessun import del SDK a livello di modulo (import lazy in `_build_default_client`):
il modulo resta importabile, e l'app non crasha, anche se `google-genai` non e'
installato o non configurato (ADR-0018 p.3)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable

from app.ai.provider import AIAnswer, AIProvider, AIProviderError, AIProviderNotConfigured, ToolCall
from app.ai.tools import TOOLS, tool_declarations
from app.config import settings

SYSTEM_PROMPT = (
    "Sei un assistente per l'analisi delle finanze personali dell'utente. Rispondi "
    "esclusivamente sulla base dei risultati restituiti dai tool a disposizione: non "
    "inventare mai numeri, transazioni o categorie che non provengono da un tool. "
    "Quando la domanda riguarda totali, andamenti o somme, usa sempre il tool "
    "'get_insights' (aggregazione calcolata dal database) invece di sommare a mano le "
    "righe grezze restituite da 'list_transactions': i modelli linguistici sbagliano "
    "l'aritmetica, il database no. Se un risultato di 'list_transactions' ha il campo "
    "'truncated' a true, stai vedendo solo un sottoinsieme: restringi i filtri o "
    "segnalalo esplicitamente all'utente, non rispondere come se fosse il totale. "
    "Rispondi sempre nella stessa lingua in cui e' formulata la domanda dell'utente."
)


def _date_fields_by_tool() -> dict[str, set[str]]:
    """Deriva dai JSON-schema di `tool_declarations()` quali parametri sono date
    (`format: "date"`): il modello li restituisce come stringa ISO, i tool si
    aspettano `datetime` (vedi `app/ai/tools.py`). Nessuna lista di nomi campo
    duplicata a mano qui: se un tool aggiunge/rimuove un campo data, questa
    funzione lo scopre dalla stessa dichiarazione che il modello vede."""
    fields_by_tool: dict[str, set[str]] = {}
    for decl in tool_declarations():
        properties = decl["parameters"]["properties"]
        fields_by_tool[decl["name"]] = {
            key for key, schema in properties.items() if schema.get("format") == "date"
        }
    return fields_by_tool


def _summarize_result(result: Any) -> str:
    """Riassunto breve e leggibile del risultato di un tool, per la traccia UI
    (ADR-0023 p.11: i numeri devono restare ricontrollabili)."""
    if isinstance(result, dict) and "rows" in result and "returned" in result:
        note = " (troncato)" if result.get("truncated") else ""
        return f"{result['returned']}/{result.get('total_matching', result['returned'])} righe{note}"
    if isinstance(result, list):
        return f"{len(result)} elementi"
    if isinstance(result, dict):
        keys = ", ".join(list(result.keys())[:5])
        return f"{len(result)} campi ({keys})"
    return str(result)[:200]


class GeminiProvider(AIProvider):
    MAX_ITERATIONS = 5
    REQUEST_TIMEOUT_SECONDS = 30

    def __init__(self, client_factory: Callable[[], Any] | None = None):
        # Validazione config specifica di questo adapter (AI_PROVIDER e' gia'
        # verificato da get_provider() prima di arrivare qui, ma questo
        # costruttore resta la fonte di verita' se istanziato direttamente).
        if not settings.ai_api_key or not settings.ai_model:
            raise AIProviderNotConfigured("AI_API_KEY o AI_MODEL non configurati per il provider 'gemini'")
        self._model = settings.ai_model
        # Seam per i test (Task 3 design note): un fake client puo' essere
        # iniettato senza toccare la logica del loop, che resta quella vera.
        self._client_factory = client_factory or self._build_default_client
        self._date_fields = _date_fields_by_tool()

    @staticmethod
    def _build_default_client():
        from google import genai  # import lazy, mai a livello di modulo

        return genai.Client(api_key=settings.ai_api_key)

    def answer(self, question: str, session) -> AIAnswer:
        client = self._client_factory()
        gemini_tools = [{"type": "function", **decl} for decl in tool_declarations()]

        tool_calls: list[ToolCall] = []
        current_input: Any = question
        previous_interaction_id: str | None = None
        last_text = ""

        for iteration in range(1, self.MAX_ITERATIONS + 1):
            create_kwargs: dict[str, Any] = {
                "model": self._model,
                "input": current_input,
                "tools": gemini_tools,
                "system_instruction": SYSTEM_PROMPT,
                "timeout": self.REQUEST_TIMEOUT_SECONDS,
            }
            if previous_interaction_id is not None:
                create_kwargs["previous_interaction_id"] = previous_interaction_id

            try:
                interaction = client.interactions.create(**create_kwargs)
            except Exception as exc:  # noqa: BLE001 - qualunque errore SDK/HTTP diventa un errore di dominio
                raise AIProviderError(f"chiamata al provider Gemini fallita: {exc}") from exc

            output_text = getattr(interaction, "output_text", None)
            if output_text:
                last_text = output_text
            steps = getattr(interaction, "steps", None) or []
            function_call_steps = [step for step in steps if getattr(step, "type", None) == "function_call"]

            if not function_call_steps:
                return AIAnswer(text=last_text, tool_calls=tool_calls, truncated=False)

            function_result_input: list[dict] = []
            for step in function_call_steps:
                name = step.name
                call_id = step.id
                raw_args = dict(step.arguments or {})
                result, result_summary = self._execute_tool(name, raw_args, session)
                tool_calls.append(ToolCall(name=name, args=raw_args, result_summary=result_summary))
                function_result_input.append(
                    {
                        "type": "function_result",
                        "name": name,
                        "call_id": call_id,
                        "result": [{"type": "text", "text": json.dumps(result, default=str)}],
                    }
                )

            if iteration == self.MAX_ITERATIONS:
                # Cap raggiunto: risposta migliore disponibile, mai un ciclo aperto
                # (decisione utente, MAX_ITERATIONS = 5; ADR-0023 p.7).
                return AIAnswer(text=last_text, tool_calls=tool_calls, truncated=True)

            current_input = function_result_input
            previous_interaction_id = getattr(interaction, "id", None)

        # Irraggiungibile (il ramo `iteration == MAX_ITERATIONS` sopra ritorna
        # sempre prima che il for esca naturalmente) — difesa in profondita' contro
        # un futuro refactor che spezzasse il cap in modo silenzioso.
        return AIAnswer(text=last_text, tool_calls=tool_calls, truncated=True)

    def _execute_tool(self, name: str, raw_args: dict, session) -> tuple[Any, str]:
        if name not in TOOLS:
            error = {"error": f"tool sconosciuto: {name}"}
            return error, f"errore: tool sconosciuto '{name}'"
        fn = TOOLS[name]
        call_args = self._coerce_args(name, raw_args)
        try:
            result = fn(session, **call_args)
        except Exception as exc:  # noqa: BLE001 - un tool che fallisce non deve interrompere il loop
            return {"error": str(exc)}, f"errore: {exc}"
        return result, _summarize_result(result)

    def _coerce_args(self, name: str, raw_args: dict) -> dict:
        """Converte gli argomenti JSON del modello nei tipi Python attesi dal
        tool: solo le date (stringa ISO -> `datetime`, guidato dallo schema, vedi
        `_date_fields_by_tool`). Il resto (str/number/bool) passa invariato: i
        nomi dei kwarg combaciano gia' esattamente con lo schema (Task 2)."""
        date_fields = self._date_fields.get(name, set())
        coerced: dict[str, Any] = {}
        for key, value in raw_args.items():
            if key in date_fields and isinstance(value, str):
                coerced[key] = datetime.fromisoformat(value)
            else:
                coerced[key] = value
        return coerced
