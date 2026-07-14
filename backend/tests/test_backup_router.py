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
