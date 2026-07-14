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

### Fase 6 — Plugin AI
- Adapter provider-agnostico, API key utente da env; insight NL su dati aggregati.
- **Milestone**: query NL sui propri dati con la propria key.

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
- **Sottoagenti di progetto** — richiamati in CLAUDE.md, collegati a skill superpower generale; uno per dominio (ingestion, schema/migrazioni, dashboard, backup).

### Stato avanzamento (sezione viva — aggiornare a ogni fine sessione)

| Fase | Stato | Note / evidenze |
|------|-------|-----------------|
| F0 Fondazione/sicurezza/ADR | ☑ fatto (2026-07-12) | Scaffolding completo; compose valido; pre-commit hook blocca secret e lascia passare file legittimi; Alembic rev 0001 applicata (5 tabelle base); sintassi backend OK. 12 ADR scritti. 4 sottoagenti creati. |
| F1 Ingestion My Finance | ☑ fatto (2026-07-13) | Migrazione 0002 (`category_raw` + `category_pending`, schema-agent). Parser Spese/Entrate per nome colonna (Bonifici ignorato), dedup hash batch, category/account reconciliation, `POST /import/my-finance`, `GET/POST /categories(/pending)`, replica atomica best-effort (ADR-0004). ADR-0013 scritto. Verificato E2E con export reale (`ru.innim.my_finance`): 1° upload 51 importate (46 spese + 5 entrate) / 0 duplicati / 18 categorie pending; 2° upload stesso file → 0 importate / 51 duplicati (idempotenza); resolve pending "Alimentari" → backfill 10 transazioni. Verifica indipendente (fuori dal sottoagente) con TestClient: numeri combacianti. |
| F2 Migrazione storico (dry-run) | ☑ fatto (2026-07-14) | Adapter un-pivot (`master_sheet_parser.py`, ADR-0015) + `POST /import/historical/dry-run` (DB effimero) + `POST /import/historical/commit` (DB live). Dry-run verificato su file reale: would_import=331 (309 spese + 22 entrate), 222 scartate (204 vuote, 12 Totale%, 6 marcatori mese), 20 categorie pending, quadratura mensile diff=0.0 su tutti i 12 mesi. **Validato manualmente dall'utente contro il foglio originale (R1) → commit reale eseguito**: `import_batch_id=1`, 331 transazioni su `data/portfolio.db`. Verifica indipendente via SQL diretto: `PRAGMA integrity_check`=ok, 331 transazioni (309 expense/9937.70€ + 22 income/19497.14€), somme mensili identiche al dry-run, 331 hash_dedup distinti (0 collisioni), conto unico `principale`, replica atomica creata (`replica/portfolio_replica.db`, ADR-0004). Archiviazione del foglio Google originale: passo manuale dell'utente (in corso, fuori dallo scope del codice). |
| F3 Dashboard Metabase | ☐ da fare | — |
| F4 Backup automatico | ☐ da fare | — |
| F5 UI React | ☐ da fare | — |
| F6 Plugin AI | ☐ da fare | — |
| F7 Raspberry arm64 | ☐ da fare | — |

Legenda: ☐ da fare · ◐ in corso · ☑ fatto/verificato.

### Prompt di ripresa sviluppo — SEZIONE VIVA (minimalista, aggiornare a ogni fase)

Da incollare a start di una nuova sessione Claude. Tenuto corto di proposito (risparmio token). **Aggiornare la riga "Fase corrente" a ogni avanzamento.**

```
Progetto "Personal Portfolio" (finanza personale, Docker). Leggi CLAUDE.md = fonte di verità.
Fase corrente: F3 (F2 completata e commit reale verificato il 2026-07-14).   ← AGGIORNARE
Sottoagente da attivare: dashboard-agent (Metabase, replica read-only, ADR-0004).
Regole: no schema change senza alembic revision; no secret committato; dubbi → chiedi.
Ciclo fase: best practice → sottoagente dominio → ADR in DECISIONS.md → implementa →
verifica → aggiorna Stato avanzamento + CLAUDE.md + questa riga "Fase corrente".
```

## Verifica (a fine implementazione, per fase)
- **F0**: `git add .` di prova con una fake key JSON → pre-commit hook blocca; DECISIONS.md/SECURITY.md presenti.
- **F1**: upload `.xlsx` reale → conteggio righe SQLite = righe Spese/Entrate (Bonifici esclusi); re-upload → conteggio invariato; categoria ignota → riga in `category_pending`.
- **F2**: report dry-run mostra somme per mese/categoria e righe scartate coerenti; somma importata == `Totale` foglio (quadratura); nessuna riga sommario importata come transazione.
- **F3**: Metabase legge replica R/O; import in corso non blocca le query; dashboard coerente su mese campione.
- **F4**: backup manuale + all'avvio → file su Drive + locale; restore su DB pulito ripristina i conteggi attesi.
- **F5/F6/F7**: smoke test UI + gestione pending, query AI su dataset noto, `docker compose up` su target arm64.
