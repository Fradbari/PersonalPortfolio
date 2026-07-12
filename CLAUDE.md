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
- Dashboard: Metabase (Fase 3) su **replica read-only** atomica; poi UI React (Fase 5).
- Backup: Service Account Google Drive + locale (Fase 4).
- Infra: `docker-compose.yml`, volumi persistenti, secrets a runtime.

## Regole non negoziabili
1. **Nessun secret committato** — hook `pre-commit` content-based attivo (ADR-0011, SECURITY.md).
2. **Nessuna modifica di schema senza `alembic revision`** (ADR-0003).
3. **FastAPI unico writer** su SQLite; Metabase legge solo la replica (ADR-0004).
4. **Hash dedup** solo su campi stabili, mai editabili (ADR-0005).
5. In caso di dubbi/incoerenze → **fermarsi e chiedere all'utente**.

## Mappa fasi (dettaglio + stato vivo in docs/ARCHITECTURE.md)
F0 fondazione/sicurezza/ADR · F1 ingestion My Finance · F2 migrazione storico (dry-run, dal 2026) ·
F3 dashboard Metabase · F4 backup · F5 UI React · F6 AI · F7 Raspberry arm64.
**Fase corrente: F0 (completata) → prossima F1.**

## Sottoagenti di progetto (`.claude/agents/`)
Attivarli quando parte la fase relativa. Collegati alla skill superpower generale.
- **ingestion-agent** — parser My Finance, adapter un-pivot master, category mapper, dedup (F1/F2).
- **schema-agent** — modelli SQLAlchemy, Alembic revision, integrità schema (ogni fase che tocca il DB).
- **dashboard-agent** — Metabase, replica read-only atomica, dashboard/insight (F3).
- **backup-agent** — dump SQLite + export .xlsx, Google Drive Service Account, restore (F4).

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
