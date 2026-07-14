"""Dump SQLite (online backup API) + export xlsx leggibile (ADR-0018, Fase 4)."""
from __future__ import annotations

import glob
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime

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
