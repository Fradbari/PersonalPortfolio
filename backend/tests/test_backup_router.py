import os
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Settings, Transaction
from app.routers import backup as backup_router
from app.services import settings as settings_service


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

    # run_backup() ora legge backup_retention via get_effective(session=None), che apre
    # una SessionLocal propria (app.db.SessionLocal di default). Per i test, quella
    # sessione deve puntare allo stesso engine di questo test (dove viene scritta la
    # riga Settings), non al DB reale dell'app -- stesso pattern di
    # test_settings_service.py::test_get_effective_session_none_opens_and_closes_its_own_session.
    monkeypatch.setattr(settings_service, "SessionLocal", Session)

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


def test_restore_rejects_path_traversal_filename(tmp_path, monkeypatch):
    client, engine = _build_test_app(tmp_path, monkeypatch)

    # Passa il check "naif" startswith/endswith (inizia con "portfolio_backup_",
    # finisce con ".db") ma contiene componenti ".." che, sotto il vecchio codice
    # (os.path.join senza basename/contenimento), farebbero uscire il path risolto
    # da settings.backup_dir (path traversal, trovato in review Task 4).
    traversal_filename = "portfolio_backup_../../../../secrets/service_account.json.db"

    resp = client.post("/backup/restore", json={"filename": traversal_filename, "confirm": True})

    assert resp.status_code == 400
    # La transazione seedata in _build_test_app deve restare intatta: nessun restore
    # (parziale o riuscito) da un file fuori da backup_dir e' avvenuto.
    Session = sessionmaker(bind=engine, future=True)
    with Session() as session:
        assert session.query(Transaction).count() == 1


# --- T5: backup_retention letto via get_effective (DB > env), non piu' da config.settings ---


def test_run_backup_local_retention_uses_db_value_over_config_default(tmp_path, monkeypatch):
    """`_build_test_app` fissa `backup_router.settings.backup_retention = 12` (il vecchio
    percorso di lettura, config): se il codice leggesse ancora da li', 12 backup
    non verrebbero mai ruotati via da un retention di 1. Scrivendo `backup_retention=1`
    nella tabella `settings` (via DB, non env) e verificando che restino solo l'ultima
    coppia dimostriamo che `run_backup()` ora legge il valore effettivo da
    `get_effective`, non il default di config (ADR-0027 p.3: DB > env > default)."""
    client, engine = _build_test_app(tmp_path, monkeypatch)
    backup_dir = tmp_path / "backups"

    for ts in ("20260101_000000", "20260102_000000", "20260103_000000"):
        (backup_dir / f"portfolio_backup_{ts}.db").write_text("x")
        (backup_dir / f"portfolio_backup_{ts}.xlsx").write_text("x")

    Session = sessionmaker(bind=engine, future=True)
    with Session() as session:
        session.add(Settings(key="backup_retention", value="1"))
        session.commit()

    resp = client.post("/backup")

    assert resp.status_code == 200
    remaining_db_files = [f for f in os.listdir(backup_dir) if f.endswith(".db")]
    assert len(remaining_db_files) == 1


def test_run_backup_drive_retention_uses_db_value_over_config_default(tmp_path, monkeypatch):
    """Stesso principio del test precedente ma per il secondo punto di lettura di
    `backup_retention` dentro `run_backup()` (ramo Drive, apply_drive_retention)."""
    client, engine = _build_test_app(tmp_path, monkeypatch)

    Session = sessionmaker(bind=engine, future=True)
    with Session() as session:
        session.add(Settings(key="backup_retention", value="1"))
        session.commit()

    monkeypatch.setattr(backup_router, "get_drive_service", lambda path: object())
    monkeypatch.setattr(backup_router, "upload_file", lambda *args, **kwargs: None)

    captured: dict = {}

    def fake_apply_drive_retention(service, folder_id, retention):
        captured["retention"] = retention
        return []

    monkeypatch.setattr(backup_router, "apply_drive_retention", fake_apply_drive_retention)

    resp = client.post("/backup")

    assert resp.status_code == 200
    body = resp.json()
    assert body["drive_uploaded"] is True
    assert captured["retention"] == 1
