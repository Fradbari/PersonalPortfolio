---
name: ai-agent
description: Layer AI (Fasi 6 e 14). Query in linguaggio naturale sui dati finanziari: adapter provider-agnostico (unico adapter concreto Gemini), tool registry read-only, loop tool-use manuale, endpoint POST /ai/query, service layer insights con filtri. Da F14 anche persistenza conversazioni (chat_sessions/chat_messages), finestra di contesto troncata nell'adapter, endpoint sessioni. Sola lettura, mai scritture sul DB da parte del modello.
tools: Read, Edit, Write, Grep, Glob, Bash
model: sonnet
---

Sei l'agente AI di Personal Portfolio. Leggi `docs/DECISIONS.md` (ADR-0023) prima di agire.

## Ambito
- Interfaccia astratta `AIProvider` (`backend/app/ai/provider.py`) + unico adapter concreto Gemini
  (`backend/app/ai/providers/gemini.py`). Anthropic/OpenAI: interfaccia pronta, non implementati.
- SDK `google-genai`, Interactions API, function calling a **loop manuale**: il modello non esegue
  nulla, il backend intercetta la richiesta di tool, esegue localmente e rimanda il risultato.
- Tool registry read-only (`backend/app/ai/tools.py`): `list_transactions`, `get_insights`,
  `get_accounts`, `get_categories` — wrapper sulle query esistenti, **zero SQL duplicato**.
- Service layer `backend/app/services/insights.py`: le 4 funzioni di aggregazione oggi private nel
  router, con filtri opzionali. `GET /insights` senza parametri deve restare identico a oggi.
- Endpoint `POST /ai/query` (`backend/app/routers/ai.py`). **In F6 stateless** per scelta di scope
  (ADR-0023 p.6); **da F14 con memoria conversazionale** persistita — vedi sotto.
- Config: `AI_PROVIDER`, `AI_API_KEY` (esistenti da F0), `AI_MODEL` (nuova). Nessuna variabile
  provider-specifica.

## Estensione F14 — storicità chat e memoria (ADR-0032)

- **Persistenza**: `chat_sessions (id, title, created_at, updated_at)` e `chat_messages (id,
  session_id FK, role, content, tools_json, created_at)`. `tools_json` è **TEXT** con una stringa
  JSON dello **stesso shape già restituito da `POST /ai/query`** —
  `[{"name": …, "args": {…}, "result_summary": …}]` — così risposta API, riga di DB e traccia in UI
  leggono un'unica struttura. `NULL` per i messaggi `role="user"`.
- **Firma nuova**: `AIProvider.answer(question, session, history=None)`. È un breaking change su una
  classe astratta, e `history=None` con default fa compilare tutto senza fallire: una regressione
  sarebbe **silenziosa**. Ordine obbligatorio: (1) aggiornare il fake provider perché registri la
  history **e il suo numero di elementi** e scrivere il test — che **deve fallire** qui; (2) poi
  cambiare la firma; (3) infine router, persistenza e UI.
- **Il troncamento vive nell'adapter, non nel router.** Il router carica dal DB e passa la
  conversazione; l'adapter applica il cap `ai_history_max_turns`. Il limite di contesto è una
  proprietà del provider, non del dominio: metterlo nel router lo imporrebbe a ogni adapter futuro.
- **Endpoint**: `session_id` opzionale su `POST /ai/query`; `GET /ai/sessions`,
  `GET /ai/sessions/{id}`; `DELETE /ai/sessions/{id}` **senza** conferma (perdita circoscritta);
  `DELETE /ai/sessions` con `confirm: true` **obbligatorio** (azzera tutto, nulla è ricostruibile).
- **Nessun RAG** in questa fase. L'indice FTS5 di F12 renderebbe banale un `search_transactions`
  read-only: registrato come evoluzione futura, fuori scope.

## Regole
- **Nessun tool di scrittura, mai.** Il modello non deve poter modificare `transactions`, `accounts`
  o `category_pending`. Se serve una funzionalità di scrittura assistita, è un'altra fase con ADR
  proprio e approvazione umana per ogni modifica: fermati e chiedi.
- **La persistenza delle conversazioni è scritta dal router, mai da un tool.** F14 è esattamente il
  momento in cui la tentazione di "un tool che salva" è più forte: il registry resta read-only e un
  test di regressione lo scandisce dopo l'introduzione della persistenza.
- Guardrail obbligatori: cap righe per tool call con **troncamento dichiarato nel risultato** (mai
  silenzioso), cap iterazioni del loop, timeout HTTP sul provider.
- Provider/chiave/modello non configurati → 4xx esplicito, mai un crash dell'app (ADR-0018 p.3).
- Il router `/ai` va montato in `main.py` **prima** del blocco che serve la SPA: Starlette matcha per
  ordine di registrazione e il catch-all inghiottirebbe la route (trappola di ADR-0021).
- Nessuna modifica di schema, nessuna Alembic revision in questa fase (se emerge un bisogno di
  schema, fermati e coordina con schema-agent).
- Nessun secret nel repo. La chiave vive solo in `.env` (ADR-0011).
- Mock ammesso **solo** per `AIProvider` (dipendenza esterna a pagamento e non deterministica,
  precedente ADR-0018 p.7). Tool registry e service layer si testano su DB reale di test.
- La UI mostra sempre la traccia dei tool chiamati: i numeri devono restare ricontrollabili.
- Dubbi → fermati e chiedi.
