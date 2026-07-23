# Personal Portfolio — Fonte di Verità (CLAUDE.md)

App **dockerizzata** per finanza personale: unifica master Google Sheet (storico) + export mensile
"My Finance" (.xlsx) in un'unica sorgente normalizzata a livello transazione, con dashboard, backup
automatico e predisposizione AI. **One-click** Docker (Windows ora, Raspberry arm64 futura). No vendor lock-in.

## Documenti canonici (leggere sempre questi)
- **Piano architetturale + Stato avanzamento + Prompt ripresa**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Decisioni (ADR)**: [docs/DECISIONS.md](docs/DECISIONS.md)
- **Sicurezza secret**: [docs/SECURITY.md](docs/SECURITY.md)

## Stack
- Backend: Python 3.12 + FastAPI (ETL: pandas/openpyxl). Unico writer sul DB.
- Storage: SQLite in **WAL mode** (`data/portfolio.db`). Migrazioni: **Alembic**.
- Dashboard: Metabase (Fase 3) su **replica read-only** atomica; affiancata da UI React (Fase 5, container singolo servito da FastAPI).
- Backup: Service Account Google Drive + locale (Fase 4).
- Infra: `docker-compose.yml`, volumi persistenti, secrets a runtime.

## Regole non negoziabili
1. **Nessun secret committato** — hook `pre-commit` content-based attivo (ADR-0011, SECURITY.md).
   Protegge **il repository**.
2. **Nessuna modifica di schema senza `alembic revision`** (ADR-0003). Numero e `down_revision` si
   fissano **al merge**, non alla scrittura: `alembic heads` deve dare **una sola** riga.
3. **FastAPI unico writer** su SQLite; Metabase legge solo la replica (ADR-0004).
4. **Hash dedup** solo su campi stabili, mai editabili (ADR-0005). Unica eccezione tracciata: il
   suffisso `#n` delle ripetizioni manuali volute (ADR-0028) — l'importer confronta sempre l'hash
   base.
5. In caso di dubbi/incoerenze → **fermarsi e chiedere all'utente**.
6. **`/settings` è l'unico punto di configurazione esposto all'utente** (ADR-0027): nessuna pagina
   si costruisce un proprio pannello di impostazioni. Vincolo di prodotto permanente.
7. **Nessun valore di secret o di identificatore di risorsa privata attraversa un endpoint o l'UI**
   (ADR-0027, blacklist `AI_API_KEY` · `GOOGLE_SA_KEY_PATH` · `GDRIVE_BACKUP_FOLDER_ID`). Perimetro
   diverso dalla regola 1: quella difende il repository, questa la **superficie HTTP** — un secret
   può essere fuori dai commit e uscire lo stesso da una risposta JSON. `GOOGLE_API_KEY` **non
   esiste** in questo progetto e non va introdotta.
8. **Nessuna route SPA condivide un path esatto con un endpoint API** (ADR-0033): pagine in
   italiano (`/transazioni`, `/impostazioni`, `/backup-restore`…), endpoint in inglese. Verificato
   da test di regressione su `SPA_ROUTES` in `main.py`, non dalla disciplina.

## Mappa fasi (dettaglio + stato vivo in docs/ARCHITECTURE.md)
F0 fondazione/sicurezza/ADR · F1 ingestion My Finance · F2 migrazione storico (dry-run, dal 2026) ·
F3 dashboard Metabase · F4 backup · F5 UI React · F-DEBT debito tecnico · F6 AI · F7 Raspberry arm64 ·
**F8-F14 roadmap in 3 blocchi**.

**Fase corrente: BLOCCO A — F8 dark mode + F9 settings, in esecuzione.** Branch
`f8-f9-theme-settings` aperto (2026-07-21); spec di dettaglio
[docs/superpowers/specs/2026-07-21-f8-f9-detail-spec.md](docs/superpowers/specs/2026-07-21-f8-f9-detail-spec.md)
e piano [docs/superpowers/plans/f8-f9-implementation-plan.md](docs/superpowers/plans/f8-f9-implementation-plan.md)
approvati (task T0-T14). **Stato al 2026-07-22: T0-T12 completati e committati, 3/3 checkpoint
umani superati** (dettaglio task-per-task in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
righe F8/F9 della tabella "Stato avanzamento" e "Prompt di ripresa sviluppo"). Riprendere da
**T13** (pagina `/impostazioni` reale), poi T14 (chiusura).

F0-F6 + F-DEBT completate (F6: query NL read-only `POST /ai/query` + pagina `/assistente-ai`,
ADR-0023, config `AI_PROVIDER`/`AI_API_KEY`/`AI_MODEL` — **mai** `GEMINI_API_KEY`, **mai**
`GOOGLE_API_KEY`).

**F7 ◐ parcheggiata in attesa hardware, non bloccante per F8+.** Preparazione completa e verificata
da desktop (branch `f7-raspberry-arm64`: gate arm64 PASS, compose unico con tuning universale per
Pi 4 4GB, runbook [docs/RASPBERRY-PI.md](docs/RASPBERRY-PI.md) pronto, ADR-0024/0025). Riprende solo
all'arrivo del Pi, con i punti aperti P1-P4 registrati in ARCHITECTURE.md.

**Roadmap F8-F14** (pianificata 2026-07-21, spec
[docs/superpowers/specs/2026-07-21-f8-f14-roadmap-design.md](docs/superpowers/specs/2026-07-21-f8-f14-roadmap-design.md),
ADR-0026 → ADR-0033):
- **Blocco A** `f8-f9-theme-settings` — F8 dark mode (token semantici CSS, Tailwind v3 `class`,
  chartConfig condiviso) · F9 endpoint `/settings` + pagina `/impostazioni` (tabella key/value,
  whitelist/blacklist) · ADR-0033 routing (pagina Backup → `/backup-restore`). Spec e piano di
  dettaglio approvati 2026-07-21.
- **Blocco B** `f11-f12-f13-transactions` — F11 `POST /transactions` manuale · F12 filtri avanzati e
  FTS5 · F13 dashboard aggiuntive. **Gate bloccante M12.0**: build arm64 + `SELECT fts5_version()`
  prima del merge.
- **Blocco C** `f10-f14-drive-chat` — F10 `POST /backup/gdrive-test` (probe write→read→delete) ·
  F14 storicità chat AI (`chat_sessions`/`chat_messages`, modello sempre read-only).

Ordine vincolante: **A prima di B**. C è indipendente funzionalmente, **non** nella catena Alembic.

## Sottoagenti di progetto (`.claude/agents/`)
Attivarli quando parte la fase relativa. Collegati alla skill superpower generale.
- **ingestion-agent** — parser My Finance, adapter un-pivot master, category mapper, dedup (F1/F2).
- **schema-agent** — modelli SQLAlchemy, Alembic revision, integrità schema (ogni fase che tocca il DB).
  Prossime: `settings` (F9), FTS5 `transactions_fts` + trigger (F12), `chat_sessions`/`chat_messages`
  (F14). Numero e `down_revision` si fissano **al merge** — `alembic heads` deve dare una sola riga.
- **dashboard-agent** — Metabase, replica read-only atomica, dashboard/insight (F3). Esteso a F13:
  pannelli React complementari (saldo cumulato, cash flow, donut categorie, trend risparmio,
  confronto mese su mese, KPI), tutti su `chartConfig` condiviso. Metabase resta invariata.
- **backup-agent** — dump SQLite + export .xlsx, Google Drive Service Account, restore (F4). Esteso a
  F10: `POST /backup/gdrive-test` con probe write→read→delete, errori sanitizzati, cleanup
  best-effort (ADR-0031).
- **react-ui-agent** — frontend React+Vite+TS (TanStack Query, Tailwind/shadcn, Recharts), endpoint
  FastAPI read+write (`/transactions`, `/accounts`, `/insights`), affianca Metabase (F5). Esteso a
  F8-F13: sistema temi (token semantici, ThemeProvider, script anti-FOUC), pagina `/settings`, form
  di inserimento manuale, filtri avanzati con stato nell'URL, pannelli dashboard.
- **ai-agent** — layer AI: adapter provider-agnostico (unico adapter Gemini), tool registry
  **read-only**, loop tool-use manuale, `POST /ai/query`, service layer insights con filtri (F6,
  ADR-0023). Esteso a F14: persistenza conversazioni, finestra di contesto troncata **nell'adapter**,
  endpoint sessioni. **Il modello non deve mai poter scrivere sul DB**: la persistenza è scritta dal
  router, mai da un tool.

## Comandi
```bash
# Avvio one-click
docker compose up -d
# Health backend
curl http://localhost:8000/health
# Migrazioni (dentro backend/)
alembic upgrade head
alembic revision -m "descrizione"   # ogni schema change
# Attivare il pre-commit hook (dopo clone)
git config core.hooksPath .githooks
```

## Struttura repo
```
backend/         FastAPI + Alembic + modelli
docs/            ARCHITECTURE.md · DECISIONS.md · SECURITY.md
.githooks/       pre-commit (secret scanner)
.claude/agents/  sottoagenti di progetto
data/ replica/ backups/ secrets/   volumi runtime (gitignored)
```
