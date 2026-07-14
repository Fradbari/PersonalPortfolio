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
