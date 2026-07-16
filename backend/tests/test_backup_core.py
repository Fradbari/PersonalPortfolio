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
