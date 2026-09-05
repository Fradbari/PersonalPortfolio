"""Dump SQLite (online backup API) + export xlsx leggibile (ADR-0018, Fase 4)."""
from __future__ import annotations

import glob
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models import Transaction

BACKUP_PREFIX = "portfolio_backup_"
TIMESTAMP_FMT = "%Y%m%d_%H%M%S"

# backend/ (contiene alembic.ini e la cartella alembic/): due livelli sopra questo file
# (backend/app/backup.py). Assoluto perche' `upgrade_schema_to_head()` gira dentro un
# processo il cui cwd non e' garantito essere backend/ (a differenza dell'invocazione da
# riga di comando su cui e' tarato il path relativo di alembic.ini).
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
    connessione lo riapre automaticamente (il listener WAL in app.db si riattiva).

    Filesystem-puro di proposito (ADR-0034 p.2): non fa girare Alembic ne' tocca l'indice
    FTS -- quella logica vive in `upgrade_schema_to_head()`, orchestrata dal router dopo
    questa copia. Cosi' resta testabile su un engine senza FTS in `test_backup_core.py`."""
    if not os.path.exists(backup_db_path):
        raise FileNotFoundError(f"Backup non trovato: {backup_db_path}")

    engine.dispose()
    shutil.copy2(backup_db_path, live_db_path)
    for ext in ("-wal", "-shm"):
        stale_side_file = f"{live_db_path}{ext}"
        if os.path.exists(stale_side_file):
            os.remove(stale_side_file)


def _alembic_config() -> Config:
    """Config Alembic con solo `script_location` assoluto (indipendente dalla cwd),
    SENZA passare `alembic.ini`.

    Deliberato: `command.upgrade` esegue `alembic/env.py`, che chiama
    `fileConfig(config.config_file_name)` solo quando un file di config e' presente. Il
    default di `fileConfig` e' `disable_existing_loggers=True`: passare l'ini
    silenzierebbe TUTTI i logger gia' creati (inclusi quelli dell'app) a ogni restore.
    Non passandolo, `config_file_name` resta None, `env.py` salta `fileConfig` e i logger
    dell'app sopravvivono. `script_location` e' l'unica opzione che serve per l'upgrade."""
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    return cfg


def upgrade_schema_to_head() -> int:
    """Porta il DB live (`settings.db_path`) a head via Alembic dopo un restore
    (ADR-0034 p.1-3). Ritorna il numero di migration applicate.

    `command.upgrade` esegue `alembic/env.py`, che costruisce il PROPRIO engine
    `NullPool` leggendo `settings.db_url` (`env.py:12`): nasce quindi DOPO che la copia
    del restore ha gia' sovrascritto il file, cosi' la migration colpisce il DB
    restaurato e non quello pre-restore (ADR-0034 p.3). `NullPool` non cachea
    connessioni, nessun handle stantio sul file appena sostituito.

    Il conteggio e' calcolato PRIMA dell'upgrade confrontando la revision corrente del
    file con la head, sulla catena lineare delle migration (invariante di progetto:
    `alembic heads` = una sola riga)."""
    cfg = _alembic_config()
    script = ScriptDirectory.from_config(cfg)
    ordered = [rev.revision for rev in reversed(list(script.walk_revisions()))]  # base -> head

    probe_engine = create_engine(settings.db_url, poolclass=NullPool)
    try:
        with probe_engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
    finally:
        probe_engine.dispose()

    if current is None:
        applied = len(ordered)
    elif current in ordered:
        applied = len(ordered) - 1 - ordered.index(current)
    else:
        applied = 0

    command.upgrade(cfg, "head")
    return applied
