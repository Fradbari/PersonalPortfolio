# Personal Portfolio — Piano Architetturale (rev. 2)

## Context

Serve un'app **dockerizzata** per finanza personale che unifichi due fonti dati oggi separate:

1. **Master budget** su Google Sheets — formato *wide/pivot*: categorie come colonne (Alimentari, Caffè, Trasp & Vett, Cena fuori, Afft & boll…), un tab per mese/anno, date `DD mese YYYY`, valuta EUR, righe con `Stipendio` per entrate e `Totale`/`Differenza` come sommari.
2. **Export mensile "My Finance"** (`ru.innim.my_finance`) → `.xlsx` — formato *long/tidy*: una riga per transazione, sheet `Spese`/`Entrate`/`Bonifici`, colonne ricche (`Data e ora`, `Categoria`, `Conto`, importi multi-valuta, `Tag`, `Commento`), date `DD/M/YYYY`, EUR.

Il problema: dati frammentati, nessuna dashboard, nessun backup strutturato, storico bloccato in un foglio pivot difficile da interrogare. Obiettivo: unica **sorgente di verità normalizzata a livello transazione**, con dashboard/insight, backup automatico e predisposizione AI — gestibile da **solo sviluppatore**, **one-click su Docker** (Windows ora, Raspberry Pi dopo), **senza vendor lock-in**.

**Nota fase**: pianificazione architetturale. *Nessun codice in questa sessione* — implementazione fase per fase nelle prossime.

## Decisioni confermate dall'utente

| Tema | Scelta |
|------|--------|
| Frontend/dashboard | **Ibrido** — Metabase subito (disaccoppiato, vedi C1), UI React custom in fase successiva |
| Storage canonico | **SQLite** (file singolo, WAL mode) |
| Vecchio Google Sheet master | **Migrazione una tantum**, con **dry-run** obbligatorio |
| Backup Google Drive | **Service Account** (JSON key, headless) |
| Backup trigger | **Manuale (pulsante)** sempre; **automatico solo all'avvio** se l'utente lo attiva in settings |
| Esposizione | **Solo rete locale** per ora — no auth/reverse proxy in questa fase (rivedere se esposto fuori) |
| Cadenza ingestion | **Upload manuale** per ora — automazione da Drive rimandata |
| Bonifici/Transfer | **Esclusi** dal calcolo (non considerati) |
| Import storico | **Solo dal 2026** — tab precedenti non importati |
| Conti (Account) | Divisione per `Conto` mantenuta; conti ignoti **importati as-is** (no pending), rinominabili in post; **storico xls → tutto "principale"** |
| Migration tool | **Alembic** — ogni fase che tocca lo schema produce una revision |
| Governance | **CLAUDE.md** unica fonte di verità; stato avanzamento + prompt ripresa nel piano; sottoagenti di progetto |

---

## 1. Mappa dei needs utente

### Funzionali
- **N-F1** Import export mensile `.xlsx`/`.csv` My Finance (upload locale via web o pickup da Drive).
- **N-F2** Import una tantum storico master Google Sheet (adapter *un-pivot* wide→long) — **solo dal 2026**, con dry-run.
- **N-F3** Normalizzazione: schema transazione canonico + tabella mapping categorie tra le due fonti.
- **N-F4** Deduplica idempotente su hash a campi stabili (vedi C2).
- **N-F5** **Category reconciliation queue**: categorie non mappate rilevate all'import → stato `pending`, transazione importata comunque ma flaggata, UI per assegnare il mapping (vedi Q2).
- **N-F6** Divisione per conto: transazioni portano `account`; conti ignoti importati **as-is** (nessuna coda pending — il nome sorgente diventa il valore `account`, rinominabile in dashboard); storico → `principale`.
- **N-F7** Dashboard: trend mensili, spesa per categoria, entrate vs uscite, saldo/differenza, breakdown %.
- **N-F8** Insight finanziari personalizzati (top categorie, scostamenti vs media, alert budget).
- **N-F9** Backup: pulsante manuale sempre; auto all'avvio opzionale. DB + export "in chiaro" `.xlsx` → Drive **e** locale.
- **N-F10** Restore da backup.
- **N-F11** (Futuro) plugin AI con API key utente per insight NL.

### Non funzionali
- **N-NF1** One-click: `docker compose up` → app pronta, zero setup manuale.
- **N-NF2** Portabilità multi-arch: `linux/amd64` (Windows) + `linux/arm64` (Raspberry).
- **N-NF3** No vendor lock-in: dati sempre esportabili in formato aperto (`.xlsx`/`.csv`/SQLite).
- **N-NF4** Manutenibilità solo-dev: stack minimale, pochi servizi, config centralizzata.
- **N-NF5** Interfaccia moderna, esposta su webpage.
- **N-NF6** Sicurezza: key AI e Service Account fuori dal repo, **con enforcement** (vedi C3).
- **N-NF7** Idempotenza e integrità dati. **Vincolo hash**: `hash_dedup` calcolato SOLO su campi stabili `(date_troncata_al_giorno, amount, category, account, type)` — **mai** su campi editabili post-import (`comment`, `tag`, timestamp con secondi).

---

## 2. Architettura proposta

Layered, container-per-responsabilità, unico `docker-compose.yml`.

```
┌─────────────────────────────────────────────────────────┐
│                     INGESTION LAYER                      │
│  Upload web (.xlsx/.csv)  ·  Drive pickup (SA)           │
│  Parser My Finance (long)  ·  Adapter master (un-pivot)  │
│  Category mapper + reconciliation queue  ·  Dedup (hash) │
└───────────────────────────┬─────────────────────────────┘
                            │  transazioni normalizzate
┌───────────────────────────▼─────────────────────────────┐
│              STORAGE LAYER — SQLite (WAL)                │
│  FastAPI = UNICO writer                                  │
│  Tabelle: transactions · categories · category_map ·     │
│  category_pending · accounts · import_batches · settings │
│  Volume Docker persistente                               │
└──────────┬───────────────────────────────┬──────────────┘
           │ write (live DB)               │ read-only replica snapshot
┌──────────▼───────────┐        ┌───────────▼──────────────┐
│   BACKEND (FastAPI)   │        │   FRONTEND LAYER          │
│  pandas/openpyxl ETL  │        │  FASE ora: Metabase       │
│  /import /transactions│        │   (legge replica R/O,     │
│  /insights /backup    │        │    versione pinnata)      │
│  /export /categories  │        │  FASE dopo: React+Vite    │
│  scheduler backup opt │◄───────┤   (consuma FastAPI)       │
└──────────┬────────────┘        └───────────────────────────┘
           │
┌──────────▼───────────┐        ┌──────────────────────────┐
│   AI LAYER (futuro)   │        │      INFRA LAYER         │
│  Adapter provider-agn │        │  compose · volumi · .env │
│  API key utente env   │        │  secrets enforcement     │
│  Insight NL aggregati │        │  backup SA Drive+locale  │
└───────────────────────┘        │  multi-arch · healthcheck│
                                 └──────────────────────────┘
```

**Backend**: **Python + FastAPI**. ETL finanziario = pandas/openpyxl (parsing `.xlsx`, un-pivot, dedup) via diretta; ecosistema AI maturo; un solo linguaggio → meno carico cognitivo solo-dev. Unico processo con accesso in scrittura al DB.

**C1 — Disaccoppiamento Metabase/SQLite** (antipattern risolto):
- SQLite in **WAL mode**: single writer (FastAPI) + reader concorrenti sicuri.
- Metabase **non** tocca il file live. Legge una **replica read-only** su volume `replica/`.
- **Meccanismo replica** (esplicito, no ambiguità): FastAPI esegue `shutil.copy2(db_live, db_replica)` **al completamento di ogni `import_batch`** — **mai** mid-write. WAL mode garantisce consistenza point-in-time durante la copia file. Nessuna finestra di inconsistenza.
- Metabase usa il suo H2 interno solo per metadati dashboard (non per i dati finanziari).
- **Alternativa** (se Metabase pesa troppo su Raspberry): saltare Metabase e anticipare la UI React alla Fase 3, puntando agli endpoint FastAPI. Decisione registrata come ADR.

**Schema canonico `transactions`**:
`id · date · amount · currency · type(expense|income) · category_id · account · comment · tag · source(master_sheet|my_finance) · import_batch_id · hash_dedup`
- `type` a 2 valori (transfer escluso per scelta utente).
- `hash_dedup` = hash di `(date@giorno, amount, category, account, type)` — contratto immutabile in DECISIONS.md.

**C2 — Dedup robusto**: hash su campi stabili sopra. Re-import stesso mese → stesso hash → skip. Modifica di `comment`/`tag` non genera duplicato.

**Category reconciliation (risposta Q2 + Q3)** — problema del *category drift* tra ciò che si scrive e ciò già scritto, sia nell'import one-time sia negli upload futuri:
- Ogni categoria sorgente risolta via `category_map` (nome sorgente → `category_id` canonico).
- Categoria **non trovata** in mappa → transazione importata comunque + record in `category_pending` (stato `unmapped`).
- UI `/categories`: lista pending, l'utente assegna → crea mapping → ri-risolve le transazioni flaggate (backfill del `category_id`).
- **Conti** (scelta diversa dalle categorie, ADR): conti ignoti importati **as-is** — il nome sorgente diventa il valore `account`, nessuna coda pending, nessun secondo flusso di riconciliazione. L'utente li vede in dashboard e li rinomina/accorpa in post. Semplifica lo stack.
- Storico xls: conto forzato a `principale`; categorie storiche mappate 1:1 dove combaciano, in coda pending dove no.

---

## 3. Piano a fasi con milestone

### Fase 0 — Fondazione, scaffolding, sicurezza, ADR
- Repo locale, struttura cartelle, `docker-compose.yml` scheletro, `.env.example`.
- **O1 — `docs/DECISIONS.md`** come deliverable di prima classe: template ADR + ADR iniziali già decisi (SQLite, FastAPI, Metabase disaccoppiato, Service Account, esposizione locale, backup manuale/startup, transfer esclusi). Ogni fase aggiunge i propri ADR **prima** di scrivere codice.
- **C3 — Enforcement sicurezza secrets** (step obbligatorio):
  - `.gitignore` con pattern: `*service_account*.json`, `credentials/`, `secrets/`, `*.key`, `*.db`, `backups/`.
  - **pre-commit hook content-based** (non su dimensione — un threshold byte bloccherebbe `package.json`/`tsconfig.json` legittimi in Fase 5). Il hook fa **grep del contenuto** dei file staged cercando pattern di secret: `private_key`, `client_email`, `auth_uri`, `-----BEGIN PRIVATE KEY-----` → blocca il commit se trovati. Più preciso di una soglia byte.
  - `docs/SECURITY.md`: come fornire le credenziali all'avvio (mount volume / env), cosa non committare mai, criterio del hook.
- Definizione schema SQLite (WAL) + **Alembic** come migration tool (già nello stack Python, zero dipendenze extra). Ogni fase successiva che modifica lo schema (Fase 1 `category_pending`, Fase 4 `settings`…) produce una `alembic revision` documentata. ADR in DECISIONS.md.
- **CLAUDE.md** come **unica fonte di verità** del progetto: link a DECISIONS.md/SECURITY.md, mappa fasi, comandi one-click, richiamo ai sottoagenti di progetto (sotto).
- **Sottoagenti di progetto** (definiti e mappati in CLAUDE.md, collegati a skill superpower generale): es. `ingestion-agent` (parser/adapter/dedup), `schema-agent` (Alembic/migrazioni), `dashboard-agent` (Metabase/replica), `backup-agent` (Drive SA/restore). Creati incrementalmente quando la fase relativa parte.
- **Milestone**: `docker compose up` avvia backend vuoto + SQLite persistente; CLAUDE.md/DECISIONS.md/SECURITY.md presenti; Alembic inizializzato; pre-commit hook attivo.

### Fase 1 — Ingestion My Finance + storage
- Parser export `.xlsx` My Finance (Spese/Entrate; **Bonifici ignorati**) → schema canonico, con colonna `Conto`.
- Upload web locale + dedup idempotente (hash C2) + `import_batches` audit.
- Category reconciliation queue attiva (N-F5).
- **Milestone**: upload `.xlsx` mensile → transazioni normalizzate con conto; re-upload = zero doppioni; categorie ignote finiscono in pending.

### Fase 2 — Migrazione storico master (una tantum, **solo dal 2026**, con dry-run)
- **R1 — Dry-run obbligatorio** (operazione più critica, storico finanziario):
  1. Import in **DB temporaneo** (non live).
  2. **Report**: N transazioni importate, somma per mese/categoria, righe scartate con motivazione (es. `Totale`/`Differenza`/`Stipendio`-sommari esclusi dalle transazioni).
  3. Confronto manuale col foglio originale.
  4. **Solo dopo validazione** → import definitivo su DB live + archiviazione foglio vecchio.
- Adapter un-pivot wide→long; conto = `principale` per tutto lo storico; categorie non combacianti → pending.
- **Milestone**: report dry-run validato manualmente → storico 2026 importato, quadratura totali confermata, foglio archiviato.

### Fase 3 — Dashboard (Metabase disaccoppiato)
- Container Metabase → **replica read-only** SQLite (mai file live). **R3 — versione pinnata** (`metabase/metabase:vX.YY.Z`, mai `latest`); policy aggiornamento in DECISIONS.md ("aggiorna solo con backup preventivo + lettura changelog").
- Dashboard: trend, per-categoria, entrate/uscite, breakdown %, saldo per conto.
- **Milestone**: dashboard navigabile su webpage con dati reali unificati, zero contesa file col backend.

### Fase 4 — Backup automatico
- **N-F9**: pulsante manuale sempre disponibile; job all'avvio **opzionale** (attivato in settings dall'utente).
- Dump SQLite + export "in chiaro" `.xlsx` → locale + Drive (Service Account).
- Retention/rotazione + procedura restore documentata e testata.
- **Milestone**: backup manuale e (se attivo) all'avvio producono file su Drive e locale; restore ripristina lo stato.

### Fase 5 — UI custom React (parte ibrida)
- React+Vite su FastAPI: pagine import, dashboard, insight, **gestione category pending**; look moderno.
- **Trigger di avvio** (parte quando almeno una è vera): (a) si vuole integrare il layer AI (Fase 6); (b) serve un'azione **write** nell'UI (import, gestione pending) non supportata da Metabase read-only; (c) si vuole esporre fuori rete locale.
- **Milestone**: UI custom affianca/sostituisce Metabase per il flusso quotidiano.

### Fase F-DEBT — Risoluzione debito tecnico F5

Fase di manutenzione, posizionata dopo F5 e prima di F6. Ha chiuso i 5 debiti tecnici emersi dalla
review finale di F5 (nessuno bloccante per l'uso corrente). Registro storico consolidato in
ADR-0020/0021/0022 (il precedente `docs/TECH-DEBT.md` è stato dismesso dopo la chiusura di tutti
e 5 i debiti). Nessuna milestone di prodotto — solo hardening/pulizia.

- **Task DEBT-01 — Tiebreaker deterministico su `GET /transactions`**
  - Descrizione: `list_transactions` (`backend/app/routers/transactions.py`) ordina solo per
    `Transaction.date.desc()`; aggiungere una chiave secondaria stabile (`Transaction.id.desc()`)
    per garantire paginazione deterministica quando più righe condividono la stessa data.
  - Acceptance criteria: query ordina per `(date desc, id desc)`; test di regressione che inserisce
    ≥3 transazioni con data identica e verifica che l'ordine sia stabile su chiamate ripetute e che
    nessuna riga sia duplicata/saltata attraversando `page`/`page_size`.
  - Effort: **S**.

- **Task DEBT-02 — Favicon servita correttamente in produzione**
  - Descrizione: `frontend/index.html` referenzia `/favicon.svg`, non raggiungibile in produzione
    perché fuori dal mount `/assets` (il catch-all SPA lo intercetta e ritorna `index.html`).
    Estendere il mount statico in `backend/app/main.py` per servire anche gli asset di root
    (`favicon.svg`, eventuali altre icone) prima del catch-all, oppure spostare l'icona dentro
    `frontend/public` con path coerente col build Vite. Rimuovere `frontend/public/icons.svg` se
    resta non referenziato (asset morto) o wireggiarlo se serviva a uno scopo dimenticato.
  - Acceptance criteria: `curl -I http://localhost:8000/favicon.svg` (container di produzione)
    ritorna `200` con `Content-Type: image/svg+xml`, non `text/html`; nessun asset dichiarato in
    `index.html` rimane 404/servito come SPA fallback.
  - Effort: **S**.

- **Task DEBT-03 — Riconciliazione versione React nel piano**
  - Descrizione: solo documentale. Il piano F5 e la narrativa di design citano "React 18", ma lo
    scaffold Vite (Task 5) ha generato `react@^19.2.7` (default npm al momento dell'esecuzione).
    Aggiornare `docs/superpowers/plans/2026-07-15-f5-react-ui.md` (o l'ADR-0019 in
    `docs/DECISIONS.md`, a seconda di dove vive la dicitura) per riflettere la versione reale
    shippata, con nota sul perché (default scaffold, non una scelta esplicita).
  - Acceptance criteria: nessuna menzione residua di "React 18" in riferimento al codice F5
    effettivamente committato; DEBT-03 chiuso dopo l'aggiornamento del piano citato.
  - Effort: **S**.

- **Task DEBT-04 — Fix proxy Vite dev su `/import`**
  - Descrizione: `frontend/vite.config.ts`'s `server.proxy` fa match per prefisso su `/import`,
    intercettando anche la navigazione diretta/reload della SPA su quella route (non solo le
    chiamate API `POST /import/*`). Restringere il pattern di proxy a path più specifici (es. solo
    `^/import/(my-finance|historical/.*)$` invece del prefisso nudo `/import`) così che un reload
    su `/import` (la pagina) non collida col backend. Verificare che tutti gli altri path proxati
    (`/transactions`, `/accounts`, `/insights`, `/categories`, `/backup`, `/health`) non abbiano lo
    stesso problema di collisione con route SPA — al momento nessuno di questi ha un nome di pagina
    identico (`/conti`, `/backup` sì potenzialmente collide con `/backup` — verificare esplicitamente
    anche questo durante il task).
  - Acceptance criteria: `npm run dev` + reload diretto del browser su `http://localhost:5173/import`
    e su `http://localhost:5173/backup` servono la SPA (non un JSON di errore dal backend); tutte le
    chiamate API esistenti verso quei prefissi continuano a funzionare (regressione manuale sulle
    pagine Import/Backup).
  - Effort: **M** (richiede verificare ogni path proxato per lo stesso pattern di collisione, non
    solo `/import`).

- **Task DEBT-05 — Pulizia worktree stale `f4-backup`**
  - Descrizione: `.git/worktrees/f4-backup` genera un warning innocuo `Permission denied` ad ogni
    commit (probabile lock OneDrive). Investigare la causa (processo/handle che tiene il lock),
    tentare `git worktree prune`; se il prune fallisce per lo stesso lock, documentare il workaround
    (es. chiudere OneDrive temporaneamente, o `rm -rf` manuale della directory se `prune` non basta).
  - Acceptance criteria: `git commit` non produce più il warning `failed to delete
    '.git/worktrees/f4-backup'`; `git worktree list` non mostra riferimenti residui.
  - Effort: **S**.

**Milestone F-DEBT**: tutti e 5 i task chiusi (evidenze nella sezione "Stato avanzamento" sotto e in
ADR-0020/0021/0022), nessuna regressione sulle funzionalità F1-F5 esistenti.

### Fase 6 — Plugin AI: query NL sui propri dati (N-F11)

Spec: `docs/superpowers/specs/2026-07-18-f6-ai-nl-query-design.md` (rev. 2, allineata al codice).
Piano: `docs/superpowers/plans/2026-07-18-f6-ai-nl-query.md`. Decisioni: **ADR-0023**.
Sottoagente: `ai-agent`. Esecuzione in Subagent-Driven Development, come F5.

Scope: query in linguaggio naturale in **sola lettura** su aggregati e transazioni grezze filtrabili.
Adapter provider-agnostico con unico adapter concreto Gemini (SDK `google-genai`, Interactions API,
function calling a loop manuale). Stateless: nessuna memoria conversazione, **nessuna Alembic
revision**. La categorizzazione AI delle pending resta fuori scope (sottosistema write, spec propria).

- **M6.1 — Service layer insights con filtri**: le 4 funzioni di aggregazione escono da
  `routers/insights.py` verso `services/insights.py` con filtri opzionali (`date_from`, `date_to`,
  `account`, `type`); `GET /insights` diventa wrapper e senza parametri resta identico a oggi (i 5
  test esistenti passano invariati). Prerequisito del layer AI, ma utile di per sé.
- **M6.2 — Tool registry read-only**: `list_transactions`, `get_insights`, `get_accounts`,
  `get_categories`, wrapper sulle query esistenti, zero SQL duplicato. Nessun tool di scrittura
  raggiungibile dal modello (ADR-0023 p.4). Guardrail: cap righe con troncamento dichiarato, cap
  iterazioni loop, timeout HTTP.
- **M6.3 — Adapter Gemini + endpoint**: `AIProvider` astratto, adapter concreto, `POST /ai/query`
  montato **prima** del catch-all SPA. Provider non configurato → 4xx esplicito, app invariata.
- **M6.4 — Settima pagina React "Assistente AI"** su `/assistente-ai`, con la **traccia dei tool
  chiamati** sempre visibile accanto alla risposta (i numeri restano ricontrollabili).
- **Milestone F6**: domanda in linguaggio naturale sui propri dati con la propria chiave, risposta
  **verificata numericamente** contro i totali noti del dataset (F2: 331 transazioni, uscite
  9937.70 €, entrate 19497.14 €), tool di scrittura irraggiungibili dal modello, suite pytest verde.

### Fase 7 — Portabilità Raspberry Pi
- Build multi-arch (`arm64`), test risorse (valutare peso Metabase → eventuale switch a sola UI React), tuning scheduler.
- **Milestone**: stesso `docker compose up` gira su Raspberry.

**Metodo per fase**: ricerca best practice → carica skill/agenti adatti → scrivi ADR → implementa → traccia evidenze/scelte in `docs/DECISIONS.md`.

---

## 4. Evoluzione futura
- Esposizione fuori rete locale → reverse proxy + auth (oggi rimandato, ADR aperto).
- Automazione ingestion (watcher cartella Drive → import senza upload manuale).
- Multi-valuta piena (colonne My Finance già la supportano).
- Budget/forecast: soglie per categoria + alert scostamento.
- Categorizzazione assistita AI delle transazioni pending.
- Export aggiuntivi (Parquet) per analisi avanzate.

---

## 5. Domande — RISOLTE

1. **Storico da che anno** → solo **2026** (dry-run e import).
2. **Categorie non combacianti** → sempre mappate via `category_map`; drift gestito con **reconciliation queue** (`category_pending` + UI assegnazione + backfill). Vale per import one-time e upload futuri.
3. **Conto** → colonna `Conto` mantenuta dall'app; storico xls → tutto a `principale`; nuovi conti ignoti importati **as-is** (no pending, rinomina in dashboard) — scelta più semplice delle categorie, registrata come ADR.
4. **Bonifici/Transfer** → **esclusi**. `type` a 2 valori.
5. **Backup trigger** → manuale (pulsante) sempre; automatico solo all'avvio se attivato dall'utente. Piano corretto (Fase 4).
6. **Esposizione** → locale per ora; auth/reverse proxy rimandati. ADR aperto.
7. **Cadenza** → manuale per ora; automazione da Drive rimandata. ADR aperto.

---

## Governance & continuità (deliverable trasversali)

Artefatti da creare e **mantenere sempre allineati** (regola: chiudere ogni sessione aggiornandoli):

- **`CLAUDE.md`** — **unica fonte di verità**. Contiene: descrizione progetto, stack, comandi one-click, mappa fasi con stato, link a DECISIONS.md/SECURITY.md, elenco sottoagenti di progetto e quando usarli, puntatore a questo piano.
- **`docs/DECISIONS.md`** — ADR di ogni scelta (SQLite, WAL, FastAPI, Alembic, Metabase pinnato/disaccoppiato, replica atomica, conti as-is, transfer esclusi, esposizione locale, backup manuale/startup).
- **`docs/SECURITY.md`** — gestione secrets e credenziali.
- **Sottoagenti di progetto** — richiamati in CLAUDE.md, collegati a skill superpower generale; uno per dominio (ingestion, schema/migrazioni, dashboard, backup, frontend React).

### Stato avanzamento (sezione viva — aggiornare a ogni fine sessione)

| Fase | Stato | Note / evidenze |
|------|-------|-----------------|
| F0 Fondazione/sicurezza/ADR | ☑ fatto (2026-07-12) | Scaffolding completo; compose valido; pre-commit hook blocca secret e lascia passare file legittimi; Alembic rev 0001 applicata (5 tabelle base); sintassi backend OK. 12 ADR scritti. 4 sottoagenti creati. |
| F1 Ingestion My Finance | ☑ fatto (2026-07-13) | Migrazione 0002 (`category_raw` + `category_pending`, schema-agent). Parser Spese/Entrate per nome colonna (Bonifici ignorato), dedup hash batch, category/account reconciliation, `POST /import/my-finance`, `GET/POST /categories(/pending)`, replica atomica best-effort (ADR-0004). ADR-0013 scritto. Verificato E2E con export reale (`ru.innim.my_finance`): 1° upload 51 importate (46 spese + 5 entrate) / 0 duplicati / 18 categorie pending; 2° upload stesso file → 0 importate / 51 duplicati (idempotenza); resolve pending "Alimentari" → backfill 10 transazioni. Verifica indipendente (fuori dal sottoagente) con TestClient: numeri combacianti. |
| F2 Migrazione storico (dry-run) | ☑ fatto (2026-07-14) | Adapter un-pivot (`master_sheet_parser.py`, ADR-0015) + `POST /import/historical/dry-run` (DB effimero) + `POST /import/historical/commit` (DB live). Dry-run verificato su file reale: would_import=331 (309 spese + 22 entrate), 222 scartate (204 vuote, 12 Totale%, 6 marcatori mese), 20 categorie pending, quadratura mensile diff=0.0 su tutti i 12 mesi. **Validato manualmente dall'utente contro il foglio originale (R1) → commit reale eseguito**: `import_batch_id=1`, 331 transazioni su `data/portfolio.db`. Verifica indipendente via SQL diretto: `PRAGMA integrity_check`=ok, 331 transazioni (309 expense/9937.70€ + 22 income/19497.14€), somme mensili identiche al dry-run, 331 hash_dedup distinti (0 collisioni), conto unico `principale`, replica atomica creata (`replica/portfolio_replica.db`, ADR-0004). Archiviazione del foglio Google originale: passo manuale dell'utente (in corso, fuori dallo scope del codice). |
| F3 Dashboard Metabase | ☑ fatto (2026-07-14) | Docker Desktop verificato attivo; immagine `metabase/metabase:v0.62.4` verificata con `curl` incluso (nessun fix healthcheck necessario). Stack avviato (`docker compose up -d`), entrambi i servizi `healthy`. Bug scoperto e risolto durante il setup: connessione SQLite alla replica falliva (`SQLITE_CANTOPEN`) perché il DB live è in WAL e apre file ausiliari `-wal`/`-shm` anche in lettura, impossibile su mount realmente read-only — fix in `app/db.py` (`refresh_read_only_replica()`: checkpoint + copia + `PRAGMA journal_mode=DELETE` sulla copia), **ADR-0017**. Datasource SQLite configurata in Metabase via API (API key gruppo Administrators, non committata, in `.env` gitignored) puntata a `/replica/portfolio_replica.db` (mount `:ro`); sync completo, tutte le tabelle rilevate. Dashboard "Personal Portfolio - Overview" con 4 card native SQL: entrate/uscite per mese, spesa per categoria (`category_raw`), trend saldo cumulato mensile, saldo per conto. Verifica dati: uscite totali card = 9937.70€, entrate totali = 19497.14€, saldo cumulato finale = 9559.44€ — combaciano esattamente coi totali del commit F2. Verificato "import in corso non blocca query": write-lock `BEGIN IMMEDIATE` tenuto sul DB live per 8s, query Metabase sulla replica risposta in 0.2s con dati corretti; integrità DB live confermata post-test (331 transazioni invariate). |
| F4 Backup automatico | ☑ fatto (2026-07-14) | Sviluppato con subagent-driven-development (4 task TDD, backup-agent): `backend/app/backup.py` (dump SQLite via `sqlite3.Connection.backup()` online API — non `shutil.copy2`, evita il workaround di ADR-0017; export `.xlsx` flat leggibile; retention locale; restore), `backend/app/drive.py` (upload/retention Google Drive, Service Account **opzionale** — degradazione graceful se `/secrets/service_account.json` assente, timeout 30s sul client), `backend/app/routers/backup.py` (`POST /backup`, `GET /backup`, `POST /backup/restore` con `confirm: true` obbligatorio), job `BACKUP_ON_STARTUP` su thread non-bloccante in `main.py`. ADR-0018. Prima suite pytest committata nel repo (17 test, tutti su comportamento reale — nessun mock salvo il fake Drive service per `apply_drive_retention`). 3 review-loop durante l'implementazione: (1) Task 3 review → fix `get_drive_service()` dentro il blocco `try` di `run_backup()` (SA malformata non doveva sfuggire al best-effort); (2) Task 4 review → **path traversal** in `POST /backup/restore` (filename tipo `portfolio_backup_../../../etc/x.db` aggirava il check `startswith`/`endswith`) risolto con `os.path.basename()` + containment check, test di regressione aggiunto; (3) review finale whole-branch (opus) → timeout Drive client (`AuthorizedHttp`, 30s) e job d'avvio spostato su `threading.Thread` daemon (non bloccava più il boot come richiesto da ADR-0018 punto 6). Verifica E2E reale (container Docker isolato `f4-verify`, non il `pp-backend` di produzione già attivo): transazione sintetica → `POST /backup` → `row_count=1`, `drive_uploaded=false` con `drive_error` esplicativo (nessuna SA montata, degradazione graceful confermata) → file `.db`+`.xlsx` reali su `/backups` → DB live svuotato → restore senza `confirm` → 400 → restore con filename path-traversal → 400 → restore reale con `confirm:true` → 200, dati ripristinati esatti (`12.34 EUR`, `TestVerificaF4`), replica Metabase rigenerata, `/health` ok post-restore. Debito noto non bloccante (single-dev locale, documentato non implementato): nessun pre-restore snapshot di sicurezza, nessun `PRAGMA integrity_check` sul backup prima di restore, collisione timestamp se due backup nello stesso secondo, `.xlsx` orfano (senza `.db` associato) non ripulito dalla retention. |
| F5 UI React | ☑ fatto (2026-07-16) | Sviluppato con subagent-driven-development (10 task, react-ui-agent), branch `f5-ui-react`, **mergiato su master 2026-07-16 (PR#1, merge commit 7fdeb00)**. Backend (Task 1-4): router `GET/PUT/DELETE /transactions` (PATCH limitato a comment/tag/category_id, mai hash_dedup), `GET/PATCH /accounts`, `GET /insights` (trend mensile, breakdown categoria, saldo cumulato, saldo per conto), montati in main.py. Frontend (Task 5-9): scaffold Vite+React+TS+TanStack Query+React Router+Tailwind v3+Recharts (Tailwind pinnato a v3.4.19, baseUrl omesso da tsconfig.app.json per incompatibilità TS 6/TS5101 — deviazioni verificate e confermate corrette in review), 6 pagine (Dashboard, Transazioni, Import, Categorie pending, Conti, Backup) con read+write reale su FastAPI, conferma esplicita a 2 step per le operazioni distruttive (delete transazione, restore backup — verificato che nessun code path bypassa il click di conferma). Ogni task review-clean (0 Critical, Important residui solo su hardening non bloccante, es. tipizzazione PUT body). Integrazione Docker (Task 10): `backend/Dockerfile` riscritto multi-stage (stage `frontend-build` con `npm ci && npm run build`, stage runtime Python copia `frontend_dist`), `docker-compose.yml` build context esteso a root, `backend/app/main.py` serve la SPA su `/` con fallback client-side routing per path non-API, `.dockerignore` aggiunto. Verifica E2E reale eseguita in questa sessione (non solo build): `docker compose build backend && docker compose up -d` → `pp-backend`+`pp-metabase` healthy; suite pytest completa 35/35 passing; verifica browser live su `http://localhost:8000` (container di produzione, non dev server): tutte le 6 pagine navigate via sidebar con dati reali (331 transazioni da F2), **hard refresh diretto su `/transazioni` conferma il fallback SPA (nessun 404)**, `/docs` Swagger UI raggiungibile, Metabase su `:3000` raggiungibile e invariata (pagina di login normale, ADR-0004/ADR-0019 rispettati), zero errori console in tutti i test. Review finale whole-branch (opus) ha trovato 2 Important (gate dry-run storico bypassabile cambiando file; mutation silenziose senza feedback errore) — entrambi fixati (commit 7e9cd67) e ri-verificati (re-review + test live) prima del merge. Bug dev-only scoperto (non blocca produzione, tracciato come DEBT-04): il proxy Vite dev fa match per prefisso su `/import`, quindi una navigazione diretta/reload su `http://localhost:5173/import` (non un click sidebar) ritorna 404 dal backend invece della SPA — non riproducibile in produzione perché FastAPI fa match per path esatto. Stato dettagliato, ledger task-per-task ed evidenze complete: `.superpowers/sdd/progress.md`. |
| F-DEBT Risoluzione debito tecnico F5 | ☑ fatto (2026-07-16) | Tutti e 5 i task chiusi, registro storico consolidato in ADR-0020/0021/0022 (`docs/TECH-DEBT.md` dismesso dopo chiusura). DEBT-05 (worktree stale): `rm -rf .git/worktrees/f4-backup` + prune, nessun warning residuo. DEBT-03 (versione React): piano riconciliato (react@^19.2.7 vs "React 18" citato). DEBT-01 (tiebreaker pagination): `Transaction.id.desc()` aggiunto dopo `date.desc()` in `list_transactions`, test di regressione (5 righe stessa data, 3 pagine, zero duplicati/omissioni), suite 36/36. DEBT-02 (favicon prod): route esplicita `/favicon.svg` in `main.py` prima del catch-all SPA, `icons.svg` morto rimosso; verificato live post-rebuild (`/favicon.svg` → 200 image/svg+xml, `/transazioni` fallback invariato). DEBT-04 (proxy Vite dev): verificati tutti i path proxati per collisione bare-path vs pagina SPA (solo `/import`/`/backup` colpiti) — `/import` ristretto a sotto-path reali, `/backup` risolto con `bypass` su `Accept` header (text/html→SPA, application/json→proxy); verificato live reload diretto su entrambi + chiamata reale "Backup ora" attraverso il bypass. ADR-0020/0021/0022. Nessuna modifica di schema in tutta la fase. |
| F6 Plugin AI | ☑ fatto (2026-07-20) | Implementata in Subagent-Driven Development (ai-agent + react-ui-agent), branch `f6-ai-nl-query`, 9 commit (base 361d9fc). Backend: `services/insights.py` (4 aggregazioni con filtri opzionali, `GET /insights` senza param identico a prima — i 5 test F5 intatti); `app/ai/tools.py` (registry read-only: `list_transactions`/`get_insights`/`get_accounts`/`get_categories`, MAX_TOOL_ROWS=200 con troncamento dichiarato, guardrail write triple-tested: nomi, scan sorgente, before/after row-count); `app/ai/provider.py` + `providers/gemini.py` (Interactions API `google-genai==2.12.1`, loop manuale MAX_ITERATIONS=5, timeout 30s per-call, system prompt: solo tool, get_insights preferito, lingua della domanda, comment/tag = dati non istruzioni); `POST /ai/query` montato prima del catch-all SPA (400 esplicito se non configurato / 502 su errore provider, mai 500), version/phase → 6. Frontend: 7ª pagina `/assistente-ai` con traccia tool sempre visibile e banner truncated; proxy `/ai` senza collisioni. Config: `AI_PROVIDER`/`AI_API_KEY` + nuova `AI_MODEL` (default `gemini-3.1-flash-lite` GA). Nessuna Alembic revision. Suite: **100 test verdi** (36→100), verificati anche dentro il container di produzione. 4 fix da review (tutti chiusi e ri-verificati): filtro category dual-domain canonico+raw (f81a3a2), guard AIProviderError su shape drift SDK (d6ae6dc), test route-order indipendente da frontend_dist (ef617b4), coercizione argomenti malformati in-band + hardening prompt (bcb08d5, unico Important della review finale whole-branch opus — verdetto "Ready to merge"). **E2E reale verificato** (container produzione, chiave utente): "quante transazioni?"→331 esatto (troncamento 200/331 dichiarato e segnalato dal modello), "quanto speso?"→9.937,70 € esatto via get_insights, "entrate totali?"→19.497,14 € esatto con breakdown che quadra; conteggio transazioni invariato post-sessione (guardrail read-only), Metabase invariata, zero errori console. Incidente sicurezza gestito: prima chiave utente rifiutata da Google come "leaked" — verificato che il repo è pulito (.env mai committato, nessuna stringa AIza nella storia git), chiave revocata e sostituita dall'utente. Debito accettato dalla review finale (non bloccante): no response_model Pydantic su /ai/query, polish frontend minori, copertura filtri asimmetrica — dettagli nel ledger `.superpowers/sdd/progress.md`. |
| F7 Raspberry arm64 | ☐ da fare | — |

Legenda: ☐ da fare · ◐ in corso · ☑ fatto/verificato.

### Prompt di ripresa sviluppo — SEZIONE VIVA (minimalista, aggiornare a ogni fase)

Da incollare a start di una nuova sessione Claude. Tenuto corto di proposito (risparmio token). **Aggiornare la riga "Fase corrente" a ogni avanzamento.**

```
Progetto "Personal Portfolio" (finanza personale, Docker). Leggi CLAUDE.md = fonte di verità.
Fase corrente: F7 — Raspberry Pi arm64, DA INIZIARE (nessun design ancora).
F0-F6 + F-DEBT completate. F6 implementata e verificata E2E sul branch f6-ai-nl-query
(review finale whole-branch passata, "Ready to merge"): verificare con `git log`/`git branch`
se il merge su master è già avvenuto prima di proseguire.

F7 in breve (ARCHITECTURE.md §3 Fase 7): build multi-arch linux/arm64, test risorse su
hardware reale (valutare peso Metabase v0.62.4 ~763MB/JVM → eventuale skip + sola UI React,
alternativa già prevista da ADR-0004/0016), tuning scheduler. Milestone: stesso
`docker compose up` gira su Raspberry Pi.
Ciclo fase: best practice → spec/brainstorm → ADR in DECISIONS.md PRIMA del codice →
piano → implementa (Subagent-Driven Development come F5/F6) → verifica su hardware →
aggiorna Stato avanzamento + CLAUDE.md + questa riga "Fase corrente".

Contesto tecnico utile per F7: backend python:3.12-slim multi-stage (node:20-slim per build
frontend); dipendenze google-api-python-client/google-auth/google-genai = client HTTP puri,
impatto arm64 atteso trascurabile (da confermare, nota ADR-0023 p.2); Metabase multi-arch
verificato in ADR-0016. Layer AI (F6): POST /ai/query, tool registry read-only, config
AI_PROVIDER/AI_API_KEY/AI_MODEL (mai GEMINI_API_KEY).

Regole sempre valide: no schema change senza alembic revision; no secret committato;
dubbi → chiedi; PUT /transactions/{id} edita SOLO comment/tag/category_id (mai hash_dedup);
nessun tool di scrittura esposto al modello AI (ADR-0023).
```

## Verifica (a fine implementazione, per fase)
- **F0**: `git add .` di prova con una fake key JSON → pre-commit hook blocca; DECISIONS.md/SECURITY.md presenti.
- **F1**: upload `.xlsx` reale → conteggio righe SQLite = righe Spese/Entrate (Bonifici esclusi); re-upload → conteggio invariato; categoria ignota → riga in `category_pending`.
- **F2**: report dry-run mostra somme per mese/categoria e righe scartate coerenti; somma importata == `Totale` foglio (quadratura); nessuna riga sommario importata come transazione.
- **F3**: Metabase legge replica R/O; import in corso non blocca le query; dashboard coerente su mese campione.
- **F4**: backup manuale + all'avvio → file su Drive + locale; restore su DB pulito ripristina i conteggi attesi.
- **F5/F6/F7**: smoke test UI + gestione pending, query AI su dataset noto, `docker compose up` su target arm64.
