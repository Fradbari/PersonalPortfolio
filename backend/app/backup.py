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
