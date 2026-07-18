# F6 — Plugin AI: query NL sui dati finanziari — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`
> (raccomandata, stesso processo di F5) oppure `superpowers:executing-plans`. Gli step usano
> checkbox (`- [ ]`). Sottoagente di dominio: `ai-agent` (`.claude/agents/ai-agent.md`); Task 5 usa
> `react-ui-agent`.

**Goal:** porre domande in linguaggio naturale sui propri dati finanziari, con la propria chiave API,
in sola lettura, con la risposta verificabile contro i numeri reali.

**Architecture:** `POST /ai/query` → `AIProvider` astratto → adapter Gemini con loop tool-use manuale
→ tool registry read-only → query esistenti sul DB live. Settima pagina React su `/assistente-ai`.

**Tech Stack:** SDK `google-genai` (Interactions API, function calling manuale), FastAPI, SQLAlchemy,
React+Vite+TS+TanStack Query. Nessuna modifica di schema, nessuna Alembic revision.

**Riferimenti obbligatori:** ADR-0023 (vincolante), spec
`docs/superpowers/specs/2026-07-18-f6-ai-nl-query-design.md`.

## Global Constraints

- **Nessun tool di scrittura esposto al modello, mai** (ADR-0023 p.4). Il registry contiene solo
  letture. Se un task sembra richiedere una scrittura: fermarsi e chiedere.
- **Nessuna modifica di schema, nessuna Alembic revision** (ADR-0023 p.6). Se emerge un bisogno di
  schema: fermarsi e coordinare con `schema-agent`.
- **Nessun secret nel repo.** Chiave solo in `.env` (ADR-0011). Il pre-commit hook content-based è
  attivo e **non** esclude `.claude/agents/` né `backend/`.
- **Config**: usare `AI_PROVIDER` e `AI_API_KEY` già esistenti (`backend/app/config.py:24-25`), più
  la nuova `AI_MODEL`. **Mai** introdurre `GEMINI_API_KEY` o altre variabili provider-specifiche
  (ADR-0023 p.3).
- **Ordine di montaggio**: il router `/ai` va incluso in `main.py` **prima** del blocco
  `if os.path.isdir(FRONTEND_DIST)` (riga ~49): Starlette matcha per ordine di registrazione e il
  catch-all `GET /{full_path:path}` inghiottirebbe la route (trappola di ADR-0021).
- **Retrocompatibilità `/insights`**: dopo il Task 1, `GET /insights` senza query param deve
  restituire esattamente l'output odierno. I 5 test di `test_insights.py` devono passare
  **invariati** — non adattarli, sono il contratto.
- **Mock**: ammesso **solo** per `AIProvider` (ADR-0018 p.7). Mai mockare DB o business logic.
- **Pattern test del repo**: helper locale `_build_test_app()` con engine `sqlite://` in-memory +
  `StaticPool` + `dependency_overrides[get_session]`. Riferimento:
  `backend/tests/test_insights.py:14-36`. Nessun `conftest.py` nel repo — non introdurne uno senza
  motivo.
- **Deviazione sostanziale dal piano** → fermarsi, scrivere un ADR, chiedere. Non improvvisare.

---

## Task 1: Backend — service layer insights con filtri opzionali

**Files:**
- Create: `backend/app/services/__init__.py`, `backend/app/services/insights.py`
- Modify: `backend/app/routers/insights.py`
- Test: `backend/tests/test_insights_service.py` (nuovo); `backend/tests/test_insights.py` **invariato**

**Interfaces:**
- Produces: 4 funzioni pubbliche consumate dal router e dal tool registry (Task 2).
- Consumes: `app.models.Transaction`, `sqlalchemy`.

Le 4 funzioni oggi private in `backend/app/routers/insights.py:19-73` si spostano in
`app/services/insights.py`, perdono l'underscore e acquisiscono filtri opzionali:

```python
# backend/app/services/insights.py — firme (corpi da portare dal router, non riscrivere la logica)
def monthly_trend(session, *, date_from=None, date_to=None, account=None, type_=None) -> list[dict]
def category_breakdown(session, *, date_from=None, date_to=None, account=None, type_="expense") -> list[dict]
def cumulative_balance(trend: list[dict]) -> list[dict]   # invariata, puro in-memory
def balance_by_account(session, *, date_from=None, date_to=None, type_=None) -> list[dict]
```

- I filtri si applicano come `WHERE` addizionali (`Transaction.date >= date_from`,
  `<= date_to`, `Transaction.account == account`, `Transaction.type == type_`), **solo quando non
  `None`**. Con tutti `None` la query generata deve essere semanticamente identica a quella odierna.
- `category_breakdown` oggi hardcoda `where(Transaction.type == "expense")`
  (`insights.py:43`): il default `type_="expense"` **preserva** quel comportamento; passare
  `type_=None` significa "entrambi i tipi", non "nessun filtro accidentale". Documentarlo nel
  docstring — è l'unico punto in cui il default non è `None` e va capito a colpo d'occhio.
- Il router `GET /insights` diventa un wrapper sottile che importa dal service. Facoltativo (e
  consigliato): esporre gli stessi filtri come query param opzionali sull'endpoint HTTP — a costo
  zero, dato che la logica c'è già.

- [ ] **Step 1: Scrivi `backend/tests/test_insights_service.py` (fallirà: il modulo non esiste)**
      Copertura minima: ogni filtro singolarmente; combinazione di due filtri; `date_from`/`date_to`
      inclusivi agli estremi; `category_breakdown` con `type_=None` restituisce anche le entrate;
      tutti i filtri `None` produce lo stesso output della funzione senza filtri.
- [ ] **Step 2: Esegui la suite e verifica che fallisca**
      `Run: cd backend && PYTHONPATH=. python -m pytest tests/test_insights_service.py`
      `Expected: FAIL — ModuleNotFoundError: app.services.insights`
- [ ] **Step 3: Implementa il service e riduci il router a wrapper**
- [ ] **Step 4: Verifica**
      `Run: cd backend && PYTHONPATH=. python -m pytest`
      `Expected: PASS — i 36 test esistenti + i nuovi. test_insights.py NON deve essere stato toccato`
      (verificalo con `git diff --stat backend/tests/test_insights.py` → deve essere vuoto).
- [ ] **Step 5: Commit** — `refactor(F6): estrae insights in service layer con filtri opzionali`

---

## Task 2: Backend — tool registry read-only

**Files:**
- Create: `backend/app/ai/__init__.py`, `backend/app/ai/tools.py`
- Test: `backend/tests/test_ai_tools.py`

**Interfaces:**
- Consumes: `app.services.insights` (Task 1), `app.models`.
- Produces: `TOOLS` (registry eseguibile) + `tool_declarations()` (schema JSON provider-agnostico),
  entrambi consumati dall'adapter (Task 3).

Quattro tool, tutti letture, tutti wrapper su query esistenti — **zero SQL nuovo** salvo il filtro
composito di `list_transactions`, che riusa lo stesso pattern del router
(`backend/app/routers/transactions.py:47-58`):

| Tool | Parametri | Fonte |
|---|---|---|
| `list_transactions` | `date_from`, `date_to`, `category`, `account`, `amount_min`, `amount_max`, `type` | query come `routers/transactions.py`, serializzazione come `_serialize()` (`transactions.py:20-33`) |
| `get_insights` | `date_from`, `date_to`, `account`, `type` | `app.services.insights` (Task 1) |
| `get_accounts` | — | `routers/accounts.py:17` |
| `get_categories` | — | `routers/categories.py:33` |

Guardrail obbligatori, **testati**:

- `MAX_TOOL_ROWS = 200` (allineato al `page_size` massimo già ammesso da
  `transactions.py:43`). Il risultato di `list_transactions` è
  `{"rows": [...], "returned": N, "total_matching": M, "truncated": bool}` — se troncato, il campo
  `truncated` è `True` e va accompagnato da una nota testuale leggibile dal modello (es. "risultato
  troncato a 200 righe su M: restringi i filtri"). **Mai troncare in silenzio**: un modello che non
  sa di vedere un sottoinsieme risponde con sicurezza su dati parziali.
- Le righe includono `comment` e `tag` (ADR-0023 p.9, scelta esplicita dell'utente). Non escluderli
  "per prudenza": è una decisione presa, e cambiarla è un ADR nuovo.
- `tool_declarations()` produce lo schema JSON delle funzioni in forma **neutra rispetto al
  provider**: la traduzione nel formato Gemini avviene nell'adapter (Task 3), non qui. È ciò che
  rende il registry riusabile da un secondo adapter senza toccarlo.

- [ ] **Step 1: Scrivi `backend/tests/test_ai_tools.py` (fallirà)**
      Copertura minima: ogni filtro di `list_transactions`; **cap righe rispettato e `truncated=True`
      con `total_matching` corretto** (seed > 200 righe); `get_insights` propaga i filtri al service;
      **nessun nome di tool nel registry corrisponde a un verbo di scrittura** e nessuna callable del
      registry esegue `INSERT`/`UPDATE`/`DELETE` (test esplicito, è il guardrail centrale della fase);
      `tool_declarations()` restituisce una dichiarazione per ogni tool eseguibile, senza orfani in
      nessuna delle due direzioni.
- [ ] **Step 2: Esegui e verifica il fallimento**
      `Run: cd backend && PYTHONPATH=. python -m pytest tests/test_ai_tools.py`
      `Expected: FAIL — ModuleNotFoundError: app.ai.tools`
- [ ] **Step 3: Implementa il registry**
- [ ] **Step 4: Verifica** — `Run: cd backend && PYTHONPATH=. python -m pytest` / `Expected: PASS`
- [ ] **Step 5: Commit** — `feat(F6): tool registry read-only per il layer AI`

---

## Task 3: Backend — interfaccia `AIProvider` + adapter Gemini

**Files:**
- Create: `backend/app/ai/provider.py`, `backend/app/ai/providers/__init__.py`,
  `backend/app/ai/providers/gemini.py`
- Modify: `backend/requirements.txt` (aggiunge `google-genai`), `backend/app/config.py` (aggiunge
  `ai_model`), `.env.example` (aggiunge `AI_MODEL=`)
- Test: `backend/tests/test_ai_provider.py`

**Interfaces:**
- Consumes: `app.ai.tools` (Task 2), `app.config.settings`.
- Produces: `AIProvider`, `AIAnswer`, `get_provider()` — consumati dal router (Task 4).

```python
# backend/app/ai/provider.py — contratto
@dataclass
class ToolCall:      name: str; args: dict; result_summary: str
@dataclass
class AIAnswer:      text: str; tool_calls: list[ToolCall]; truncated: bool = False

class AIProviderError(Exception): ...        # errore runtime del provider  → 502
class AIProviderNotConfigured(AIProviderError): ...  # config assente       → 400

class AIProvider(ABC):
    @abstractmethod
    def answer(self, question: str, session) -> AIAnswer: ...

def get_provider() -> AIProvider:   # dispatch su settings.ai_provider; oggi solo "gemini"
```

Adapter Gemini (`providers/gemini.py`):

- **Prima di scrivere codice, riverifica la doc corrente** su
  `https://ai.google.dev/gemini-api/docs/interactions/function-calling`. Stato al 2026-07-18: SDK
  `google-genai` (`from google import genai`), `client.interactions.create()`, il modello **non
  esegue nulla** — si intercetta lo step `function_call`, si esegue localmente, si rimanda uno step
  `function_result` con `name`, `call_id` **propagato identico** e `result`. La linea di modelli si
  muove in fretta: se la doc diverge da questa descrizione, **fermati e segnala** invece di adattare
  a intuito.
- Loop manuale con `MAX_ITERATIONS = 5`. Superato il limite: si restituisce la risposta migliore
  disponibile con `truncated=True`, mai un ciclo aperto. (Valore tarabile senza nuovo ADR: alzarlo
  aumenta il costo per domanda, abbassarlo limita le domande multi-step.)
- Timeout HTTP sulla chiamata al provider (stesso principio del timeout 30s già imposto al client
  Drive in F4, `backend/app/drive.py`).
- **System prompt**: istruire il modello a rispondere **solo** sulla base dei risultati dei tool, a
  non inventare numeri, e a preferire `get_insights` (aggregazione fatta dal DB) rispetto al sommare
  a mano righe grezze — i modelli sbagliano l'aritmetica, il DB no. Rispondere nella lingua della
  domanda.
- `settings.ai_provider` vuoto, `ai_api_key` vuota o `ai_model` vuoto → `AIProviderNotConfigured`.
  Nessun import del SDK a livello di modulo che possa far crashare l'app se il pacchetto manca:
  import lazy dentro l'adapter.

- [ ] **Step 1: Scrivi `backend/tests/test_ai_provider.py` (fallirà)**
      Copertura minima (senza rete): `get_provider()` solleva `AIProviderNotConfigured` con config
      vuota, per ciascuna delle tre variabili mancanti; `get_provider()` con `AI_PROVIDER` ignoto
      solleva errore esplicito; un `AIProvider` fake che restituisce `AIAnswer` rispetta il
      contratto; il cap iterazioni produce `truncated=True` (testato su un fake che chiede tool
      all'infinito, **non** sul client Gemini reale).
- [ ] **Step 2: Esegui e verifica il fallimento**
      `Run: cd backend && PYTHONPATH=. python -m pytest tests/test_ai_provider.py`
      `Expected: FAIL — ModuleNotFoundError: app.ai.provider`
- [ ] **Step 3: Implementa interfaccia + adapter + config `ai_model` + dipendenza**
- [ ] **Step 4: Verifica** — `Run: cd backend && PYTHONPATH=. python -m pytest` / `Expected: PASS`
- [ ] **Step 5: Commit** — `feat(F6): interfaccia AIProvider e adapter Gemini con loop tool-use`

---

## Task 4: Backend — router `POST /ai/query`

**Files:**
- Create: `backend/app/routers/ai.py`
- Modify: `backend/app/main.py` (include router **prima** del blocco SPA; bump `version` e `phase` a 6)
- Test: `backend/tests/test_ai_router.py`

**Interfaces:**
- Consumes: `app.ai.provider` (Task 3), `app.db.get_session`.
- Produces: `POST /ai/query` — consumato dal frontend (Task 5).

- Body `{"question": str}` (non vuota, altrimenti 422). Risposta
  `{"answer": str, "tools_used": [{"name", "args", "result_summary"}], "truncated": bool}`.
- `AIProviderNotConfigured` → **400** con messaggio esplicito ("layer AI non configurato: imposta
  AI_PROVIDER, AI_API_KEY, AI_MODEL in .env"). `AIProviderError` → **502**. Mai un 500 non gestito,
  mai un crash: il resto dell'app non deve accorgersi che il provider è giù (ADR-0023 p.8).
- `main.py`: `include_router(ai.router)` insieme agli altri include (riga ~33-38), quindi **prima**
  del blocco `if os.path.isdir(FRONTEND_DIST)`. Aggiornare `version="0.1.0-phase6"` e
  `{"phase": "6"}` in `/health`.

- [ ] **Step 1: Scrivi `backend/tests/test_ai_router.py` (fallirà)**
      Con `dependency_overrides` che inietta un `AIProvider` **fake deterministico** (unico mock
      ammesso, ADR-0018 p.7): risposta 200 con `answer` e `tools_used` popolati; provider non
      configurato → 400 col messaggio esplicito; provider che solleva `AIProviderError` → 502;
      question vuota → 422.
- [ ] **Step 2: Esegui e verifica il fallimento**
      `Run: cd backend && PYTHONPATH=. python -m pytest tests/test_ai_router.py`
      `Expected: FAIL — ModuleNotFoundError: app.routers.ai`
- [ ] **Step 3: Implementa router + wiring in main.py + bump phase**
- [ ] **Step 4: Verifica**
      `Run: cd backend && PYTHONPATH=. python -m pytest`
      `Expected: PASS — tutta la suite`
      Verifica aggiuntiva sull'ordine delle route: `POST /ai/query` non deve cadere nel catch-all SPA.
- [ ] **Step 5: Commit** — `feat(F6): endpoint POST /ai/query`

---

## Task 5: Frontend — pagina "Assistente AI" (`react-ui-agent`)

**Files:**
- Create: `frontend/src/pages/AiAssistant.tsx`
- Modify: `frontend/src/App.tsx` (route `/assistente-ai`),
  `frontend/src/components/Sidebar.tsx` (7ª voce), `frontend/vite.config.ts` (proxy `/ai`)

**Interfaces:**
- Consumes: `POST /ai/query` (Task 4), `frontend/src/lib/api.ts`.

- Mutation TanStack Query sul pattern già in uso in
  `frontend/src/pages/CategoriesPending.tsx:22-26`, **incluso il display errore standard del repo**
  (`{mutation.error ? <p className="mt-3 text-red-600">…</p> : null}`) — il messaggio 400 "layer AI
  non configurato" deve arrivare leggibile all'utente, non sparire.
- La risposta mostra **sempre la traccia dei tool chiamati** (ADR-0023 p.11), anche in forma
  compatta/collassabile: è ciò che rende i numeri ricontrollabili invece che da prendere sulla
  fiducia. Non è un dettaglio di debug da nascondere.
- Nessuno storico conversazione: la pagina è stateless, ogni submit è indipendente (ADR-0023 p.6).
- Proxy: aggiungere `'/ai': 'http://localhost:8000'` in `vite.config.ts`. La route SPA è
  `/assistente-ai`, stringa diversa da `/ai` — **verificare comunque** che il match per prefisso di
  Vite non la catturi (è esattamente la classe di bug di ADR-0022; se collide, applicare il pattern
  `bypass` su `Accept: text/html` già usato per `/backup`).

- [ ] **Step 1: Implementa la pagina, la route, la voce sidebar, il proxy**
- [ ] **Step 2: Verifica browser manuale (dev server)**
      `Run: cd frontend && npm run dev`
      Expected: la voce compare in sidebar; una domanda con backend senza chiave mostra l'errore 400
      leggibile; **reload diretto del browser su `http://localhost:5173/assistente-ai` serve la SPA**,
      non un JSON del backend (regressione ADR-0022); zero errori in console.
- [ ] **Step 3: Commit** — `feat(F6): pagina Assistente AI`

---

## Task 6: Integrazione Docker e verifica E2E reale

**Files:** nessuno da creare — è un task di verifica. Eventuali fix emersi vanno committati a parte.

- [ ] **Step 1: Build e avvio**
      `Run: docker compose build backend && docker compose up -d`
      `Expected: pp-backend e pp-metabase entrambi healthy`
- [ ] **Step 2: Suite completa dentro il container di produzione**
      `Expected: PASS — 36 test preesistenti + i nuovi, zero fallimenti`
- [ ] **Step 3: `/health` risponde `"phase": "6"`**
- [ ] **Step 4: Domanda reale con chiave valida** su `http://localhost:8000/assistente-ai`
      (container di produzione, non dev server). Poni almeno tre domande di cui **conosci già la
      risposta** e confrontala coi totali noti del dataset F2: **331 transazioni, uscite 9937.70 €,
      entrate 19497.14 €**. Se i numeri non tornano, è un fallimento del task, non un capriccio del
      modello: indaga se il tool ha restituito dati troncati o filtrati male.
- [ ] **Step 5: Verifica del guardrail read-only** — nessun tool di scrittura è raggiungibile dal
      modello; il conteggio delle transazioni prima e dopo la sessione di domande è identico.
- [ ] **Step 6: Metabase su `:3000` invariata** (ADR-0004 rispettato) e le altre 6 pagine funzionanti.
- [ ] **Step 7: Commit** di eventuali fix — `fix(F6): …`

---

## Task 7: Chiusura fase

- [ ] **Step 1: `docs/ARCHITECTURE.md`** — riga F6 in *Stato avanzamento* → ☑ con evidenze reali
      (numeri dei test, esito delle domande di verifica, deviazioni dal piano); *Prompt di ripresa* → F7.
- [ ] **Step 2: `CLAUDE.md`** — riga "Fase corrente" → F7.
- [ ] **Step 3: `.superpowers/sdd/progress.md`** — ledger F6 task-per-task (formato del ledger F5).
- [ ] **Step 4: Nuovo ADR** se durante l'implementazione è emersa una deviazione sostanziale
      (ADR-0023 non si modifica: se cambia, se ne aggiunge uno che lo supera).
- [ ] **Step 5: Commit** — `docs(F6): chiude la fase, stato avanzamento e prompt di ripresa`

---

## Note di esecuzione

- Ambiente: su Windows i test si lanciano con `PYTHONPATH=.` da `backend/`. OneDrive può tenere lock
  su `node_modules/.vite` — se il dev server si pianta all'avvio, è quello (annotato in F5).
- Se il formato dell'API Gemini diverge da quanto descritto nel Task 3: **fermarsi e segnalare**, non
  adattare a intuito. È l'unica parte del piano basata su una fonte esterna che può cambiare.
- Non anticipare la categorizzazione AI delle pending, nemmeno "già che ci siamo": è un sottosistema
  **write** con spec e ADR propri, e richiede approvazione umana per ogni modifica.

## Domande aperte da validare con l'utente prima del Task 3

1. **Costo** — c'è un tetto mensile accettabile sulla chiave? Determina se `MAX_ITERATIONS = 5` va
   stretto (2-3) o largo (5-8).
2. **Lingua** — l'assistente risponde nella lingua della domanda (default assunto in questo piano) o
   sempre in italiano?
