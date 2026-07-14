# F4 Backup Automatico — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dump SQLite + export `.xlsx` leggibile verso locale e Google Drive (Service
Account), retention/rotazione, restore con conferma esplicita, job opzionale
all'avvio.

**Architecture:** Nuovo modulo `backend/app/backup.py` (funzioni pure: dump SQLite via
online backup API, export xlsx, orchestrazione, retention locale, restore) +
`backend/app/drive.py` (upload/retention Google Drive, Service Account opzionale) +
`backend/app/routers/backup.py` (endpoint HTTP, stesso stile di `routers/imports.py`).
Nessuna modifica di schema DB.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, `sqlite3` (online backup API),
pandas/openpyxl, `google-api-python-client` + `google-auth` (nuove), pytest + httpx
(nuove, dev-only).

Riferimenti: `docs/superpowers/specs/2026-07-14-backup-automation-design.md`, ADR-0018
in `docs/DECISIONS.md`, `backup-agent.md`.

## Global Constraints

- Nessuna Alembic revision per F4 (nessuna modifica di schema — CLAUDE.md regola 2).
- Nessun secret committato — la Service Account key vive solo in `/secrets` (mount
  runtime, gitignored), mai letta/loggata nel codice se non per aprirla come file
  (ADR-0011).
- Naming backup: `portfolio_backup_YYYYMMDD_HHMMSS.db` + `.xlsx` (stesso timestamp,
  stesso prefisso `portfolio_backup_`).
- `settings.backup_retention` (default 12, da `.env` `BACKUP_RETENTION`) = numero di
  **coppie** `.db`+`.xlsx` mantenute, sia in locale sia su Drive.
- Drive best-effort ovunque: un fallimento (SA assente, rete, permessi) non deve mai
  far fallire il backup locale né sollevare un'eccezione non gestita — solo log
  warning + campo nella risposta endpoint (ADR-0004, ADR-0018 punto 3).
- Restore (`POST /backup/restore`) richiede `confirm: true` esplicito nel body,
  altrimenti HTTP 400 — operazione distruttiva sul DB live (ADR-0018 punto 5).
- Restore legge solo da `settings.backup_dir` locale, mai da Drive (ADR-0018 punto 5).
- Stile endpoint: coerente con `backend/app/routers/imports.py` (stesso pattern
  `try/except` best-effort per operazioni non bloccanti, stesso uso di `logger.warning`).

---

### Task 1: Dump SQLite (online backup API) + export xlsx leggibile

**Files:**
- Create: `backend/app/backup.py`
- Create: `backend/tests/test_backup_core.py`
- Create: `backend/requirements-dev.txt`

**Interfaces:**
- Produces: `dump_sqlite(source_db_path: str, dest_db_path: str) -> None`
- Produces: `TRANSACTION_COLUMNS: dict[str, str]` (nome campo SQLAlchemy → header
  colonna italiano leggibile, ordine: date, amount, currency, type, category_raw,
  account, comment, tag, source)
- Produces: `export_transactions_xlsx(engine: sqlalchemy.engine.Engine, dest_xlsx_path: str) -> int`
  (ritorna il numero di righe esportate)
- Produces: `BACKUP_PREFIX = "portfolio_backup_"`, `TIMESTAMP_FMT = "%Y%m%d_%H%M%S"`
  (costanti, riusate da Task 2/3/4)

- [ ] **Step 1: Installa le dipendenze di test**

Crea `backend/requirements-dev.txt`:

```
-r requirements.txt
pytest==8.3.4
httpx==0.28.1
```

Esegui (da worktree root, venv già presente da setup):

```bash
.venv/Scripts/python -m pip install -r backend/requirements-dev.txt
```

- [ ] **Step 2: Scrivi i test (falliranno — `app.backup` non esiste ancora)**

Crea `backend/tests/test_backup_core.py`:

```python
import os
import sqlite3
from datetime import datetime

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backup import dump_sqlite, export_transactions_xlsx
from app.db import Base
from app.models import Transaction


def _make_source_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
    conn.executemany("INSERT INTO t (val) VALUES (?)", [("a",), ("b",), ("c",)])
    conn.commit()
    conn.close()


def test_dump_sqlite_copies_rows_from_wal_source(tmp_path):
    source_path = str(tmp_path / "source.db")
    dest_path = str(tmp_path / "dump.db")
    _make_source_db(source_path)

    dump_sqlite(source_path, dest_path)

    assert os.path.exists(dest_path)
    dest_conn = sqlite3.connect(dest_path)
    try:
        rows = dest_conn.execute("SELECT val FROM t ORDER BY id").fetchall()
        assert [r[0] for r in rows] == ["a", "b", "c"]
        journal_mode = dest_conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert journal_mode == "delete"
    finally:
        dest_conn.close()


def test_dump_sqlite_dest_has_no_wal_side_files(tmp_path):
    source_path = str(tmp_path / "source.db")
    dest_path = str(tmp_path / "dump.db")
    _make_source_db(source_path)

    dump_sqlite(source_path, dest_path)

    assert not os.path.exists(dest_path + "-wal")
    assert not os.path.exists(dest_path + "-shm")


def _seed_engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'seed.db'}", connect_args={"check_same_thread": False}, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as session:
        session.add_all(
            [
                Transaction(
                    date=datetime(2026, 1, 5), amount=42.5, currency="EUR", type="expense",
                    category_raw="Alimentari", account="principale", comment="spesa",
                    source="my_finance", hash_dedup="h1",
                ),
                Transaction(
                    date=datetime(2026, 1, 10), amount=1500.0, currency="EUR", type="income",
                    category_raw="Stipendio", account="principale", comment=None,
                    source="my_finance", hash_dedup="h2",
                ),
            ]
        )
        session.commit()
    return engine


def test_export_transactions_xlsx_writes_readable_flat_sheet(tmp_path):
    engine = _seed_engine(tmp_path)
    dest_path = str(tmp_path / "export.xlsx")

    row_count = export_transactions_xlsx(engine, dest_path)

    assert row_count == 2
    df = pd.read_excel(dest_path, sheet_name="Transazioni")
    assert list(df.columns) == [
        "Data", "Importo", "Valuta", "Tipo", "Categoria", "Conto", "Commento", "Tag", "Fonte",
    ]
    assert df.loc[0, "Categoria"] == "Alimentari"
    assert df.loc[1, "Importo"] == 1500.0
```

- [ ] **Step 3: Esegui i test, verifica che falliscano**

Run (da `backend/`): `../.venv/Scripts/python -m pytest tests/test_backup_core.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.backup'`

- [ ] **Step 4: Implementa `backend/app/backup.py`**

```python
"""Dump SQLite (online backup API) + export xlsx leggibile (ADR-0018, Fase 4)."""
from __future__ import annotations

import sqlite3

import pandas as pd
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.models import Transaction

BACKUP_PREFIX = "portfolio_backup_"
TIMESTAMP_FMT = "%Y%m%d_%H%M%S"

TRANSACTION_COLUMNS = {
    "date": "Data",
    "amount": "Importo",
    "currency": "Valuta",
    "type": "Tipo",
    "category_raw": "Categoria",
    "account": "Conto",
    "comment": "Commento",
    "tag": "Tag",
    "source": "Fonte",
}


def dump_sqlite(source_db_path: str, dest_db_path: str) -> None:
    """Online backup API (ADR-0018): sicura con sorgente WAL live, nessun blocco.
    Converte la destinazione a journal_mode=DELETE cosi' il file di backup e'
    autonomo (nessun side-file -wal/-shm richiesto per riaprirlo)."""
    src_conn = sqlite3.connect(source_db_path)
    dest_conn = sqlite3.connect(dest_db_path)
    try:
        src_conn.backup(dest_conn)
        dest_conn.execute("PRAGMA journal_mode=DELETE;")
        dest_conn.commit()
    finally:
        dest_conn.close()
        src_conn.close()


def export_transactions_xlsx(engine: Engine, dest_xlsx_path: str) -> int:
    """Export flat leggibile di tutte le transazioni (N-NF3, no vendor lock-in).
    Ritorna il numero di righe esportate."""
    Session = sessionmaker(bind=engine, future=True)
    with Session() as session:
        rows = session.execute(
            select(*(getattr(Transaction, col) for col in TRANSACTION_COLUMNS)).order_by(Transaction.date)
        ).all()

    df = pd.DataFrame(rows, columns=list(TRANSACTION_COLUMNS.values()))
    df.to_excel(dest_xlsx_path, sheet_name="Transazioni", index=False, engine="openpyxl")
    return len(df)
```

- [ ] **Step 5: Esegui i test, verifica che passino**

Run: `../.venv/Scripts/python -m pytest tests/test_backup_core.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/backup.py backend/tests/test_backup_core.py backend/requirements-dev.txt
git commit -m "feat(F4): dump SQLite via online backup API + export xlsx leggibile"
```

---

### Task 2: Orchestrazione backup, retention locale, restore

**Files:**
- Modify: `backend/app/backup.py` (append — leggi il file esistente prima di modificarlo)
- Create: `backend/tests/test_backup_orchestration.py`

**Interfaces:**
- Consumes (da Task 1): `dump_sqlite`, `export_transactions_xlsx`, `BACKUP_PREFIX`,
  `TIMESTAMP_FMT`
- Produces: `@dataclass BackupResult` con campi `db_path: str`, `xlsx_path: str`,
  `row_count: int`, `timestamp: str`
- Produces: `create_backup(engine: Engine, source_db_path: str, dest_dir: str) -> BackupResult`
- Produces: `list_local_backups(dest_dir: str) -> list[str]` (lista di timestamp, es.
  `"20260714_120000"`, più recenti prima)
- Produces: `apply_local_retention(dest_dir: str, retention: int) -> list[str]`
  (ritorna i filename cancellati)
- Produces: `restore_from_backup(engine: Engine, backup_db_path: str, live_db_path: str) -> None`
  (solleva `FileNotFoundError` se `backup_db_path` non esiste)

- [ ] **Step 1: Scrivi i test (falliranno — le nuove funzioni non esistono ancora)**

Crea `backend/tests/test_backup_orchestration.py`:

```python
import os
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backup import apply_local_retention, create_backup, list_local_backups, restore_from_backup
from app.db import Base
from app.models import Transaction


def _engine_with_one_transaction(db_path):
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as session:
        session.add(
            Transaction(
                date=datetime(2026, 1, 5), amount=10.0, currency="EUR", type="expense",
                category_raw="Test", account="principale", source="my_finance", hash_dedup="h1",
            )
        )
        session.commit()
    return engine


def test_create_backup_writes_paired_db_and_xlsx(tmp_path):
    db_path = str(tmp_path / "live.db")
    dest_dir = str(tmp_path / "backups")
    engine = _engine_with_one_transaction(db_path)

    result = create_backup(engine, db_path, dest_dir)

    assert result.row_count == 1
    assert os.path.exists(result.db_path)
    assert os.path.exists(result.xlsx_path)
    assert result.timestamp in os.path.basename(result.db_path)


def test_apply_local_retention_keeps_only_most_recent_pairs(tmp_path):
    dest_dir = tmp_path / "backups"
    dest_dir.mkdir()
    for ts in ("20260101_000000", "20260102_000000", "20260103_000000"):
        (dest_dir / f"portfolio_backup_{ts}.db").write_text("x")
        (dest_dir / f"portfolio_backup_{ts}.xlsx").write_text("x")

    deleted = apply_local_retention(str(dest_dir), retention=1)

    remaining = sorted(os.listdir(dest_dir))
    assert remaining == ["portfolio_backup_20260103_000000.db", "portfolio_backup_20260103_000000.xlsx"]
    assert len(deleted) == 4


def test_list_local_backups_empty_dir_returns_empty_list(tmp_path):
    assert list_local_backups(str(tmp_path / "missing")) == []


def test_restore_from_backup_overwrites_live_db(tmp_path):
    db_path = str(tmp_path / "live.db")
    dest_dir = str(tmp_path / "backups")
    engine = _engine_with_one_transaction(db_path)

    result = create_backup(engine, db_path, dest_dir)

    Session = sessionmaker(bind=engine, future=True)
    with Session() as session:
        session.query(Transaction).delete()
        session.commit()
        assert session.query(Transaction).count() == 0

    restore_from_backup(engine, result.db_path, db_path)

    with Session() as session:
        assert session.query(Transaction).count() == 1


def test_restore_from_backup_missing_file_raises(tmp_path):
    db_path = str(tmp_path / "live.db")
    engine = _engine_with_one_transaction(db_path)

    try:
        restore_from_backup(engine, str(tmp_path / "nope.db"), db_path)
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass
```

- [ ] **Step 2: Esegui i test, verifica che falliscano**

Run: `../.venv/Scripts/python -m pytest tests/test_backup_orchestration.py -v`
Expected: FAIL con `ImportError` (le funzioni non esistono in `app.backup`)

- [ ] **Step 3: Aggiungi a `backend/app/backup.py`** (in coda al file esistente da Task 1)

```python
import glob
import os
import shutil
from dataclasses import dataclass
from datetime import datetime


@dataclass
class BackupResult:
    db_path: str
    xlsx_path: str
    row_count: int
    timestamp: str


def _timestamped_paths(dest_dir: str) -> tuple[str, str, str]:
    ts = datetime.utcnow().strftime(TIMESTAMP_FMT)
    db_path = os.path.join(dest_dir, f"{BACKUP_PREFIX}{ts}.db")
    xlsx_path = os.path.join(dest_dir, f"{BACKUP_PREFIX}{ts}.xlsx")
    return db_path, xlsx_path, ts


def create_backup(engine: Engine, source_db_path: str, dest_dir: str) -> BackupResult:
    os.makedirs(dest_dir, exist_ok=True)
    db_path, xlsx_path, ts = _timestamped_paths(dest_dir)
    dump_sqlite(source_db_path, db_path)
    row_count = export_transactions_xlsx(engine, xlsx_path)
    return BackupResult(db_path=db_path, xlsx_path=xlsx_path, row_count=row_count, timestamp=ts)


def list_local_backups(dest_dir: str) -> list[str]:
    """Timestamp (non filename) delle coppie disponibili, piu' recenti prima."""
    if not os.path.isdir(dest_dir):
        return []
    db_files = sorted(glob.glob(os.path.join(dest_dir, f"{BACKUP_PREFIX}*.db")), reverse=True)
    return [os.path.basename(f)[len(BACKUP_PREFIX):-3] for f in db_files]


def apply_local_retention(dest_dir: str, retention: int) -> list[str]:
    """Cancella le coppie .db+.xlsx piu' vecchie oltre le `retention` piu' recenti.
    Ritorna i filename cancellati."""
    timestamps = list_local_backups(dest_dir)
    stale = timestamps[retention:]
    deleted: list[str] = []
    for ts in stale:
        for ext in (".db", ".xlsx"):
            path = os.path.join(dest_dir, f"{BACKUP_PREFIX}{ts}{ext}")
            if os.path.exists(path):
                os.remove(path)
                deleted.append(os.path.basename(path))
    return deleted


def restore_from_backup(engine: Engine, backup_db_path: str, live_db_path: str) -> None:
    """Sovrascrive il DB live col backup scelto (operazione distruttiva, ADR-0018
    punto 5). L'engine viene chiuso prima della sostituzione file; la prossima
    connessione lo riapre automaticamente (il listener WAL in app.db si riattiva)."""
    if not os.path.exists(backup_db_path):
        raise FileNotFoundError(f"Backup non trovato: {backup_db_path}")

    engine.dispose()
    shutil.copy2(backup_db_path, live_db_path)
    for ext in ("-wal", "-shm"):
        stale_side_file = f"{live_db_path}{ext}"
        if os.path.exists(stale_side_file):
            os.remove(stale_side_file)
```

Nota: `Engine` è già importato da Task 1 (`from sqlalchemy.engine import Engine`) — non
duplicare l'import. Aggiungi solo gli import nuovi (`glob`, `os`, `shutil`,
`dataclass`, `datetime`) in cima al file, nella sezione import esistente.

- [ ] **Step 4: Esegui i test, verifica che passino**

Run: `../.venv/Scripts/python -m pytest tests/test_backup_orchestration.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/backup.py backend/tests/test_backup_orchestration.py
git commit -m "feat(F4): orchestrazione backup, retention locale, restore"
```

---

### Task 3: Integrazione Google Drive (upload + retention, Service Account opzionale)

**Files:**
- Create: `backend/app/drive.py`
- Modify: `backend/requirements.txt` (append)
- Create: `backend/tests/test_drive.py`

**Interfaces:**
- Consumes (da Task 1): `BACKUP_PREFIX` (`from app.backup import BACKUP_PREFIX`)
- Produces: `get_drive_service(sa_key_path: str)` → `None` se `sa_key_path` non esiste,
  altrimenti un client `googleapiclient.discovery.Resource` per `drive` v3
- Produces: `upload_file(service, file_path: str, folder_id: str) -> str` (ritorna
  l'id Drive del file caricato)
- Produces: `delete_file(service, file_id: str) -> None`
- Produces: `list_backup_files(service, folder_id: str) -> list[dict]` (ogni dict:
  `{"id": ..., "name": ...}`)
- Produces: `apply_drive_retention(service, folder_id: str, retention: int) -> list[str]`
  (ritorna i filename cancellati su Drive)

- [ ] **Step 1: Aggiungi le dipendenze**

Aggiungi in coda a `backend/requirements.txt`:

```
google-api-python-client==2.149.0
google-auth==2.35.0
google-auth-httplib2==0.2.0
```

Esegui: `.venv/Scripts/python -m pip install -r backend/requirements.txt` (da worktree root)

- [ ] **Step 2: Scrivi il test (fallirà — `app.drive` non esiste ancora)**

Crea `backend/tests/test_drive.py`:

```python
from app.drive import get_drive_service


def test_get_drive_service_returns_none_when_sa_key_missing(tmp_path):
    missing_path = str(tmp_path / "does_not_exist.json")

    service = get_drive_service(missing_path)

    assert service is None


def test_get_drive_service_returns_none_for_empty_path():
    assert get_drive_service("") is None
```

Nota: nessun test esercita `upload_file`/`delete_file`/`list_backup_files` contro
Drive reale — richiederebbero credenziali live, fuori scope (ADR-0018 punto 7,
verifica manuale in Task 4/verifica finale, coerente con la verifica manuale di
Metabase in F3).

- [ ] **Step 3: Esegui il test, verifica che fallisca**

Run: `../.venv/Scripts/python -m pytest tests/test_drive.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.drive'`

- [ ] **Step 4: Implementa `backend/app/drive.py`**

```python
"""Upload/retention Google Drive via Service Account (ADR-0008/ADR-0018).
Best-effort: nessuna Service Account montata -> get_drive_service ritorna None,
mai un'eccezione che blocchi il backup locale."""
from __future__ import annotations

import os

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app.backup import BACKUP_PREFIX

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def get_drive_service(sa_key_path: str):
    """None se la Service Account non e' montata a runtime (degradazione graceful,
    ADR-0018 punto 3)."""
    if not sa_key_path or not os.path.exists(sa_key_path):
        return None
    credentials = service_account.Credentials.from_service_account_file(sa_key_path, scopes=DRIVE_SCOPES)
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def upload_file(service, file_path: str, folder_id: str) -> str:
    """Ritorna l'id del file caricato su Drive."""
    metadata: dict = {"name": os.path.basename(file_path)}
    if folder_id:
        metadata["parents"] = [folder_id]
    media = MediaFileUpload(file_path, resumable=True)
    uploaded = service.files().create(body=metadata, media_body=media, fields="id").execute()
    return uploaded["id"]


def list_backup_files(service, folder_id: str) -> list[dict]:
    """Lista {id, name} dei file di backup nella cartella Drive, piu' recenti (per nome) prima."""
    query = f"name contains '{BACKUP_PREFIX}'"
    if folder_id:
        query += f" and '{folder_id}' in parents"
    response = service.files().list(q=query, fields="files(id, name)", orderBy="name desc").execute()
    return response.get("files", [])


def delete_file(service, file_id: str) -> None:
    service.files().delete(fileId=file_id).execute()


def apply_drive_retention(service, folder_id: str, retention: int) -> list[str]:
    """Cancella su Drive le coppie piu' vecchie oltre le `retention` piu' recenti
    (stesso criterio di apply_local_retention, ADR-0018 punto 4)."""
    files = list_backup_files(service, folder_id)
    timestamps = sorted(
        {os.path.splitext(f["name"])[0][len(BACKUP_PREFIX):] for f in files}, reverse=True
    )
    stale_timestamps = set(timestamps[retention:])
    deleted: list[str] = []
    for f in files:
        ts = os.path.splitext(f["name"])[0][len(BACKUP_PREFIX):]
        if ts in stale_timestamps:
            delete_file(service, f["id"])
            deleted.append(f["name"])
    return deleted
```

- [ ] **Step 5: Esegui il test, verifica che passi**

Run: `../.venv/Scripts/python -m pytest tests/test_drive.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/drive.py backend/tests/test_drive.py backend/requirements.txt
git commit -m "feat(F4): integrazione Google Drive (upload/retention, Service Account opzionale)"
```

---

### Task 4: Endpoint FastAPI + job opzionale all'avvio

**Files:**
- Create: `backend/app/routers/backup.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/config.py`
- Modify: `.env.example`
- Create: `backend/tests/test_backup_router.py`

**Interfaces:**
- Consumes (da Task 1/2): `create_backup`, `list_local_backups`, `apply_local_retention`,
  `restore_from_backup` (tutte da `app.backup`)
- Consumes (da Task 3): `get_drive_service`, `upload_file`, `apply_drive_retention`
  (da `app.drive`)
- Consumes (esistente): `engine`, `refresh_read_only_replica` (da `app.db`), `settings`
  (da `app.config`)
- Produces: `run_backup() -> dict` in `app.routers.backup` (riusata dall'endpoint
  manuale e dal job opzionale d'avvio in `main.py`)
- Produces: `router` (`APIRouter(prefix="/backup", tags=["backup"])`) con
  `POST /backup`, `GET /backup`, `POST /backup/restore`

- [ ] **Step 1: Aggiungi `backup_dir` a `backend/app/config.py`**

Apri `backend/app/config.py` e aggiungi il campo (accanto a `google_sa_key_path` nella
sezione "Backup (Fase 4)"):

```python
    backup_dir: str = "/backups"
```

Il file risultante nella sezione Backup deve leggere:

```python
    # Backup (Fase 4)
    backup_on_startup: bool = False
    backup_dir: str = "/backups"
    google_sa_key_path: str = "/secrets/service_account.json"
    gdrive_backup_folder_id: str = ""
    backup_retention: int = 12
```

Aggiungi anche in `.env.example`, nella sezione `# --- Backup (Fase 4) ---`, subito
dopo `BACKUP_ON_STARTUP=false`:

```
# Path locale dove scrivere i backup (montato come volume Docker, vedi docker-compose.yml)
BACKUP_DIR=/backups
```

- [ ] **Step 2: Scrivi i test (falliranno — `app.routers.backup` non esiste ancora)**

Crea `backend/tests/test_backup_router.py`:

```python
import os
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Transaction
from app.routers import backup as backup_router


def _build_test_app(tmp_path, monkeypatch):
    db_path = tmp_path / "live.db"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as session:
        session.add(
            Transaction(
                date=datetime(2026, 1, 5), amount=10.0, currency="EUR", type="expense",
                category_raw="Test", account="principale", source="my_finance", hash_dedup="h1",
            )
        )
        session.commit()

    monkeypatch.setattr(backup_router, "engine", engine)
    monkeypatch.setattr(backup_router.settings, "db_path", str(db_path))
    monkeypatch.setattr(backup_router.settings, "backup_dir", str(backup_dir))
    monkeypatch.setattr(backup_router.settings, "google_sa_key_path", str(tmp_path / "missing_sa.json"))
    monkeypatch.setattr(backup_router.settings, "backup_retention", 12)
    monkeypatch.setattr(backup_router, "refresh_read_only_replica", lambda: None)

    app = FastAPI()
    app.include_router(backup_router.router)
    return TestClient(app), engine


def test_backup_now_creates_local_files_and_skips_drive(tmp_path, monkeypatch):
    client, _engine = _build_test_app(tmp_path, monkeypatch)

    resp = client.post("/backup")

    assert resp.status_code == 200
    body = resp.json()
    assert body["row_count"] == 1
    assert body["drive_uploaded"] is False
    assert body["drive_error"] is not None
    assert os.path.exists(body["db_path"])
    assert os.path.exists(body["xlsx_path"])


def test_list_backups_returns_created_timestamp(tmp_path, monkeypatch):
    client, _engine = _build_test_app(tmp_path, monkeypatch)
    client.post("/backup")

    resp = client.get("/backup")

    assert resp.status_code == 200
    assert len(resp.json()["backups"]) == 1


def test_restore_requires_confirm_true(tmp_path, monkeypatch):
    client, _engine = _build_test_app(tmp_path, monkeypatch)
    created = client.post("/backup").json()
    filename = os.path.basename(created["db_path"])

    resp = client.post("/backup/restore", json={"filename": filename, "confirm": False})

    assert resp.status_code == 400


def test_restore_overwrites_live_db(tmp_path, monkeypatch):
    client, engine = _build_test_app(tmp_path, monkeypatch)
    created = client.post("/backup").json()
    filename = os.path.basename(created["db_path"])

    Session = sessionmaker(bind=engine, future=True)
    with Session() as session:
        session.query(Transaction).delete()
        session.commit()
        assert session.query(Transaction).count() == 0

    resp = client.post("/backup/restore", json={"filename": filename, "confirm": True})

    assert resp.status_code == 200
    with Session() as session:
        assert session.query(Transaction).count() == 1


def test_restore_missing_file_returns_404(tmp_path, monkeypatch):
    client, _engine = _build_test_app(tmp_path, monkeypatch)

    resp = client.post("/backup/restore", json={"filename": "portfolio_backup_00000000_000000.db", "confirm": True})

    assert resp.status_code == 404
```

- [ ] **Step 3: Esegui i test, verifica che falliscano**

Run: `../.venv/Scripts/python -m pytest tests/test_backup_router.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.routers.backup'`

- [ ] **Step 4: Implementa `backend/app/routers/backup.py`**

```python
"""`POST /backup` — backup manuale (dump + xlsx + locale + Drive best-effort + retention).
`GET /backup` — lista backup locali disponibili.
`POST /backup/restore` — restore da backup locale (operazione distruttiva, richiede
conferma esplicita). ADR-0018."""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.backup import apply_local_retention, create_backup, list_local_backups, restore_from_backup
from app.config import settings
from app.db import engine, refresh_read_only_replica
from app.drive import apply_drive_retention, get_drive_service, upload_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backup", tags=["backup"])


def run_backup() -> dict:
    """Punto unico riusato dall'endpoint manuale e dal job opzionale all'avvio
    (ADR-0018 punto 6)."""
    result = create_backup(engine, settings.db_path, settings.backup_dir)

    drive_uploaded = False
    drive_error: str | None = None
    drive_deleted: list[str] = []
    try:
        # get_drive_service() e' dentro il try: una Service Account key presente
        # ma malformata/corrotta solleva un'eccezione da from_service_account_file()
        # (non solo "file assente" - quello ritorna None senza eccezione) e deve
        # restare best-effort come il resto del blocco Drive (ADR-0004/ADR-0018).
        service = get_drive_service(settings.google_sa_key_path)
        if service is None:
            drive_error = "Service Account non montata: upload Drive skippato."
        else:
            upload_file(service, result.db_path, settings.gdrive_backup_folder_id)
            upload_file(service, result.xlsx_path, settings.gdrive_backup_folder_id)
            drive_uploaded = True
            drive_deleted = apply_drive_retention(service, settings.gdrive_backup_folder_id, settings.backup_retention)
    except Exception as exc:  # SA malformata/rete/permessi Drive: best-effort (ADR-0004/ADR-0018)
        drive_error = str(exc)
        logger.warning("Backup Drive fallito (non bloccante): %s", exc)

    local_deleted = apply_local_retention(settings.backup_dir, settings.backup_retention)

    return {
        "db_path": result.db_path,
        "xlsx_path": result.xlsx_path,
        "row_count": result.row_count,
        "drive_uploaded": drive_uploaded,
        "drive_error": drive_error,
        "local_deleted": local_deleted,
        "drive_deleted": drive_deleted,
    }


@router.post("")
def backup_now():
    return run_backup()


@router.get("")
def list_backups():
    return {"backups": list_local_backups(settings.backup_dir)}


class RestoreRequest(BaseModel):
    filename: str
    confirm: bool = False


@router.post("/restore")
def restore(payload: RestoreRequest):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Restore richiede 'confirm: true' (operazione distruttiva, ADR-0018).")

    # os.path.basename() PRIMA della validazione: neutralizza qualunque componente di
    # path (".." o separatori) in payload.filename prima che partecipi al pattern-check
    # e al join, cosi' il file risolto non puo' mai uscire da settings.backup_dir
    # (path traversal, trovato in review Task 4).
    filename = os.path.basename(payload.filename)
    if not filename.startswith("portfolio_backup_") or not filename.endswith(".db"):
        raise HTTPException(status_code=400, detail="filename atteso: portfolio_backup_YYYYMMDD_HHMMSS.db")

    backup_dir_abs = os.path.abspath(settings.backup_dir)
    backup_db_path = os.path.abspath(os.path.join(backup_dir_abs, filename))
    if os.path.dirname(backup_db_path) != backup_dir_abs:
        raise HTTPException(status_code=400, detail="filename atteso: portfolio_backup_YYYYMMDD_HHMMSS.db")

    try:
        restore_from_backup(engine, backup_db_path, settings.db_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        refresh_read_only_replica()
    except Exception as exc:  # replica Metabase: best-effort (ADR-0004)
        logger.warning("Replica read-only non aggiornata dopo restore (non bloccante): %s", exc)

    return {"restored_from": payload.filename}
```

- [ ] **Step 5: Registra il router e il job opzionale in `backend/app/main.py`**

Sostituisci il contenuto di `backend/app/main.py` con:

```python
"""FastAPI app — scheletro Fase 0 + ingestion (Fase 1/2) + backup (Fase 4)."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.routers import backup, categories, imports

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.backup_on_startup:
        try:
            backup.run_backup()
        except Exception as exc:  # best-effort: non deve bloccare l'avvio (ADR-0018 punto 6)
            logger.warning("Backup all'avvio fallito (non bloccante): %s", exc)
    yield


app = FastAPI(title="Personal Portfolio", version="0.1.0-phase4", lifespan=lifespan)

app.include_router(imports.router)
app.include_router(categories.router)
app.include_router(backup.router)


@app.get("/health")
def health():
    """Healthcheck usato da Docker (ADR: one-click)."""
    return {"status": "ok", "phase": "4", "db_path": settings.db_path}


@app.get("/")
def root():
    return {"app": "Personal Portfolio", "docs": "/docs"}
```

- [ ] **Step 6: Esegui i test, verifica che passino**

Run: `../.venv/Scripts/python -m pytest tests/test_backup_router.py -v`
Expected: 5 passed

- [ ] **Step 7: Esegui l'intera suite backup + verifica import app**

Run (da `backend/`):
```bash
../.venv/Scripts/python -m pytest tests/ -v
../.venv/Scripts/python -c "import app.main; print('OK import app.main')"
```
Expected: tutti i test passano (15 totali tra Task 1-4); import senza errori.

- [ ] **Step 8: Commit**

```bash
git add backend/app/routers/backup.py backend/app/main.py backend/app/config.py .env.example backend/tests/test_backup_router.py
git commit -m "feat(F4): endpoint POST/GET /backup, POST /backup/restore, job opzionale all'avvio"
```

---

## Post-implementazione (controller, non subagent)

Dopo la review finale whole-branch: verifica manuale E2E (backup reale con `docker
compose up`, Service Account reale se disponibile, restore su DB di prova) e solo
allora aggiornare — con le evidenze reali raccolte, non prima:
- `docs/DECISIONS.md` — nessuna modifica (ADR-0018 già scritto).
- `docs/SECURITY.md` — come condividere la cartella Drive con l'email della service
  account (passo umano).
- `docs/ARCHITECTURE.md` — riga F4 nella tabella "Stato avanzamento" con evidenze,
  "Fase corrente" → F5, prompt di ripresa sviluppo aggiornato.
- `CLAUDE.md` — riga "Fase corrente" → F5.
