# F6 — Plugin AI: query NL su dati finanziari — design spec

Data: 2026-07-18 (rev. 2, allineata al codice reale) · Fase: F6 · Riferimenti: ARCHITECTURE.md §3 Fase 6
(N-F11), ADR-0009 (esposizione LAN), ADR-0018 punto 3/7 (graceful-degradation e mock provider esterno),
ADR-0019 (pattern react-ui-agent, letture su DB live), ADR-0023 (decisioni di questa fase).

## Contesto

F5 + F-DEBT completate e mergiate su master. F6 = prima fase che introduce un layer AI, previsto
fin dal piano originale (N-F11: "plugin AI con API key utente per insight NL", diagramma
architettura §2 "AI LAYER (futuro) — Adapter provider-agn, API key utente env, Insight NL
aggregati"). ARCHITECTURE.md §4 Evoluzione futura menziona separatamente "categorizzazione assistita
AI delle transazioni pending" — **fuori scope di questa fase**, sottosistema indipendente (write su
`category_pending` vs query read-only), da progettare con spec/ADR propri quando parte.

**Rev. 2 (2026-07-18)**: la rev. 1 nasceva da brainstorming e non era stata verificata contro il
codice. Il confronto col repo ha trovato 7 incoerenze, tutte risolte in questa revisione e registrate
in ADR-0023. Le due bloccanti erano: nomi delle variabili di config già occupati da altri nomi, e
logica `/insights` priva di qualunque filtro.

## Decisioni (confermate dall'utente)

1. **Scope sessione**: solo query NL su insight/dati aggregati e transazioni grezze filtrabili.
   Categorizzazione AI delle pending esplicitamente esclusa.
2. **Provider**: adapter provider-agnostico (interfaccia astratta), con **un solo adapter concreto
   in questa fase — Google AI Studio (Gemini)**. Anthropic/OpenAI restano interfaccia pronta, non
   implementati.
3. **Superficie**: sia endpoint backend (`POST /ai/query`) sia nuova pagina React "Assistente AI"
   (settima pagina, dopo Backup) — non solo API.
4. **Scope dati**: il modello può richiedere sia dati aggregati sia transazioni grezze filtrabili
   (data/categoria/conto/importo/tipo), **inclusi i campi liberi `comment` e `tag`**. Implica un loop
   tool-use (function calling) lato backend, non un singolo prompt statico. Trade-off privacy
   accettato esplicitamente dall'utente e documentato in `docs/SECURITY.md`.
5. **Memoria conversazione**: nessuna. Ogni domanda è indipendente e stateless — nessuna tabella
   nuova, nessuna Alembic revision.
6. **Approccio implementativo**: adapter custom leggero (non libreria multi-provider tipo
   LiteLLM/AnyLLM, non framework agent tipo LangChain). Scartati per: dipendenza pesante non
   necessaria per uso stateless single-user (N-NF4), peso extra su Raspberry (N-NF2, F7).
7. **Modello di default**: linea *flash-lite* GA (la più economica adeguata al compito), configurabile
   via env senza rilascio. Il dataset reale è di poche centinaia di righe: un modello di punta non
   porta valore proporzionale al costo.

### Verifica API Gemini (fatta il 2026-07-18 su ai.google.dev)

La rev. 1 segnalava come **non validato** il nome del modello e dell'endpoint. Verificato:

- SDK Python: pacchetto `google-genai`, import `from google import genai`.
- API: **Interactions API** (GA), metodo `client.interactions.create()`.
- Function calling: **loop manuale**, il modello non esegue nulla da sé. Il backend intercetta lo step
  `function_call`, esegue localmente, e rimanda uno step `function_result` con i campi `name`,
  `call_id` (da propagare identico) e `result`.
- Modelli GA disponibili: `gemini-3.5-flash` (di punta), `gemini-3.1-flash-lite`, `gemini-2.5-flash`,
  `gemini-2.5-flash-lite`, `gemini-2.5-pro`.

Riverificare comunque il model id corrente a inizio implementazione: la linea di modelli si muove
in fretta, e il valore vive in una env var proprio per non richiedere un rilascio quando cambia.

## Architettura

```
Frontend "Assistente AI" (nuova pagina React, react-ui-agent)
        │ POST /ai/query {question}
        ▼
Router /ai/query (FastAPI, NUOVO — montato PRIMA del catch-all SPA)
        │
        ▼
AIProvider (interfaccia astratta) ← selezionato da AI_PROVIDER env (oggi solo "gemini")
        │  loop tool-use manuale: il provider chiede l'esecuzione di un tool,
        │  il backend lo esegue e rimanda il risultato, finche' il modello
        │  non produce una risposta testuale finale (cap iterazioni)
        ▼
Tool registry READ-ONLY (backend/app/ai/tools.py):
  - list_transactions(date_from, date_to, category, account, amount_min/max, type)
  - get_insights(date_from, date_to, account, type)   → service layer (vedi sotto)
  - get_accounts()
  - get_categories()
        │  (wrapper sulle query gia' esistenti — nessuna query SQL duplicata)
        ▼
DB live (stesso pattern read di ADR-0019: WAL, nessuna replica per endpoint FastAPI)
```

Nessuna modifica di schema — nessuna Alembic revision per F6 (stateless, nessuna tabella nuova).

### Nuovi componenti backend

- **`backend/app/services/insights.py`** — le 4 funzioni di aggregazione oggi private nel router
  (`_monthly_trend`, `_category_breakdown`, `_cumulative_balance`, `_balance_by_account`,
  `backend/app/routers/insights.py:19-73`) vengono spostate qui e dotate di **filtri opzionali**
  (`date_from`, `date_to`, `account`, `type`). `GET /insights` diventa un wrapper sottile e, chiamato
  senza parametri, deve restituire esattamente l'output odierno (i 5 test esistenti passano
  invariati). Senza questo passo il modello non potrebbe rispondere a "quanto ho speso a marzo per
  categoria" se non scaricando le transazioni grezze e sommandole da sé — più costoso e meno
  affidabile.
- **`backend/app/ai/provider.py`** — interfaccia astratta `AIProvider`, metodo
  `answer(question: str) -> AIAnswer` (risposta testuale finale + traccia dei tool chiamati, esposta
  in UI perché i numeri restino ricontrollabili).
- **`backend/app/ai/providers/gemini.py`** — primo adapter concreto. Implementa il loop tool-use
  dell'Interactions API.
- **`backend/app/ai/tools.py`** — tool registry read-only, condiviso da tutti gli adapter
  presenti/futuri (indipendente dal provider). Genera qui anche lo schema JSON delle dichiarazioni.
- **`backend/app/routers/ai.py`** — `POST /ai/query`, body `{question: str}`, risposta
  `{answer: str, tools_used: [...]}`.

### Configurazione

Le variabili **esistono già** in `backend/app/config.py:24-25` e `.env.example:28-31` — non
introdurne di provider-specifiche (contraddirebbe l'adapter provider-agnostico):

| Var | Uso |
|---|---|
| `AI_PROVIDER` | oggi unico valore supportato: `gemini`. Vuoto = layer AI disattivo |
| `AI_API_KEY` | chiave personale dell'utente, mai committata |
| `AI_MODEL` | **nuova**, model id; default sulla linea flash-lite GA |

### Limiti operativi (guardrail)

Non erano nella rev. 1. Servono perché il costo, la latenza e il volume di dati che lasciano la LAN
dipendono tutti da quante volte il loop gira e quante righe restituisce ogni tool:

- **Cap righe per tool call**: `list_transactions` non restituisce mai più di N righe al modello. Il
  troncamento è **dichiarato nel risultato del tool**, mai silenzioso, così il modello sa che sta
  vedendo un sottoinsieme e può restringere i filtri invece di rispondere su dati parziali.
- **Cap iterazioni del loop**: superato il limite, l'endpoint risponde con quanto raccolto e lo
  segnala, invece di ciclare a costo indefinito.
- **Timeout HTTP** sulla chiamata al provider (stesso principio del timeout 30s già imposto al client
  Drive in F4).

### Guardrail di sicurezza (non negoziabili)

- **Tool registry solo lettura**: nessun tool può eseguire scritture. Il modello non ha mai accesso a
  operazioni che modificano `transactions`/`accounts`/`category_pending`. Un output non deterministico
  del modello non può quindi alterare o cancellare dati — la cautela già imposta su restore/delete
  (ADR-0018 p.5, ADR-0019 p.6) qui è applicata a monte, non esponendo affatto il tool di scrittura.
  `PUT /transactions/{id}` continua a editare solo `comment`/`tag`/`category_id`: regola invariata,
  nessun tool AI la richiama.
- **Secrets**: chiave via `.env`, mai committata, stesso enforcement pre-commit content-based
  (ADR-0011). Provider non configurato o chiave mancante → **4xx esplicito** dall'endpoint, nessun
  crash dell'app e nessun impatto sul resto delle funzionalità (pattern graceful-degradation del
  Drive opzionale, ADR-0018 p.3).
- **Egress esterno**: prima chiamata di rete verso un servizio esterno diverso da Google Drive in
  questo progetto. Solo su azione esplicita dell'utente (submit del form), mai automatica o in
  background — stesso principio di controllo-utente-sul-quando del backup (ADR-0008). Dati finanziari
  **incluso il testo libero di `comment`/`tag`** lasciano la rete locale verso il provider scelto
  dall'utente con la sua chiave personale. Annotato in `docs/SECURITY.md`.
- **Ordine di montaggio**: il router `/ai` va incluso in `main.py` **prima** del blocco che serve la
  SPA — Starlette fa match per ordine di registrazione, e il catch-all `GET /{full_path:path}`
  intercetterebbe qualunque route registrata dopo di lui (stessa trappola di DEBT-02/ADR-0021).

### Frontend

Nuova pagina "Assistente AI" su route `/assistente-ai` (react-ui-agent, stesso pattern delle altre 6
pagine F5): textbox domanda, submit, area risposta, stato loading/error via TanStack Query mutation,
**traccia dei tool chiamati visibile** accanto alla risposta. Nessuna gestione storico/multi-turno
(stateless, decisione 5). Voce aggiunta a `frontend/src/components/Sidebar.tsx` e route in `App.tsx`;
proxy `/ai` in `vite.config.ts` (nessuna collisione con la route SPA, che ha nome diverso — vincolo
ADR-0022).

## Test

- Suite pytest su `POST /ai/query`: **mock del solo `AIProvider`** (adapter fake, deterministico) —
  stesso precedente accettato del fake Drive service (ADR-0018 p.7: mock ammesso solo per dipendenza
  esterna non deterministica e a pagamento, mai per DB o business logic). Il tool registry resta
  testato **senza mock**, con query reali sul DB di test.
- Suite sui guardrail: cap righe rispettato e troncamento dichiarato; nessun tool di scrittura
  raggiungibile dal registry.
- Suite sul service layer insights: i 5 test esistenti passano invariati (retrocompatibilità) + nuovi
  test sui filtri.
- Nessuna Alembic revision, nessuna migrazione da testare.
- Verifica E2E manuale in browser a fine implementazione (pattern F1-F5): domanda reale con chiave
  valida, con la risposta **confrontata contro i totali noti del dataset** (F2: 331 transazioni,
  uscite 9937.70 €, entrate 19497.14 €).

## Documentazione aggiornata in questa sessione

- `docs/DECISIONS.md` — ADR-0023 (scritto **prima** del codice, regola di progetto).
- `docs/SECURITY.md` — sezione "Egress esterno verso il provider AI (F6)".
- `docs/ARCHITECTURE.md` — Fase 6 espansa con milestone, stato avanzamento, prompt di ripresa.
- `CLAUDE.md` — `ai-agent` nella lista sottoagenti.
- `.claude/agents/ai-agent.md` — nuovo sottoagente di dominio.
- `docs/superpowers/plans/2026-07-18-f6-ai-nl-query.md` — piano implementativo task-per-task.

## Documentazione da aggiornare a fine implementazione

- `docs/ARCHITECTURE.md` — riga F6 in Stato avanzamento → ☑ con evidenze; prompt di ripresa → F7.
- `CLAUDE.md` — riga "Fase corrente" → F7.
- `.superpowers/sdd/progress.md` — ledger F6.

## Fuori scope (YAGNI)

- Categorizzazione AI assistita per `category_pending` (sottosistema write separato, spec/ADR propri).
- Memoria/storico conversazione multi-turno.
- Rate-limit o budget token lato server (costo sulla chiave personale dell'utente).
- Streaming risposta (SSE/websocket) — v1 request/response singolo.
- Adapter Anthropic/OpenAI concreti (solo interfaccia pronta per estenderli).
- Autenticazione/reverse proxy — esposizione resta solo LAN (ADR-0009 invariato); l'egress verso il
  provider AI è un flusso uscente iniziato dall'utente, non un'esposizione entrante nuova.
