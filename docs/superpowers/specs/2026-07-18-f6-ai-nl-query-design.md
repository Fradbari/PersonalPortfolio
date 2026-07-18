# F6 — Plugin AI: query NL su dati finanziari — design spec

Data: 2026-07-18 · Fase: F6 · Riferimenti: ARCHITECTURE.md §3 Fase 6 (N-F11), ADR-0009 (esposizione LAN),
ADR-0018 punto 3/7 (pattern graceful-degradation e mock provider esterno), ADR-0019 (pattern react-ui-agent)

## Contesto

F5 + F-DEBT completate e mergiate su master. F6 = prima fase che introduce un layer AI, previsto
fin dal piano originale (N-F11: "plugin AI con API key utente per insight NL", diagramma
architettura §2 "AI LAYER (futuro) — Adapter provider-agn, API key utente env, Insight NL
aggregati"). ARCHITECTURE.md §3 Fase 6 menziona anche, separatamente, in §4 Evoluzione futura,
"categorizzazione assistita AI delle transazioni pending" — **fuori scope di questa sessione**,
sottosistema indipendente (write su `category_pending` vs query read-only), da progettare con
un ADR/spec proprio quando parte.

## Decisioni (confermate dall'utente in brainstorming)

1. **Scope sessione**: solo query NL su insight/dati aggregati e transazioni grezze filtrabili.
   Categorizzazione AI pending esplicitamente esclusa.
2. **Provider**: adapter provider-agnostico (interfaccia astratta), ma **un solo adapter concreto
   in questa fase — Google AI Studio (Gemini)**. Anthropic/OpenAI restano interfaccia pronta,
   non implementati. Nota verificata via ricerca: il nome modello/endpoint esatto Gemini
   (`gemini-3.5-flash` / "Interactions API" emerso da WebFetch su ai.google.dev) **non è stato
   validato con certezza** contro fonte affidabile — va riverificato a inizio implementazione
   contro la doc ufficiale corrente, non dare per assodato quanto scritto qui.
3. **Superficie**: sia endpoint backend (`POST /ai/query`) sia nuova pagina React "Assistente AI"
   (settima pagina, dopo Backup) — non solo API.
4. **Scope dati**: il modello può richiedere sia dati aggregati (`/insights`) sia transazioni
   grezze filtrabili (data/categoria/conto/importo/tipo) — non solo aggregati. Implica un loop
   tool-use (function-calling) lato backend, non un singolo prompt statico.
5. **Memoria conversazione**: nessuna. Ogni domanda è indipendente e stateless — nessuna tabella
   nuova, nessuna Alembic revision per la sessione di chat.
6. **Approccio implementativo**: adapter custom leggero (non libreria multi-provider tipo
   LiteLLM/AnyLLM, non framework agent tipo LangChain). Scartati per: dipendenza pesante non
   necessaria per uso stateless single-user (N-NF4), peso extra su Raspberry (N-NF2, F7),
   compatibilità Gemini tool-use non verificabile con certezza in una libreria terza in questo
   momento.

## Architettura

```
Frontend "Assistente AI" (nuova pagina React, react-ui-agent)
        │ POST /ai/query {question}
        ▼
Router /ai/query (FastAPI, NUOVO)
        │
        ▼
AIProvider (interfaccia astratta) ← selezionato da AI_PROVIDER env (oggi solo "gemini")
        │  loop tool-use: il provider puo' chiedere l'esecuzione di un tool,
        │  il backend lo esegue e rimanda il risultato, finche' il modello
        │  non produce una risposta testuale finale
        ▼
Tool registry READ-ONLY (backend/app/ai/tools.py):
  - list_transactions(filtri: date_range, category, account, amount_min/max, type)
  - get_insights()      → riusa la logica di insights.py esistente
  - get_accounts()      → riusa accounts.py esistente
  - get_categories()    → riusa categories.py esistente
        │  (wrapper sulle funzioni di query gia' esistenti — nessuna query SQL duplicata)
        ▼
DB live (stesso pattern read di ADR-0019: WAL, nessuna replica necessaria per endpoint FastAPI)
```

Nessuna modifica di schema — nessuna Alembic revision per F6 (stateless, nessuna tabella nuova).

### Nuovi componenti backend

- **`backend/app/ai/provider.py`** — interfaccia astratta `AIProvider` con un metodo
  `answer(question: str) -> AIAnswer` (risposta testuale finale + eventuale traccia dei tool
  chiamati, utile per debug/UI).
- **`backend/app/ai/providers/gemini.py`** — primo adapter concreto. Implementa il loop
  tool-use specifico dell'API Gemini (function calling). Verificare a inizio implementazione:
  nome modello corrente, formato esatto della function-calling request/response (vedi nota
  punto 2 sopra).
- **`backend/app/ai/tools.py`** — tool registry read-only condiviso da tutti gli adapter
  presenti/futuri (stesso registry, indipendente dal provider).
- **`backend/app/routers/ai.py`** — `POST /ai/query`, body `{question: str}`, risposta
  `{answer: str}` (+ eventuale campo debug con tool usati).

### Guardrail di sicurezza (non negoziabili)

- **Tool registry solo lettura**: nessun tool del registry può chiamare `PUT`/`DELETE`/`POST` di
  scrittura. Il modello non ha mai accesso a operazioni che modificano `transactions`/`accounts`/
  `category_pending`. Questo evita che un output non deterministico del modello alteri/cancelli
  dati — coerente con la cautela già imposta su restore/delete (ADR-0018 punto 5, ADR-0019
  punto 6), qui applicata a monte impedendo l'esposizione stessa del tool di scrittura.
  `PUT /transactions/{id}` continua a editare solo `comment`/`tag`/`category_id` (regola invariata,
  mai toccata da questa fase — nessun tool AI la richiama comunque).
- **Secrets**: chiave provider via `.env`, mai committata — stesso enforcement pre-commit hook
  content-based (ADR-0011). Config: `AI_PROVIDER` (oggi solo valore `gemini` supportato) +
  `GEMINI_API_KEY`. Provider non configurato o chiave mancante → errore 4xx esplicito
  dall'endpoint, nessun crash app (stesso pattern graceful-degradation del Drive opzionale,
  ADR-0018 punto 3).
- **Egress esterno**: prima chiamata di rete verso un servizio esterno diverso da Google Drive
  in questo progetto. Solo su azione esplicita dell'utente (submit del form), mai automatica o
  in background — stesso principio di controllo-utente-sul-quando già usato per il backup
  (ADR-0008). Da annotare in `docs/SECURITY.md`: nuova voce di egress, dati finanziari (anche
  transazioni grezze, per decisione punto 4) lasciano la rete locale verso il provider scelto
  dall'utente con la sua chiave personale.

### Frontend

Nuova pagina "Assistente AI" (react-ui-agent, stesso pattern delle altre 6 pagine F5): textbox
domanda, submit, area risposta, stato loading/error via TanStack Query mutation. Nessuna gestione
storico/multi-turno in UI (stateless, decisione punto 5).

## Test

- Suite pytest su `POST /ai/query`: **mock del solo `AIProvider`** (adapter fake, deterministico)
  — stesso precedente accettato del fake Drive service (ADR-0018 punto 7: mock necessario per
  dipendenza esterna non deterministica/a pagamento, mai mock di DB o business logic). Il tool
  registry (query reali sul DB di test) resta testato senza mock.
- Nessuna Alembic revision, nessuna migrazione da testare.
- Verifica E2E manuale in browser a fine implementazione (stesso pattern F1-F5): domanda reale
  con chiave Gemini valida, verifica che la risposta rifletta dati corretti noti (es. dataset di
  test già usato in F2/F3/F4/F5).

## Documentazione da aggiornare a fine implementazione

- `docs/DECISIONS.md` — nuovo ADR (numero successivo a 0022) con le decisioni di questa spec
  prima di scrivere codice (da scrivere come primo passo dell'implementazione, non a fine fase).
- `docs/SECURITY.md` — nuova voce egress esterno (vedi sopra).
- `CLAUDE.md` — riga "Fase corrente" → F7 a fine fase; sottoagente AI (se creato) mappato.
- `docs/ARCHITECTURE.md` — stato avanzamento F6 (☑ con evidenze), prompt di ripresa.

## Fuori scope (YAGNI)

- Categorizzazione AI assistita per `category_pending` (sottosistema separato, spec/ADR propri).
- Memoria/storico conversazione multi-turno.
- Rate-limit o budget token lato server (costo sulla chiave personale dell'utente).
- Streaming risposta (SSE/websocket) — v1 request/response singolo.
- Adapter Anthropic/OpenAI concreti (solo interfaccia pronta per estenderli).
- Autenticazione/reverse proxy — esposizione resta solo LAN (ADR-0009 invariato); l'egress verso
  il provider AI è un flusso uscente iniziato dall'utente, non un'esposizione entrante nuova.
