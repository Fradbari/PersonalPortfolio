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
| Backup Google Drive | **OAuth utente** (refresh token, scope `drive.file`, ADR-0035; la Service Account iniziale è dismessa) |
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
- **N-NF6** Sicurezza: key AI e credenziali Google (oggi token OAuth, ADR-0035) fuori dal repo, **con enforcement** (vedi C3).
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
- Dump SQLite + export "in chiaro" `.xlsx` → locale + Drive (OAuth utente dal rimedio ADR-0035; in origine Service Account).
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
- Build multi-arch (`arm64`), test risorse (valutare peso Metabase → eventuale switch a sola UI React). (Tuning scheduler: descoped in fase di design F7 — YAGNI, spec 2026-07-20; `BACKUP_ON_STARTUP` opzionale già esistente basta.)
- **Milestone**: stesso `docker compose up` gira su Raspberry.

> **Nota (2026-07-21)**: F7 è **parcheggiata in attesa dell'hardware**, non abbandonata. Resta ◐ e
> **non è bloccante per F8+**: le fasi successive procedono su desktop. Quando il Pi 4 4GB sarà
> disponibile, la fase riprende dal runbook `docs/RASPBERRY-PI.md`, che è già pronto. Vedi anche
> "Punti aperti dipendenti dall'hardware Pi" più sotto (P1-P4) e il gate M12.0 di F12, che esiste
> proprio per non far arrivare sul Pi una migrazione che lì fallirebbe.

### Fasi F8-F14 — Roadmap in 3 blocchi (pianificate 2026-07-21)

Spec: `docs/superpowers/specs/2026-07-21-f8-f14-roadmap-design.md`.
Decisioni: **ADR-0026 → ADR-0032**. Ogni blocco produrrà la propria spec di dettaglio e il proprio
piano implementativo quando parte, come F5/F6/F7.

| Blocco | Branch | Fasi | Alembic | Agenti |
|---|---|---|---|---|
| **A — Fondamenta UI** | `f8-f9-theme-settings` | F8 dark mode, F9 settings | tabella `settings` | react-ui-agent, schema-agent |
| **B — Superficie transazioni** | `f11-f12-f13-transactions` | F11 inserimento, F12 filtri, F13 dashboard | FTS5 | react-ui-agent, schema-agent, dashboard-agent |
| **C — Integrazioni** | `f10-f14-drive-chat` | F10 GDrive test, F14 chat AI | tabelle chat | backup-agent, ai-agent, schema-agent, react-ui-agent |

Ordine vincolante: **A prima di B** (F12/F13 consumano i token colore di F8 e la pagina di F9). C è
indipendente **funzionalmente**, ma **non** nella catena Alembic: numero e `down_revision` si
fissano **al merge**, non alla scrittura — chi mergia per secondo rebasa sulla head reale.
`alembic heads` deve sempre restituire **una sola** riga (ADR-0029, sezione 8 della spec).

#### Blocco A

**F8 — Dark mode globale** (ADR-0026)
- **M8.1** Token semantici in `frontend/src/index.css` (`:root` + `.dark`, HSL triplo) e
  `darkMode: 'class'` in `tailwind.config.js`, con `theme.extend.colors` che li mappa a utility.
- **M8.2** ThemeProvider (`light|dark|system`) + **script inline anti-FOUC** in `index.html`, che
  applica la classe prima del bundle.
- **M8.3** Conversione delle 31 classi colore hardcoded su 11 file; `button.tsx` e `alert-dialog.tsx`
  per primi.
- **M8.4** `frontend/src/lib/chart-config.ts` condiviso; spariscono i **6** esadecimali di
  `Dashboard.tsx` (rettifica ADR-0026: due sulla stessa riga). *Rettifiche spec di dettaglio*:
  colori chart come **stringhe** `hsl(var(--chart-N))` (non `getComputedStyle`);
  `ChartContainer`/`ChartTooltip` **non** si portano — basta `contentStyle` nel config.
- **Milestone F8**: 7 pagine navigate in dark e light senza un elemento illeggibile, grafici
  leggibili su nero, nessun flash bianco al reload, toggle persistente.

**F9 — Pagina Settings centralizzata** (ADR-0027)
- **M9.1** Tabella `settings` key/value (`key` PK, `value`, `updated_at`).
- **M9.2** `GET /settings` (whitelist + `secrets_status` con solo `{configured: bool}`),
  `PUT /settings` (solo whitelist). Precedenza **DB > env > default**.
- **M9.3** Whitelist iniziale con il momento di applicazione dichiarato per chiave.
- **M9.4** Blacklist permanente: chiavi AI/Drive mai leggibili né scrivibili, con test automatico.
- **M9.5** Ottava route: pagina **`/impostazioni`**, endpoint `/settings` (rettifica ADR-0027 via
  ADR-0033 — path esatto condiviso = bug hard-refresh, già colpito `/backup` in produzione); ogni
  secret come badge "configurato / non configurato". Nel Blocco A rientra anche la rinomina della
  pagina Backup a `/backup-restore` (ADR-0033, nessun redirect).
- **Milestone F9**: il tema salvato sul DB sopravvive al cambio di browser; nessun valore di secret
  è ottenibile da alcun endpoint; test di blacklist verde.

#### Blocco B

**F11 — Inserimento manuale transazione** (ADR-0028)
- **M11.1** `POST /transactions` (introdotto da F11): `source='manual'`, `import_batch_id=NULL`,
  `category_raw` derivato. Nessuna revision.
- **M11.2** Dedup: 409 con la transazione gemella; forzatura con `allow_duplicate: true` →
  `hash_dedup = <hash>#<n>`. L'importer confronta **sempre** l'hash base. Calcolo di `n` e insert
  nella **stessa transazione serializzata** (`BEGIN IMMEDIATE`) + retry singolo su `IntegrityError`.
- **M11.3** Validazione doppia; **lookup esplicita del `category_id` → 404 prima** di derivare
  `category_raw` (altrimenti NOT NULL violato → 500 opaco).
- **M11.4** Form React in `/transazioni` con invalidazione delle query.
- **Milestone F11**: la transazione manuale compare in lista/dashboard/Metabase; doppio invio → 409;
  forzatura → due righe; re-import della stessa riga → nessun duplicato aggiuntivo.

**F12 — Filtri avanzati e ricerca full-text** (ADR-0029)
- **M12.0** **Gate arm64 bloccante**: `docker buildx --platform linux/arm64` + nel container
  emulato `PRAGMA compile_options` (`ENABLE_FTS5`) e una `CREATE VIRTUAL TABLE ... USING fts5` di
  prova (mai `SELECT fts5_version()`: non esiste). Se fallisce, il blocco non si mergia.
- **M12.1** Tabella virtuale `transactions_fts` + 3 trigger + popolamento; check FTS5 fail-fast
  all'avvio + rebuild dell'indice a ogni avvio (`lifespan`); **rebuild dopo `POST /backup/restore`**.
- **M12.2** Filtri `date_from/date_to/category_id/account/amount_min/amount_max/type/q`;
  `year_month` mantenuto per compatibilità.
- **M12.3** `group_by=category|month|account` con subtotali, paginazione invariata (ADR-0020).
- **M12.4** Filtri in `useSearchParams` → permalink; alimentano la `queryKey` di TanStack Query.
- **Milestone F12**: ricerca per parola nel commento; filtri riflessi nell'URL e ripristinati al
  reload; il restore di un backup non rompe la ricerca.

**F13 — Dashboard avanzate** (ADR-0030)
- **M13.1** Estensione di `services/insights.py` (**lo stesso modulo di F6**, mai un secondo):
  firme backward-compatible, i 5 test F5 passano **invariati**, e il tool AI `get_insights` rientra
  nel criterio di merge.
- **M13.2** Sei pannelli su `chartConfig` condiviso: saldo cumulato · cash flow mensile · spese per
  categoria (donut) · trend risparmio · confronto mese su mese · 4 KPI card. Metabase **invariata**.
- Vincolo di nomenclatura: la parola "patrimonio" è vietata in UI, tooltip, titoli e campi API — il
  dato è un **saldo cumulato**.
- **Milestone F13**: ogni numero quadra con i totali noti del dataset F2; tutti i pannelli leggibili
  in dark.

#### Blocco C

**F10 — Backup GDrive e test di connettività** (ADR-0031)
- **M10.1** `POST /backup/gdrive-test`: probe reale write → read → delete (con scope `drive.file`
  una `list` non prova la scrittura). Credenziali lette solo da `config.py`.
- **M10.2** Esiti diagnostici distinti; messaggio Google **sanitizzato** (campi strutturati di
  `HttpError` + redazione letterale dei valori noti).
- **M10.3** Pulsante "Test connessione GDrive" nella pagina Backup; il folder id non è mai mostrato.
- **M10.4** Cleanup **best-effort**: nome `portfolio_gdrive_probe_<timestamp>.probe`, prefisso
  distinto da quello dei backup, rimozione orfani a inizio di ogni esecuzione.
- **Milestone F10**: SA valida → verde e nessun residuo; cartella non condivisa → messaggio che
  nomina la causa.

**F14 — Storicità chat AI e memoria** (ADR-0032)
- **M14.1** `chat_sessions` + `chat_messages`; `tools_json` = TEXT con **lo stesso shape** già
  restituito da `POST /ai/query`.
- **M14.2** `AIProvider.answer(question, session, history=None)` — breaking change: **prima** si
  aggiorna il fake provider e si scrive il test (che deve fallire), **poi** si cambia la firma. Il
  troncamento vive **nell'adapter**, non nel router.
- **M14.3** `session_id` opzionale su `POST /ai/query`; `GET /ai/sessions`, `GET /ai/sessions/{id}`;
  `DELETE /ai/sessions/{id}` senza conferma, `DELETE /ai/sessions` con `confirm: true`.
- **M14.4** UI: elenco sessioni, ripresa conversazione, "Azzera storico" a 2 step; traccia tool
  sempre visibile.
- **M14.5** Modello **sempre read-only**: la persistenza è scritta dal router, mai da un tool.
- **Milestone F14**: follow-up ("e il mese prima?") risposto correttamente; conversazione ripresa
  dopo riavvio container; azzeramento completo; conteggio transazioni invariato.

**Metodo per fase**: ricerca best practice → carica skill/agenti adatti → scrivi ADR → implementa → traccia evidenze/scelte in `docs/DECISIONS.md`.

---

## 4. Evoluzione futura

Voci **non** coperte da F8-F14 (per quelle vedi la roadmap sopra). Ognuna richiede spec e ADR propri
quando partirà.

- **Patrimonio netto reale**: modello asset/passività con snapshot periodici (immobili,
  investimenti, mutui). Oggi il DB ha solo transazioni, quindi F13 mostra un **saldo cumulato** e la
  parola "patrimonio" è vietata in UI (ADR-0030). Questo è il sottosistema che la sbloccherebbe.
- **Tool AI `search_transactions`**: con l'indice FTS5 introdotto da F12 (ADR-0029) un quinto tool
  read-only di ricerca testuale diventa banale da aggiungere. Fuori scope in F14 per contenere
  l'egress verso il provider (ADR-0032 p.7).
- **Categorizzazione assistita AI delle transazioni pending**: è un sottosistema **write**, quindi
  fuori dal perimetro read-only di ADR-0023/0032. Spec e ADR propri, con un meccanismo di conferma
  umana prima di qualunque scrittura.
- Esposizione fuori rete locale → reverse proxy + auth (oggi rimandato, ADR-0009 invariato).
- Automazione ingestion (watcher cartella Drive → import senza upload manuale).
- Multi-valuta piena (colonne My Finance già la supportano).
- Budget/forecast: soglie per categoria + alert scostamento.
- Export aggiuntivi (Parquet) per analisi avanzate.
- Migrazione a Tailwind v4 (`@theme inline`, OKLCH) e inizializzazione della CLI shadcn: scartata in
  F8 come cambio di build system nel mezzo di 7 feature (ADR-0026 p.3), rivedibile con ADR proprio.

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
| F7 Raspberry arm64 | ◐ in corso (preparazione completata 2026-07-20, attesa hardware) | Target confermato dall'utente: **Pi 4 4GB**, hardware non ancora disponibile → verifica su hardware reale rimandata (la fase si chiude ☑ solo con la checklist runbook eseguita sul Pi). Preparazione fatta e verificata da desktop (branch `f7-raspberry-arm64`, SDD): **Gate portabilità arm64 PASS** — wheel check fail-fast `pip download --only-binary=:all: --platform manylinux2014_aarch64` su requirements: 58/58 wheel aarch64 (pandas/numpy/cryptography/pydantic-core/greenlet incluse), zero sdist; `docker buildx --platform linux/arm64 --load` → immagine Architecture=arm64; smoke QEMU: alembic+uvicorn partono, `/health` 200 (incidente non-bug: MSYS path mangling di Git Bash su `-e DB_PATH`, risolto con `MSYS_NO_PATHCONV=1`); manifest `metabase/metabase:v0.62.4` include linux/arm64 (ri-conferma ADR-0016). **Compose tuning universale** (9767b75): healthcheck backend 30s/10s/5/90s, metabase 30s/15s/10/900s, `JAVA_OPTS=-Xmx1g`, `mem_limit: 2g`, log rotation json-file 10m/3 su entrambi i servizi, version/phase → 7; verificato live su desktop (compose config valido, suite 100/100, `docker compose up -d --build` → entrambi healthy, `/health` phase "7", Metabase :3000 ok). **Runbook `docs/RASPBERRY-PI.md`** (c7fccee): setup Pi da zero, comando standard unico `docker compose up -d --build`, checklist in 2 parti (validazione full-stack = milestone; misura Metabase ADR-0025 con soglie ≤10min avvio / ≤1.5GB RAM steady / warm <10s / no OOM 24h), Modello A (skip = raccomandazione `stop metabase`, mai topologia alternativa), troubleshooting, nota egress. ADR-0024/0025. Nessuna Alembic revision, nessuna logica di business toccata (solo metadata version/phase). |

| F8 Dark mode globale — **Blocco A** | ☑ fatto (2026-07-23) | ADR-0026 + rettifiche. Eseguito in subagent-driven-development (react-ui-agent), review dopo ogni task, 0 Critical/Important residui. **T8**: 22 token semantici (non 21 — correzione di conteggio, la lista concreta della spec ne ha sempre avute 22) in `:root`/`.dark` (`frontend/src/index.css`), HSL triplo, `darkMode:'class'` + `theme.extend.colors` con `<alpha-value>` (`tailwind.config.js`); baseline palette shadcn "slate" + chart palette standard shadcn + `success`/`warning` custom coerenti con gli usi ambra/verde preesistenti — valori concreti in ADR-0026 addendum. **T9**: `theme-provider.tsx` (`light\|dark\|system`, chiave localStorage `personal-portfolio:theme`), persistenza doppia DB (`GET/PUT /settings`, chiave `theme`) fonte di verità + localStorage cache anti-FOUC; degradazione verificata (backend irraggiungibile non blocca mai il render, solo `console.warn`) sia empiricamente sia leggendo `api.ts` in review. Script anti-FOUC in `index.html`, `<title>Personal Portfolio</title>`. **T10**: `chart-config.ts` (`chartColors`/`chartGrid`/`chartAxis`/`chartTooltip`, stringhe `hsl(var(--chart-N))`, mai `getComputedStyle`); 6 esadecimali di `Dashboard.tsx` mappati; verificato **a schermo dal controller** che i colori cambiano davvero al toggle tema (non solo al mount). **T11**: `button.tsx`/`alert-dialog.tsx`/`App.tsx`/`Sidebar.tsx` convertiti; `bg-black/50` dell'overlay preservato come unica eccezione dichiarata. **T12**: 7 pagine convertite per esaurimento — grep finale su tutto `frontend/src` dà **una sola riga residua** (l'eccezione dell'overlay), verificato indipendentemente da reviewer e controller. **CHECKPOINT UMANO 3**: automatico (console pulita, inversione colori corretta) + giudizio utente 2026-07-22 — *"la palette va bene, ma dovrà essere ritestata quando sarà davvero implementato l'intero stile nero (compreso lo sfondo)"*: approvazione provvisoria, la ri-validazione finale rientra nei criteri di accettazione manuali di fine piano (8 pagine × 2 temi, incluso `/impostazioni` reale post-T13). **Difetto scoperto fuori piano e chiuso** (commit `0f965b9`): il proxy Vite dev (`vite.config.ts`) fa match per prefisso — la chiave `/backup` intercettava anche `/backup-restore` (route SPA rinominata in T6a), stessa classe di difetto ADR-0033 riemersa nel solo proxy di sviluppo; fix con `bypass` scoperto sulla sola route SPA, verificato via curl diretto (non riproducibile in produzione). **T13** (pagina `/impostazioni` reale, commit `b1f9487`, react-ui-agent): sostituito il placeholder di T6a con le 6 sezioni whitelist (Aspetto/Dashboard esterne/Parametri ETL/Backup/AI) + Secret; `theme` scritto solo via `useTheme()` (nessuna PUT /settings duplicata per quella chiave), ogni campo mostra `applies_when`+`source` da `GET /settings`, i 3 secret sono solo badge configurato/non-configurato + nome variabile `.env`, mai un valore o un input — verificato dal reviewer riga per riga sul diff, 0 Critical/Important. **T14** (chiusura): `version="0.1.0-phase9"` + `/health` `phase: "9"` in `backend/app/main.py`, `alembic heads` = 1 riga (`0003`), suite 144 test verdi confermata post-bump. **Mergiato su `master`** (merge commit `bcbdb18`, 2026-07-23). **Audit visivo post-merge** (branch `f8-f9-post-merge-audit`, commit `2b290ef`): grep colori hardcoded ripetuto su tutto `frontend/src` — pulito (stesso unico residuo noto, l'overlay); 8 pagine (le 7 esistenti + `/impostazioni`) navigate in light e dark via browser reale, zero errori console; contrasto WCAG dei token calcolato analiticamente su ogni coppia foreground/background — **1 difetto reale trovato**: `--warning-foreground` non aveva mai avuto una variante `.dark` (era rimasto il valore scuro di `:root`), contrasto 1.22:1 nell'unico punto d'uso (`AiAssistant.tsx:61`, banner di troncamento cronologia AI) — praticamente invisibile. Fix: `38 92% 85%` in `.dark`, verificato via calcolo WCAG (14.14:1) e via browser reale sul container rigenerato (`getComputedStyle` sull'elemento con le classi esatte). Suite **148 test verdi** post-fix, `alembic heads` invariato. **Fix successivo** (branch
`fix-input-dark-contrast`, commit `37f93ac`): utente segnala con screenshot reale su
`/impostazioni` input illeggibili in dark (sfondo bianco fisso, mai legato al tema, su 7 siti
`<input>` del frontend — `Settings.tsx`, `Accounts.tsx`, `Transactions.tsx` x2,
`CategoriesPending.tsx`). Root cause: nessun input dichiarava `bg-*`/`text-*`, ereditavano lo
sfondo default del browser per i controlli form. Fix architetturale in un solo punto
(`index.css @layer base`, dopo `body{}`): `input:not([type='checkbox']):not([type='radio']):not([type='file']),
textarea, select { @apply bg-background text-foreground; }` — invece di patchare i 7 siti uno
per uno (pattern già sfuggito due volte separate). Verificato via browser reale sul container
rigenerato: dark `bg=rgb(2,8,23)` `color=rgb(248,250,252)` (leggibile); light invariato
(`bg=white` `color=quasi-nero`). 148 test verdi, alembic heads invariato. Blocco A **chiuso,
mergiato e pushato su `origin/master`** (`37f93ac`). |
| F9 Settings centralizzata — **Blocco A** | ☑ fatto (2026-07-23) | ADR-0027 + rettifiche. Eseguito in subagent-driven-development (schema-agent), review dopo ogni task. **T1**: modello `Settings` (`key` PK, `value`, `updated_at`) + revision `0003_settings.py` (`down_revision="0002"`, da riconfermare al merge). **T2**: `services/settings.py` — `WHITELIST` a 6 chiavi (`theme`, `metabase_url`, `ai_history_max_turns`, `import_min_year`, `backup_retention`, `backup_on_startup`) con type/default/env_attr/applies_when; `BLACKLIST` a 3 chiavi; `get_effective(key, session=None)` precedenza DB>env>default con sessione autonoma se `None`; `set_values` transazione singola. **T3**: router `GET/PUT /settings`, import con alias `settings_router` (evita shadowing di `app.config.settings`), blacklist a 3 asserzioni, PUT su chiave illegale → 400 messaggio identico (anti-enumerazione). **T4**: bug latente chiuso — `parse_master_sheet_xlsx(file, sheet_name, sheet_year)` entrambi obbligatori, `grep "settings"` sul parser → 0 match. **T5**: `backup_retention`/`backup_on_startup` riagganciati via `get_effective`; fix di review: lettura `backup_on_startup` nel lifespan avvolta in try/except best-effort (stesso stile di `_run_startup_backup`), altrimenti un DB non migrato avrebbe bloccato il boot. **T6b**: `mount_spa()` estratto, `SPA_ROUTES` a livello di modulo (8 voci, verificate contro `App.tsx` reale). **T7**: test routing ADR-0033 (invariante + comportamento HTTP); fix di review: Test 1 usa `app.main.app.routes` reale invece di una lista router mantenuta a mano (evita drift silenzioso su router futuri). Alembic: `0003 (head)`, una sola riga. Suite: **144 test verdi** (100 pre-esistenti invariati + 44 nuovi). **CHECKPOINT UMANO 1**: superato, `GET/PUT /settings` ispezionato a mano. **CHECKPOINT UMANO 2**: superato sul **container di produzione reale** (rebuild), le 4 URL della tabella routing verificate via browser (`/settings`→JSON, `/impostazioni`→HTML, `/backup`→JSON, `/backup-restore`→HTML). **T13**: pagina `/impostazioni` reale costruita sul contratto `GET/PUT /settings` esistente, nessuna modifica al router/service richiesta — verificato che il payload (6 chiavi whitelist + `secrets_status` a 3 chiavi) copriva già tutti i campi richiesti dalla UI. **T14**: `phase`/`version` → 9, `alembic heads` = 1 riga, suite 144 verdi. **Mergiato su `master`** (merge commit `bcbdb18`, 2026-07-23); audit visivo post-merge non ha toccato F9 (nessun residuo di colore nelle pagine settings, vedi riga F8 per il dettaglio del fix trovato altrove). Suite **148 test verdi** (144 + 4 aggiunti nella review finale whole-branch per un badge secret sempre "configurato"). Blocco A **chiuso, mergiato e pushato su `origin/master`** (`37f93ac`). |
| F11 Inserimento manuale — **Blocco B** | ☑ fatto (2026-07-27) | Backend: `POST /transactions` (T7, commit `123fb08`+fix `c85cac7`+emendamento CP1 `6b29898`). Ordine ADR-0028: lookup `category_id`→404, poi `category_raw`/hash/insert. Ordinale `#n` con retry su `IntegrityError` (mai `BEGIN IMMEDIATE`, rettifica p.5). **CP1 (checkpoint umano) superato con un emendamento dell'utente**: una data oltre `MAX_FUTURE_DAYS` (1 giorno) non è più un rifiuto 422 ma un avviso 409 `reason:"future_date"` con via d'uscita `confirm_future_date:true` — stessa meccanica del duplicato (`reason:"duplicate"`); terzo `reason:"ordinal_exhausted"` senza via d'uscita. Frontend: `ApiError` (T8), primitive UI (T9), form manuale + dialog sui 3 `reason` (T10, commit `91971b6`+fix `edf6b30` dopo 2 Important di review — un retry post-409 poteva scrivere un payload diverso da quello mostrato a schermo; il backdrop del dialog azzerava l'intero form su un trascinamento di selezione testo). Dettaglio review task-per-task in `.superpowers/sdd/progress.md`. |
| F12 Filtri avanzati + FTS5 — **Blocco B** | ☑ fatto e mergiato (2026-10-14, `ab9c360`) | **Gate arm64 sull'immagine finale: GO** (2026-10-14, `pp-backend:arm64-verify`, HEAD `19ad2f7`, DB vuoto scratch): alembic 0001→0005, `/health` 200 `phase:"13"`, `0.1.0-phase13` in OpenAPI, `ENABLE_FTS5` presente, con `transactions_fts` assente warning all'avvio e nessun crash. Post-merge su master: 252 test verdi, `alembic heads` = `0005`. Review finale whole-branch: 0 Critical, fix committati (rebuild FTS + check `ENABLE_FTS5` all'avvio, invalidazione `['insights']`). **Gate M12.0 arm64+FTS5: GO** (T0) — dettaglio storico: bug trovato nello script di verifica del piano (`SELECT fts5_version()` non è una funzione SQL reale), riverificato con `PRAGMA compile_options`+virtual table reale. Migration `0004` indici (T2) + `0005` FTS5/trigger (T3, `content='transactions'` su `comment,tag,category_raw,account`) fatte, review-approvate dopo un fix Critical (il test permanente dei trigger non rilevava un UPDATE trigger insert-only — corretto con `integrity-check` a due argomenti). `services/search.py` (T5), filtri/`group_by`/`q` su `GET /transactions` (T6) e filtri avanzati in `useSearchParams` (T11, commit `228d760`+fix `9f839b7` — il 503 deliberato di FTS5 mancante spariva dietro una tabella vuota silenziosa, ora un errore visibile) fatti. Nato il primo `conftest.py` del progetto (fixture `fts_engine`, Strategia A con `EnvironmentContext` esplicito) — **T4 è stato assorbito da T3**, non serve più come task separato. **T15 fatto (2026-09-05, ADR-0034)**: `POST /backup/restore` ora fa copia → `alembic upgrade head` (`upgrade_schema_to_head()` in `backup.py`, `command.upgrade` con `NullPool`) → `rebuild_fts_index` → refresh replica, quattro try/except distinti dentro un `threading.Lock` di modulo; body con `migrations_applied:N` e `schema_note` se N>0. Chiude D5 (restore non faceva girare Alembic) e retroattivamente i backup pre-F9. **Footgun evitato**: `_alembic_config()` NON passa `alembic.ini` a `Config` — altrimenti `env.py` chiamerebbe `fileConfig(..., disable_existing_loggers=True)` a ogni restore, silenziando i logger dell'app (rilevato dal test del lifespan). 4 nuovi test (D5 con backup 0002→settings creata + `version_num`=head sul file, no-op da head, failure path migration=caso 1 e rebuild=caso 2 distinti). Suite 245 verdi. |
| F13 Dashboard avanzate — **Blocco B** | ☑ fatto e mergiato (2026-10-14, `ab9c360`) | Pianificata 2026-07-21 (ADR-0030), spec/piano 2026-07-25 (task T12-T14). Nessuna revision. **Rettifica ADR-0030 p.3 applicata**: `GET /insights/panels` (T13, commit `0a4fb75`) è endpoint **nuovo**, `GET /insights` resta byte-identico (i suoi 5 test invariati) e `ai/tools.py` non toccato — verificato dal reviewer sul diff, non sul solo report. **Rettifica additiva ADR-0026 applicata**: `--chart-6`/`--chart-7` (T12, commit `13d616f`), indici 0-4 di `chartColors` invariati byte per byte. **CP1b (checkpoint umano) superato**: verifica dal vivo del controller su copia scratch del DB reale (mai `data/portfolio.db`) — `kpi` incrocia esattamente i totali noti F2 (income 19497.14€, expense 9937.70€), `months` tronca senza riempire, donut ≤7 con "Altro" reale, `month_over_month` si ancora davvero all'ultimo mese con dati (giugno) e non al mese corrente wall-clock. **Due punti che il contratto congelato non decideva alla lettera, confermati esplicitamente dall'utente**: `month_over_month` ignora la finestra `months`/`date_from` di default (resta ancorato ai dati reali più recenti); `month_over_month` è solo-uscite come `category_donut`. Sei pannelli React (T14, commit `0e1760f`+fix `0092227`) fatti: **replace** dei 3 pannelli sovrapposti di `Dashboard.tsx` con le versioni nuove da `/insights/panels` (saldo cumulato ora windowed, non più all-time), **keep** "Saldo per conto" (nessun equivalente nel nuovo contratto), **add** trend risparmio/confronto mese su mese/KPI. Un giro di review ha trovato "patrimonio" **dentro il commento che lo vietava** (non tracciato da git al momento del check dell'implementer — bug del metodo, non solo del codice), corretto e riverificato via confronto hash dei blob. "Saldo cumulato", mai "patrimonio" (verificato da grep a radice di parola, non dalla disciplina — ADR-0030). Metabase invariata. **CP2 superato (2026-09-04)**: giudizio visivo da browser reale confermato dall'utente — 7 pannelli leggibili in dark, wording corretto, `--chart-6/7` non collidono, il dialog del 409 mostra la gemella. Era l'ultimo checkpoint umano del blocco. |
| F10 Backup GDrive + test — **Blocco C** | ☑ fatto e mergiato (`55e2b79`, 2026-10-21); T10 + fix review finale mergiati (`c18a86c`, 2026-10-23) | Branch `f10-f14-drive-chat` (pushato), mergiato su `master` prima di T10 (`55e2b79`). `POST /backup/gdrive-test` probe write→read→delete con 12 esiti tipizzati (ADR-0031 + rettifiche 2026-10-14/19/20), errori sanitizzati con `redact()` anche in `POST /backup` (D7). **T7b** (`9d276a1`, aggiunto a CP2): `GET /backup/last` (ultimo esito in memoria, anche del backup all'avvio) e folder id vuoto → nessun upload (G2). **T8** (`07c2df3`): UI su `/backup-restore` (test solo al click + banner "Ultimo backup"). **`ece6dfe`**: esito `api_disabled` (403 `accessNotConfigured`, emerso al probe reale). **CP2 chiuso (2026-10-20)**: probe reale dal container → `quota_exceeded`/`storageQuotaExceeded` (SA senza quota su Drive personale): F10 funziona e il messaggio indica il rimedio; **rimedio (Shared Drive o OAuth utente) = ADR separato dopo C**. Fughe in risposta/log: 0. **Chiusura (T10, 2026-10-23)**: review finale whole-branch (Opus 5.5, `git diff 749d86c...HEAD`): 0 Critical; fix I1 (`TransportError`→`network_error`), M1 (stage reale in `POST /backup`, `sa_invalid` per chiave malformata), M2 (`RefreshError` retryable→`network_error`), M3 (`at` in UTC con offset), M4 (contrasto `--success`, 5.18:1 light / 8.61:1 dark, `0d77393`), M8b. Debiti: D4 con vincolo logger `googleapiclient`, rimedio Drive (ADR separato), TODO vite, replica Metabase. |
| F14 Storicità chat AI — **Blocco C** | ☑ fatto e mergiato (`55e2b79`, 2026-10-21); T10 + fix review finale mergiati (`c18a86c`, 2026-10-23) | Revision `0006` `chat_sessions`/`chat_messages` (+ `truncated`, D8). Ordine ADR-0032 p.3 rispettato con evidenza rosso→verde in 4 tempi (ledger). Troncamento nell'adapter, persistenza solo dal router, registry read-only. **CP1 approvato (2026-10-14)**; **CP2**: Gemini reale, follow-up col contesto, ripresa dopo riavvio, restore da `0005` → chat vuote + 404. **T9** (`4994192`): UI `/assistente-ai` (sessione in URL, traccia tool per messaggio, "Azzera storico" a 2 step, 404 da `ApiError.status`), `ai_history_max_turns ≥ 0`. **CP3 chiuso (2026-10-21)**: light+dark approvati; fix `--destructive` dark (`d8a7de7`, contrasto 2.0→6.6:1, rettifica ADR-0026). Suite **331 verdi**, `alembic heads` = `0006`, `phase` `"14"` / `0.1.0-phase14`. **Chiusura (T10, 2026-10-23)**: review finale Opus 5.5 (0 Critical, 2 Important + 8 Minor): fix I2 (rilettura sessione con `populate_existing`, evita 500 se la sessione sparisce durante la risposta; test rosso→verde), M6 (adapter scarta turni assistant vuoti col loro user), M7 (`redact()` sul 502), M8a (test history + tool-call). **M5 parcheggiato** (id sessione riusato, debito 8). **Suite 347 verdi**, `alembic heads` = `0006`; upgrade head + downgrade fino a `0002` su DB scratch, 3 trigger FTS ricreati. **Gate arm64 sull'immagine finale: GO** (`pp-backend:arm64-t10`, DB vuoto scratch, `aarch64`): alembic 0001→0006, `/health` `phase:"14"`, `0.1.0-phase14` in `/openapi.json`, `ENABLE_FTS5` + virtual table fts5 di prova. |
| Rimedio Drive — OAuth utente (post Blocco C) | ◐ in corso, branch `drive-oauth` (CP2 dal vivo e merge da fare) | ADR-0035, piano `docs/superpowers/plans/drive-oauth-plan.md`. Causa: una Service Account non ha quota e non scrive in un My Drive personale (probe → `quota_exceeded`). Soluzione: OAuth utente (refresh token, scope `drive.file`), cartella creata dall'app, Service Account dismessa. Eseguito in subagent-driven-development, review dopo ogni task: **T1** `drive.py` credenziali `from_authorized_user_file` + esiti `sa_*`→`auth_*` (781996b); **T2** config/router (`GOOGLE_OAUTH_TOKEN_PATH`, default vuoto; 8cf70d4); **T3** blacklist `google_oauth_token_path` (262f14e); **T4** `scripts/gdrive_oauth_setup.py` sul host (7298c81 + fix scrittura atomica/mode 0600 `63f4202` dopo 1 Important di review); **T5** hook pre-commit con marcatori quotati (3b21201); **T6** UI Settings/Backup (f404932); **T7** documenti. Suite 382 verdi + 2 skip (POSIX-only), `alembic heads` = `0006` (nessuna revision), nessuna nuova dipendenza nell'immagine. **CP1 superato** (contratto 12 esiti, script riletto). **CP2 dal vivo superato (2026-10-23)**: probe `ok`, `drive_uploaded: true`, rotazione retention su Drive, probe `ok` dopo lo spostamento della cartella. **T8** review finale whole-branch (Opus 5.5): 0 Critical, 2 Important documentali corretti + minor. Restano: merge su ok utente, revoca della vecchia chiave SA, esito dell'avviso "app non verificata" (non registrato). |

Legenda: ☐ da fare · ◐ in corso · ☑ fatto/verificato.

**Nota su F7 (2026-07-21)**: resta ◐ **parcheggiata in attesa dell'hardware**, non abbandonata e
**non bloccante per F8+**. Riprende dal runbook `docs/RASPBERRY-PI.md`, già pronto. La sua riga
sopra è invariata: nessuna evidenza è stata riscritta.

### Punti aperti dipendenti dall'hardware Pi (P1-P4)

Decisioni **sospese per scelta**, non dimenticanze: dipendono da misure che solo il Raspberry reale
può produrre. Vanno riportate all'utente quando l'hardware arriva.

| # | Punto aperto | Perché non si decide ora | Cosa lo sblocca |
|---|---|---|---|
| **P1** | Se Metabase viene fermata sul Pi (ADR-0025, Modello A), le dashboard React di F13 smettono di essere complementari e diventano l'unica superficie analitica: ADR-0030 andrebbe rivisto con un ADR successivo | Dipende dalle soglie di ADR-0025 (avvio ≤ 10 min, RAM steady ≤ 1.5GB, warm < 10s) | Checklist parte 2 di `docs/RASPBERRY-PI.md` |
| **P2** | Copertura funzionale minima di F13 se P1 si verifica: replicare le 4 card SQL native di F3 o accettare di perderle | Discende da P1 | Esito di P1 + scelta utente |
| **P3** | Costo dei nuovi pannelli e del bundle su Pi 4 4GB: nessuna soglia di performance frontend è mai stata definita in questo progetto | Non misurabile da desktop | Sessione-Pi |
| **P4** | Punto di rientro di F7 rispetto a F8-F14: se l'hardware arriva a Blocco C in corso, F7 si inserisce subito o attende il merge del blocco | Priorità dell'utente, non scelta tecnica | Arrivo dell'hardware |

**Non è pending** il rischio FTS5 su arm64: lo chiude in anticipo il gate M12.0, bloccante per il
merge del Blocco B proprio perché non può aspettare il Pi.

### Debito tecnico aperto (post Blocco B, 2026-10-14)

Tre Minor rinviati dalla review finale del Blocco B, **non** parte del Blocco C salvo che il lavoro
di C li tocchi. Ognuno richiede un task proprio, fuori da C:

1. **Accessibilità del dialog** del form manuale (`TransactionForm.tsx`): nessun focus iniziale,
   nessun Escape, nessun focus restore, `aria-modal="true"` non davvero applicato.
2. **Errore di rete in inglese**: un backend irraggiungibile produce un `TypeError` nativo ("Failed
   to fetch") invece di un `ApiError` — livello `api.ts`, comune a tutti i consumer.
3. **Dashboard che si svuota tutta se `GET /insights` fallisce**: il fallimento della chiamata
   legacy oscura anche i sei pannelli di `/insights/panels`, che ne dipendono solo per "Saldo per
   conto".

Altri Minor accettati (20, con motivazione) e il dettaglio task-per-task sono nel ledger archiviato
in `.superpowers/sdd-archive-blocco-b/progress.md`.

### Debito tecnico aperto (post Blocco C, 2026-10-23)

Emersi durante il Blocco C e **non** risolti da esso. Ognuno richiede un task proprio.

4. **D4 — logging applicativo non configurato, INFO invisibile.** Nessun `logging.basicConfig`/
   dictConfig: i logger `app.*` ereditano il root a livello WARNING, quindi un log INFO (per esempio l'esito
   del rebuild FTS5 all'avvio, che oggi non viene emesso proprio per questo) non comparirebbe in
   `docker logs`. Compaiono solo i WARNING (es. `Probe Drive fallito in <stage>`). Non è un bug di C
   ma limita la diagnosi in produzione. Decisione D4 (2026-10-14): fuori da C.
   **Vincolo per chi lo risolverà** (review finale C): `googleapiclient.discovery` logga a DEBUG
   `URL being requested` con la query `'<folder_id>' in parents`; un livello DEBUG globale violerebbe
   la regola 7. Fissare i logger `googleapiclient` e `httplib2` ad almeno WARNING.
5. **Rimedio Drive per Service Account senza quota → ADR-0035 (in corso su `drive-oauth`).** CP2 del
   Blocco C aveva provato dal vivo che `POST /backup/gdrive-test` risponde `quota_exceeded` (403
   `storageQuotaExceeded`): una SA non può creare file in un Drive personale. Risolto sul branch con
   OAuth utente; CP2 dal vivo superato il 2026-10-23, il debito si chiude con il merge.
6. **TODO `vite.config.ts`**: il bypass del proxy per `/backup-restore` non gestisce la query
   string (`TODO(Blocco-C)`). Oggi la pagina Backup non acquisisce query string, quindi è latente.
7. **Replica Metabase non rigenerata dopo la cancellazione di chat** (`DELETE /ai/sessions` con
   `confirm: true` e `DELETE /ai/sessions/{id}`): la replica è una copia intera del DB e include `chat_sessions`/`chat_messages`;
   si rigenera solo dopo import e restore. Documentato in SECURITY.md; correggerlo è una scelta di
   prodotto (refresh costoso vs privacy), non un task meccanico.
8. **Id di sessione riusato** (review finale C, M5, parcheggiato): `chat_sessions.id` senza
   `AUTOINCREMENT`, SQLite riusa l'id appena cancellato. Scenario: tab A con `?sessione=7`, tab B
   cancella la 7 e ne apre una nuova che riprende l'id 7; un follow-up dal tab A si accoda alla
   chat di B. Rischio basso (single-user). Il rimedio è una revision `0007` con
   `sqlite_autoincrement=True`, che però non copre il restore: decisione di prodotto, non meccanica.

9. **Retention Drive: file cestinati e escape del folder id** (review finale ADR-0035, preesistente):
   `list_backup_files` in `drive.py` non filtra `trashed = false`, quindi un backup cestinato a mano
   conta ancora nella retention (restano N-1 coppie vive), e la query non fa l'escape del folder id
   come invece il probe. Task proprio, fuori dal rimedio.
10. **Hook pre-commit e SIGPIPE** (preesistente): con `set -o pipefail`, `git show | grep -Eq` può dare
    141 su file oltre ~64 KB con il marcatore all'inizio, e il file non viene bloccato. I file di
    token (< 1 KB) non sono toccati. Rimedio: `grep -Eq "$patterns" <(git show ":$file")`.
11. **Script di setup OAuth, minor rimandati**: nessun pre-check che la directory padre di `--out`
    esista (il consenso andrebbe ripetuto), nessuna guardia `--out` = `--client-secrets` con `--force`,
    nessun timeout di `run_local_server`, `google-auth-httplib2` non pinnata nello script.

Non è debito: `/impostazioni` con `-1` su `ai_history_max_turns` è bloccato dal fumetto di validazione
nativa del browser (`min=0`); il backend rifiuta comunque il valore. Accettato dall'utente.

### Prompt di ripresa sviluppo — SEZIONE VIVA (minimalista, aggiornare a ogni fase)

Da incollare a start di una nuova sessione Claude. Tenuto corto di proposito (risparmio token). **Aggiornare la riga "Fase corrente" a ogni avanzamento.**

```
Progetto "Personal Portfolio" (finanza personale, Docker). Leggi CLAUDE.md = fonte di verità.
Fase corrente: RIMEDIO DRIVE (ADR-0035) SUL BRANCH `drive-oauth`, NON ANCORA MERGIATO. Piano:
docs/superpowers/plans/drive-oauth-plan.md. T1-T7 su branch (OAuth utente, scope drive.file, cartella
creata dall'app, Service Account dismessa, esiti sa_*→auth_*, blacklist google_oauth_token_path, hook
con marcatori quotati, script scripts/gdrive_oauth_setup.py, UI, doc). 382 test verdi + 2 skip,
`alembic heads` = 0006. CP1 e CP2 superati (CP2 dal vivo 2026-10-23: probe `ok`, upload su Drive,
rotazione retention, probe `ok` dopo lo spostamento della cartella); T8 review finale Opus 5.5 fatta.
DA FARE: merge `--no-ff` su ok dell'utente (nessun push senza richiesta); l'utente revoca la vecchia
chiave SA e sistema `.env.example`; esito dell'avviso "app non verificata" non registrato; il caso
negativo (cartella creata a mano → 404) e la rotazione del token non sono stati provati dal vivo.
Base: BLOCCO C CHIUSO, MERGIATO E PUSHATO; AMBIENTE RESETTATO A 0006 VUOTO.
Codice di C su master da 55e2b79; T10 + fix della review finale con c18a86c (2026-10-23, --no-ff);
origin/master allineato. phase "14" / 0.1.0-phase14, 347 test backend verdi, `alembic heads` = 0006,
gate arm64 GO. Review finale Opus 5.5: 0 Critical, fix applicati, M5 parcheggiato (debito 8).

STATO DELL'AMBIENTE (reset del 2026-10-23, su ok esplicito dell'utente):
- Container pp-backend e pp-metabase ricostruiti con `docker compose build --no-cache && up -d`.
  DB applicativo NUOVO e VUOTO a 0006: 0 transazioni, 0 conti, 0 categorie, 0 category_map,
  0 settings (valgono i default: backup_retention 12, backup_on_startup false, tema di default),
  0 chat; tabelle chat e `transactions_fts` + 3 trigger presenti. La replica
  `replica/portfolio_replica.db` NON esiste: nasce al primo import o restore, quindi la fonte dati
  di Metabase è vuota/in errore finché non c'è un import. `metabase-data/` (dashboard) NON toccato.
- Il DB precedente (rev 0003: 514 transazioni, 3 conti, 20 categorie, 6 settings) è archiviato in
  `data/archive/portfolio-0003-20261023.db` (copia con sqlite backup API, integrity_check ok,
  gitignored). NON cancellarlo e NON migrarlo: i dati si ricaricano da zero.
- I backup già presenti in `backups/` (3 coppie .db/.xlsx: 2026-07-16, 2026-08-27, 2026-09-03) e quelli
  su Drive sono intatti. Sono schema vecchio: un restore li porta a head (ADR-0034) e SOVRASCRIVE il
  DB: non usarli per sbaglio.

PROSSIMI PASSI, in quest'ordine:
(a) CARICAMENTO DATI mese per mese, a cura dell'utente. Flusso: export My Finance .xlsx del mese →
    pagina `/import` (o `POST /import/my-finance`, campo `file`); leggono solo le schede Spese ed
    Entrate, Bonifici ignorata. Il DB parte SENZA categorie né category_map: le categorie
    del primo import finiranno TUTTE in coda pending → risolverle da `/categorie-pending` (assegna a
    una categoria canonica nuova o esistente; il backfill aggiorna le transazioni già importate e le
    importazioni future riconoscono il nome) PRIMA del mese successivo. Conti nuovi: accettati
    as-is, nessuna risoluzione. Storico dal master sheet (una tantum, dry-run poi commit) solo se
    l'utente lo vuole.
    Controlli dopo OGNI mese (la risposta riporta `imported`, `skipped_duplicates`,
    `skipped_invalid_rows`, `pending_categories`):
    1. `imported` = righe attese del mese (Spese + Entrate dell'export, senza Bonifici);
    2. `skipped_duplicates` = 0 su mese nuovo; > 0 solo se il file si sovrappone a mesi già caricati;
    3. `skipped_invalid_rows` spiegato (righe vuote in coda sono normali), altrimenti indagare;
    4. `pending_categories` risolte prima di proseguire (`GET /categories/pending` vuoto);
    5. idempotenza: ricaricare lo stesso file dà `imported` = 0 (dedup su data, importo, categoria,
       conto, tipo; mai su commento/tag);
    6. totale entrate/uscite del mese in `/` e in `/transazioni` = totali dell'export; nessun conto
       inatteso in `/conti`;
    7. conteggio `transactions` nel DB cresce esattamente di `imported` (lettura RO, mai scrivere).
    Consigliato un backup manuale (`/backup-restore` → "Backup ora") dopo ogni mese verificato.
(b) RIMEDIO DRIVE: deciso con ADR-0035 (OAuth utente) e implementato sul branch `drive-oauth`;
    CP2 e T8 fatti, resta il merge su ok utente (vedi "Fase corrente"). Procedura utente in
    docs/SECURITY.md («Backup su Google Drive»).
(c) F7 Raspberry arm64: ◐ PARCHEGGIATA in attesa hardware (Pi 4 4GB), runbook docs/RASPBERRY-PI.md e
    punti aperti P1-P4. Debiti aperti: sezioni "Debito tecnico aperto" di questo file.
VERIFICHE LASCIATE ALL'UTENTE (richiedono .env/secrets, che l'agente non legge): probe Drive da
`/backup-restore` (atteso `ok` dopo il setup OAuth di ADR-0035, `auth_missing` prima) e domanda reale a Gemini da
`/assistente-ai` sul DB popolato.

Vincoli dell'ambiente:
- .env e secrets/ sono esclusi dalla content policy aziendale per l'agente: mai leggerli, mai
  aggirare il blocco (anche un comando che nomina il path della SA viene rifiutato). Le verifiche
  che li richiedono le fa l'utente; Docker li passa via env_file / bind mount.
- Nessun MCP Docker disponibile: usare la CLI `docker`.
- I subagent di .claude/agents non hanno shell: test/build/lint li esegue il thread principale.

Trappole ancora valide:
- Gate FTS5 nella forma corretta: `PRAGMA compile_options` (`ENABLE_FTS5`) + `CREATE VIRTUAL TABLE
  ... USING fts5(...)` di prova. MAI `SELECT fts5_version()`: non esiste, falso negativo.
- `test_fts_triggers.py` è un canary: `batch_alter_table(recreate="always")` droppa i trigger FTS.
  Se "iniziasse a fallire" non invertire l'asserzione. Una migration che ricrea `transactions`
  deve ricreare anche i 3 trigger.
- `_alembic_config()` in `backup.py` NON passa `alembic.ini` a `Config` (altrimenti `fileConfig`
  silenzia i logger dell'app a ogni restore).
- Dopo `git add -A`, rifare i grep di verifica (es. `git grep -i patrimon`): un file non tracciato
  sfugge al `git grep`. Parola vietata in UI/codice: "patrimonio" (si dice "saldo cumulato").
- Git Bash/MSYS: `MSYS_NO_PATHCONV=1` coi comandi `docker run -e VAR=/path`; in un processo Python
  nativo Windows usare il prefisso inline `DB_PATH="$DB" comando`, non `export`.
- Verifiche SOLO su DB scratch (copia via sqlite backup API o DB vuoto in temp), mai su
  data/portfolio.db (DB vivo, da quando l'utente ricarica i dati). Polling su /health, non un singolo tentativo (arm64 sotto QEMU è lento).
- /health restituisce `phase` ma non `version`: la versione (0.1.0-phaseNN) sta in /openapi.json.
- Rimedio Drive per la SA senza quota (Shared Drive o OAuth utente) = ADR SEPARATO dopo C: non
  implementarlo senza ADR, non modificare F4 per aggirarlo.

Regole sempre valide: no schema change senza alembic revision; no secret committato; nessun secret
o identificatore privato leggibile da UI/API/log (ADR-0027/0031: mai folder id, path SA o chiave);
ogni impostazione esposta passa da /impostazioni; nessuna route SPA su path esatto di endpoint
(ADR-0033); dubbi → chiedi; PUT /transactions/{id} edita SOLO comment/tag/category_id; nessun tool
di scrittura esposto al modello AI (ADR-0023/0032). Catena Alembic: numero e down_revision si
fissano AL MERGE (`alembic heads` = 1 riga).

F7 Raspberry arm64: ◐ PARCHEGGIATA in attesa hardware (Pi 4 4GB), runbook docs/RASPBERRY-PI.md e
punti aperti P1-P4.

Esecuzione in subagent-driven-development: un task per subagent, review dopo ciascuno (T10 e i
gate li esegue il main).
```

## Verifica (a fine implementazione, per fase)
- **F0**: `git add .` di prova con una fake key JSON → pre-commit hook blocca; DECISIONS.md/SECURITY.md presenti.
- **F1**: upload `.xlsx` reale → conteggio righe SQLite = righe Spese/Entrate (Bonifici esclusi); re-upload → conteggio invariato; categoria ignota → riga in `category_pending`.
- **F2**: report dry-run mostra somme per mese/categoria e righe scartate coerenti; somma importata == `Totale` foglio (quadratura); nessuna riga sommario importata come transazione.
- **F3**: Metabase legge replica R/O; import in corso non blocca le query; dashboard coerente su mese campione.
- **F4**: backup manuale + all'avvio → file su Drive + locale; restore su DB pulito ripristina i conteggi attesi.
- **F5/F6/F7**: smoke test UI + gestione pending, query AI su dataset noto, `docker compose up` su target arm64.

### Verifica F8-F14 (per blocco, prima del merge)

Comuni a ogni blocco:
- `alembic heads` → **una sola** head; `alembic upgrade head` e `downgrade` fino a `0002` su DB di
  prova.
- Suite pytest completa (**148 test** dopo il Blocco A) verde e **invariata**, più i nuovi: dedup
  manuale 409/forzatura, filtri e full-text, sopravvivenza dei trigger FTS a un
  `batch_alter_table`, failure path del restore, guardrail read-only AI dopo la persistenza.
- Build del **container di produzione** e navigazione reale delle pagine (non solo dev server), in
  **dark e light**, con console pulita.
- Numeri incrociati contro i totali noti del dataset F2 (331 transazioni, uscite 9937.70 €, entrate
  19497.14 €) su ogni pannello nuovo.
- `docker compose config` valido, `/health` con `phase` aggiornata.

Per fase:
- **F8**: le 7 pagine esistenti in entrambi i temi senza elementi illeggibili; reload senza flash
  bianco; zero esadecimali residui nei componenti grafici.
- **F9**: il tema salvato sopravvive al cambio di browser; `GET /settings` non restituisce alcun
  valore blacklistato (test automatico); precedenza DB > env verificata.
- **F11**: doppio invio identico → 409 con la gemella nel corpo; forzatura → due righe distinte;
  `category_id` inesistente → **404 con `COUNT(*)` invariato**, non 500 e non 409; dopo un POST
  valido, `source='manual'` e `import_batch_id IS NULL` letti **dal DB**, non dal JSON di risposta.
  La copertura di concorrenza è **dichiarata best-effort**, non simulata: il retry è corretto per
  costruzione ma la suite copre solo il path sequenziale (rettifica del criterio originale "due
  richieste concorrenti → `#1` e `#2`, mai un 500", non verificabile con `TestClient` sincrono né
  con la fixture `StaticPool` a connessione unica).
- **F12**: **gate M12.0 bloccante** (build `linux/arm64` + `PRAGMA compile_options`/`ENABLE_FTS5` +
  virtual table fts5 di prova), eseguito come
  primo task e ripetuto sull'immagine finale; ricerca per parola nel commento; `group_by` che
  restituisce subtotali coerenti ignorando la paginazione; filtri riflessi nell'URL e ripristinati
  al reload; restore di un backup → la ricerca continua a rispondere sui dati ripristinati;
  `fts_available()` falso → **503**, mai 500.
- **F13**: i 5 test F5 su `GET /insights` passano **invariati** — in particolare
  `test_insights_empty_db_returns_empty_lists`, il più fragile perché asserisce sul body intero, il
  cui output va copiato nel ledger come evidenza; il tool AI `get_insights` restituisce gli stessi
  numeri di prima (`ai/tools.py` non si tocca); nessuna occorrenza di `patrimon` in `*.ts`/`*.tsx`.
- **F10**: manuale, una volta — Service Account reale con cartella condivisa (verde, nessun
  residuo) e con cartella non condivisa (messaggio che nomina la causa e **privo del folder id**).
- **F14**: evidenza documentata del passaggio rosso→verde sul fake provider **prima** del cambio di
  firma; follow-up conversazionale corretto; conversazione ripresa dopo riavvio container;
  azzeramento completo; conteggio transazioni invariato a fine sessione.
