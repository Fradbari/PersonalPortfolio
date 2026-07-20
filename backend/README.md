# Backend

Backend FastAPI (Python 3.12): unico writer sul DB SQLite del Personal Portfolio.

## Struttura cartelle

```
app/
  main.py            entrypoint FastAPI, monta i router e il backup di avvio
  db.py               connessione e sessione SQLite (WAL mode)
  models.py            modelli SQLAlchemy
  config.py            settings (pydantic-settings)
  backup.py            orchestrazione backup (dump SQLite + export .xlsx)
  drive.py              integrazione Google Drive (Service Account)
  routers/              endpoint FastAPI (accounts, ai, backup, categories, imports, insights, transactions)
  services/              logica di dominio (es. insights.py)
  ai/                     provider AI (Gemini), tool registry read-only
  ingestion/               parser My Finance e master sheet, riconciliazione/dedup
alembic/                    migrazioni schema DB
tests/                       test pytest
Dockerfile
requirements.txt
requirements-dev.txt
```

## Comandi

Avvio locale (senza Docker):
```bash
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Migrazioni Alembic:
```bash
alembic upgrade head
alembic revision -m "descrizione"   # ogni schema change
```

Test:
```bash
pytest
```

## Regole non negoziabili

- **FastAPI unico writer** su SQLite; Metabase legge solo la replica (ADR-0004).
- **Nessuna modifica di schema senza `alembic revision`** (ADR-0003).
- **Hash dedup** solo su campi stabili, mai editabili (ADR-0005).

## Approfondimenti

- Piano architetturale + stato avanzamento: [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)
- Decisioni (ADR): [../docs/DECISIONS.md](../docs/DECISIONS.md)
