import os
import sqlite3
from datetime import datetime

from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backup import _alembic_config
from app.models import Settings, Transaction
from app.routers import backup as backup_router
from app.services import settings as settings_service
from conftest import run_alembic_upgrade


def _build_test_app(tmp_path, monkeypatch):
    db_path = tmp_path / "live.db"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    # DB live costruito con le migration Alembic reali (non `Base.metadata.create_all`):
    # il backup che ne deriva porta `alembic_version` a head, cosi' il restore -> upgrade
    # e' un no-op verificabile (0 migration) invece di ritentare 0001 da zero su tabelle
    # gia' esistenti. Necessario da T15 (ADR-0034): `POST /backup/restore` ora fa girare
    # `alembic upgrade head` dopo la copia.
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    with engine.connect() as connection:
        run_alembic_upgrade(connection)
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
    # Con folder id vuoto il ramo Drive e' saltato (fix G2, T7b): serve un valore.
    monkeypatch.setattr(backup_router.settings, "gdrive_backup_folder_id", "test-folder")

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


# --- T15: POST /backup/restore porta il DB a head (ADR-0034) ---


def _make_backup_at_revision(backup_dir, revision, ts):
    """Crea un file di backup valido migrato ad `revision` con Alembic (non a head):
    simula un backup fatto in una fase precedente del progetto."""
    filename = f"portfolio_backup_{ts}.db"
    path = backup_dir / filename
    eng = create_engine(f"sqlite:///{path}", future=True)
    try:
        with eng.connect() as connection:
            run_alembic_upgrade(connection, revision)
    finally:
        eng.dispose()
    return filename


def _head_revision() -> str:
    return ScriptDirectory.from_config(_alembic_config()).get_current_head()


def test_restore_runs_migrations_and_reports_applied(tmp_path, monkeypatch):
    """D5 (chiuso da T15): un backup pre-`settings` (schema 0002) restaurato viene
    portato a head. Dopo la copia + upgrade la tabella `settings` esiste, `version_num`
    sul file di `settings.db_path` e' la head, e il body dichiara le migration applicate
    (assertion sul DB, non solo sul body -- altrimenti un 200 con schema fermo passerebbe
    inosservato, criterio T15 test #2)."""
    client, _engine = _build_test_app(tmp_path, monkeypatch)
    backup_dir = tmp_path / "backups"
    filename = _make_backup_at_revision(backup_dir, "0002", "20200101_000000")

    resp = client.post("/backup/restore", json={"filename": filename, "confirm": True})

    assert resp.status_code == 200
    body = resp.json()
    # 0002 -> head = 0003, 0004, 0005, 0006 (catena lineare corrente). Se una migration futura
    # venisse aggiunta, questo valore cambia: e' un segnale voluto, non un test fragile.
    assert body["migrations_applied"] == 4
    assert "schema_note" in body

    live_db_path = tmp_path / "live.db"
    conn = sqlite3.connect(live_db_path)
    try:
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        assert version == _head_revision()
        # la tabella `settings`, assente nel backup 0002, esiste dopo l'upgrade
        conn.execute("SELECT 1 FROM settings LIMIT 0")
    finally:
        conn.close()


def test_restore_from_0005_backup_creates_empty_chat_tables(tmp_path, monkeypatch):
    """D3: backup pre-F14 (0005) restaurato -> head, tabelle chat vuote, dati intatti."""
    client, _engine = _build_test_app(tmp_path, monkeypatch)
    backup_dir = tmp_path / "backups"
    filename = _make_backup_at_revision(backup_dir, "0005", "20200102_000000")
    bconn = sqlite3.connect(backup_dir / filename)
    try:
        bconn.execute(
            "INSERT INTO transactions (date, amount, currency, type, category_raw, account, source, hash_dedup) "
            "VALUES ('2026-02-01', 5.0, 'EUR', 'expense', 'Bkp', 'principale', 'my_finance', 'hbackup')"
        )
        bconn.commit()
    finally:
        bconn.close()

    resp = client.post("/backup/restore", json={"filename": filename, "confirm": True})

    assert resp.status_code == 200
    body = resp.json()
    assert body["migrations_applied"] >= 1
    assert "schema_note" in body

    conn = sqlite3.connect(tmp_path / "live.db")
    try:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == _head_revision()
        assert conn.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM transactions WHERE hash_dedup='hbackup'").fetchone()[0] == 1
    finally:
        conn.close()


def test_restore_from_head_backup_reports_zero_migrations(tmp_path, monkeypatch):
    """Backup gia' a head (caso normale): restore no-op sullo schema, `migrations_applied`
    = 0, nessun `schema_note`."""
    client, _engine = _build_test_app(tmp_path, monkeypatch)
    created = client.post("/backup").json()
    filename = os.path.basename(created["db_path"])

    resp = client.post("/backup/restore", json={"filename": filename, "confirm": True})

    assert resp.status_code == 200
    body = resp.json()
    assert body["migrations_applied"] == 0
    assert "schema_note" not in body


def test_restore_migration_failure_returns_case1_message(tmp_path, monkeypatch):
    """Failure path del blocco 2 (ADR-0034 p.5): se `upgrade_schema_to_head` solleva, il
    500 porta il messaggio del caso 1 (schema potenzialmente incoerente), distinto dal
    caso rebuild."""
    client, _engine = _build_test_app(tmp_path, monkeypatch)
    created = client.post("/backup").json()
    filename = os.path.basename(created["db_path"])

    def boom():
        raise RuntimeError("alembic esplode")

    monkeypatch.setattr(backup_router, "upgrade_schema_to_head", boom)

    resp = client.post("/backup/restore", json={"filename": filename, "confirm": True})

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert "migration fallita" in detail
    assert "rebuild indice FTS" not in detail


def test_restore_rebuild_failure_returns_case2_message(tmp_path, monkeypatch):
    """Failure path del blocco 3 (ADR-0034 p.5, criterio T15 test #3): se il rebuild FTS
    solleva DOPO una migration riuscita, il 500 porta il messaggio del caso 2 (indice
    mancante), NON quello del caso 1 -- senza questa distinzione i due rami sarebbero
    indistinguibili da fuori."""
    client, _engine = _build_test_app(tmp_path, monkeypatch)
    created = client.post("/backup").json()
    filename = os.path.basename(created["db_path"])

    def boom(_engine):
        raise RuntimeError("rebuild esplode")

    monkeypatch.setattr(backup_router, "rebuild_fts_index", boom)

    resp = client.post("/backup/restore", json={"filename": filename, "confirm": True})

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert "rebuild indice FTS" in detail
    assert "migration fallita" not in detail


# ---- F10 T3: POST /backup/gdrive-test + redazione drive_error (ADR-0031, D7) ----
import json as _json
import logging
import threading

from test_gdrive_probe import FakeDrive, http_error

from app import drive as drive_module

SENT = "SENTINEL_FOLDER_123"
SENT_SA = "SENTINEL_SA_PATH_456.json"


def _sentinels(tmp_path, monkeypatch, *, sa_exists=True, folder=SENT):
    sa = tmp_path / SENT_SA
    if sa_exists:
        sa.write_text("{}")
    monkeypatch.setattr(backup_router.settings, "google_sa_key_path", str(sa))
    monkeypatch.setattr(backup_router.settings, "gdrive_backup_folder_id", folder)
    monkeypatch.setattr(backup_router.settings, "ai_api_key", "")
    return str(sa)


def _assert_no_sentinel(text, sa):
    assert SENT not in text
    assert SENT_SA not in text and sa not in text


def test_gdrive_test_never_leaks_sentinels_real_probe(tmp_path, monkeypatch):
    client, _e = _build_test_app(tmp_path, monkeypatch)
    sa = _sentinels(tmp_path, monkeypatch)
    cases = {
        "404": FakeDrive(fail={"create": http_error(404, "notFound", folder=SENT)}),
        "403_quota": FakeDrive(fail={"create": http_error(403, "storageQuotaExceeded", folder=SENT)}),
        "403": FakeDrive(fail={"list": http_error(403, "forbidden", folder=SENT)}),
        "500": FakeDrive(fail={"create": http_error(500, folder=SENT)}),
        "ok": FakeDrive(),
    }
    for name, fake in cases.items():
        monkeypatch.setattr(drive_module, "get_drive_service", lambda _p, f=fake: f)
        resp = client.post("/backup/gdrive-test")
        assert resp.status_code == 200, name
        _assert_no_sentinel(resp.text, sa)
    assert client.post("/backup/gdrive-test").json()["ok"] is True


def test_gdrive_test_never_leaks_sentinels_config_outcomes(tmp_path, monkeypatch):
    client, _e = _build_test_app(tmp_path, monkeypatch)
    sa = _sentinels(tmp_path, monkeypatch, sa_exists=False)
    resp = client.post("/backup/gdrive-test")
    assert resp.status_code == 200 and resp.json()["outcome"] == "sa_missing"
    _assert_no_sentinel(resp.text, sa)

    sa = _sentinels(tmp_path, monkeypatch, folder="")
    monkeypatch.setattr(drive_module, "get_drive_service", lambda _p: FakeDrive())
    resp = client.post("/backup/gdrive-test")
    assert resp.json()["outcome"] == "folder_id_missing"
    _assert_no_sentinel(resp.text, sa)


def test_gdrive_test_ignores_body_and_uses_settings(tmp_path, monkeypatch):
    client, _e = _build_test_app(tmp_path, monkeypatch)
    sa = _sentinels(tmp_path, monkeypatch)
    seen = {}

    def fake_probe(sa_key_path, folder_id):
        seen["args"] = (sa_key_path, folder_id)
        return drive_module.run_gdrive_probe(sa_key_path, folder_id)

    monkeypatch.setattr(backup_router, "run_gdrive_probe", fake_probe)
    monkeypatch.setattr(
        drive_module, "get_drive_service",
        lambda _p: FakeDrive(fail={"create": http_error(404, "notFound", folder="OTHER_SENTINEL")}),
    )
    resp = client.post("/backup/gdrive-test", json={"folder_id": "OTHER_SENTINEL", "sa_key_path": "OTHER_PATH"})
    assert resp.status_code == 200
    assert seen["args"] == (sa, SENT)
    assert "OTHER_SENTINEL" not in resp.text and "OTHER_PATH" not in resp.text
    _assert_no_sentinel(resp.text, sa)


def test_gdrive_test_lock_returns_409_then_recovers(tmp_path, monkeypatch):
    client, _e = _build_test_app(tmp_path, monkeypatch)
    _sentinels(tmp_path, monkeypatch)
    monkeypatch.setattr(drive_module, "get_drive_service", lambda _p: FakeDrive())
    assert backup_router._probe_lock.acquire(blocking=False)
    try:
        resp = client.post("/backup/gdrive-test")
        assert resp.status_code == 409
        assert resp.json()["detail"] == "Test di connessione già in corso."
    finally:
        backup_router._probe_lock.release()
    assert client.post("/backup/gdrive-test").status_code == 200
    assert not backup_router._probe_lock.locked()


def _backup_with_404(tmp_path, monkeypatch, caplog):
    client, _e = _build_test_app(tmp_path, monkeypatch)
    sa = _sentinels(tmp_path, monkeypatch)
    fake = FakeDrive(fail={"create": http_error(404, "notFound", folder=SENT)})
    monkeypatch.setattr(backup_router, "get_drive_service", lambda _p: fake)
    monkeypatch.setattr(drive_module, "get_drive_service", lambda _p: fake)
    caplog.set_level(logging.DEBUG)
    return client, sa


def test_backup_drive_error_is_redacted(tmp_path, monkeypatch, caplog):
    client, sa = _backup_with_404(tmp_path, monkeypatch, caplog)
    resp = client.post("/backup")
    assert resp.status_code == 200
    body = resp.json()
    assert body["drive_error"] and body["drive_uploaded"] is False
    _assert_no_sentinel(resp.text, sa)
    _assert_no_sentinel(caplog.text, sa)


def test_folder_id_absent_from_both_endpoints_same_404(tmp_path, monkeypatch, caplog):
    client, sa = _backup_with_404(tmp_path, monkeypatch, caplog)
    for path in ("/backup", "/backup/gdrive-test"):
        resp = client.post(path)
        assert resp.status_code == 200
        _assert_no_sentinel(resp.text, sa)
    _assert_no_sentinel(caplog.text, sa)
