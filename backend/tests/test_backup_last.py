"""T7b: `GET /backup/last` (ultimo esito in memoria) + fix G2 (folder id vuoto -> niente Drive)."""
import logging
import os
import threading
from types import SimpleNamespace

import pytest

from app import main as main_module
from app.drive import outcome_message
from app.routers import backup as backup_router
from test_backup_router import _build_test_app
from test_gdrive_probe import FakeDrive, http_error

SENTINEL = "SENTINEL_FOLDER_T7B_ZZZ"
SENTINEL_PATH = "SENTINEL_TOKEN_T7B_PATH.json"
KEYS = {"at", "trigger", "local_ok", "drive_uploaded", "drive_outcome", "message"}


@pytest.fixture(autouse=True)
def _reset_last(monkeypatch):
    monkeypatch.setattr(backup_router, "_last_backup", None)


def _with_token(tmp_path, monkeypatch, folder):
    token = tmp_path / SENTINEL_PATH
    token.write_text("{}")
    monkeypatch.setattr(backup_router.settings, "google_oauth_token_path", str(token))
    monkeypatch.setattr(backup_router.settings, "gdrive_backup_folder_id", folder)
    monkeypatch.setattr(backup_router.settings, "ai_api_key", "")
    return str(token)


def test_initial_state_is_null(tmp_path, monkeypatch):
    client, _e = _build_test_app(tmp_path, monkeypatch)
    resp = client.get("/backup/last")
    assert resp.status_code == 200
    assert resp.json() == {"last": None}


def test_manual_trigger_recorded(tmp_path, monkeypatch):
    client, _e = _build_test_app(tmp_path, monkeypatch)
    assert client.post("/backup").status_code == 200
    last = client.get("/backup/last").json()["last"]
    assert set(last) == KEYS
    assert last["trigger"] == "manual"
    assert last["local_ok"] is True
    assert last["drive_uploaded"] is False
    assert last["drive_outcome"] == "auth_missing"


def test_startup_trigger_recorded(tmp_path, monkeypatch):
    client, _e = _build_test_app(tmp_path, monkeypatch)
    main_module._run_startup_backup()
    assert client.get("/backup/last").json()["last"]["trigger"] == "startup"


def test_last_returns_copy(tmp_path, monkeypatch):
    client, _e = _build_test_app(tmp_path, monkeypatch)
    client.post("/backup")
    returned = backup_router.last_backup()["last"]
    returned["trigger"] = "mutated"
    assert backup_router._last_backup["trigger"] == "manual"
    assert client.get("/backup/last").json()["last"]["trigger"] == "manual"


def test_drive_error_sanitized_everywhere(tmp_path, monkeypatch, caplog):
    client, _e = _build_test_app(tmp_path, monkeypatch)
    token_path = _with_token(tmp_path, monkeypatch, SENTINEL)
    fake = FakeDrive(fail={"create": http_error(404, "notFound", folder=SENTINEL)})
    monkeypatch.setattr(backup_router, "get_drive_service", lambda _p: fake)
    caplog.set_level(logging.DEBUG)

    post = client.post("/backup")
    last = client.get("/backup/last")

    for text in (post.text, last.text, caplog.text):
        assert SENTINEL not in text
        assert token_path not in text and SENTINEL_PATH not in text
    assert last.json()["last"]["drive_outcome"] == "folder_not_found"
    assert last.json()["last"]["drive_uploaded"] is False


def test_startup_local_failure_log_sanitized(tmp_path, monkeypatch, caplog):
    client, _e = _build_test_app(tmp_path, monkeypatch)
    token_path = _with_token(tmp_path, monkeypatch, SENTINEL)

    def boom(*_a, **_k):
        raise OSError(f"disk error su {token_path} cartella {SENTINEL}")

    monkeypatch.setattr(backup_router, "create_backup", boom)
    caplog.set_level(logging.DEBUG)

    main_module._run_startup_backup()  # non deve sollevare

    assert "Backup all'avvio fallito" in caplog.text
    assert SENTINEL not in caplog.text
    assert token_path not in caplog.text and SENTINEL_PATH not in caplog.text
    last = client.get("/backup/last")
    assert SENTINEL not in last.text and SENTINEL_PATH not in last.text
    assert last.json()["last"]["trigger"] == "startup"


def test_local_failure_recorded_and_reraised(tmp_path, monkeypatch):
    client, _e = _build_test_app(tmp_path, monkeypatch)

    def boom(*_a, **_k):
        raise OSError("dettaglio interno /percorso/segreto")

    monkeypatch.setattr(backup_router, "create_backup", boom)

    with pytest.raises(OSError):
        backup_router.run_backup()

    last = client.get("/backup/last").json()["last"]
    assert last["local_ok"] is False
    assert last["drive_uploaded"] is False
    assert last["drive_outcome"] is None
    assert last["message"] == "Backup locale fallito: controlla il log del backend."
    assert "segreto" not in str(last)


def test_empty_folder_id_skips_drive_g2(tmp_path, monkeypatch):
    client, _e = _build_test_app(tmp_path, monkeypatch)
    _with_token(tmp_path, monkeypatch, "")
    calls = []

    def spy_service(_p):
        calls.append("service")
        return FakeDrive()

    monkeypatch.setattr(backup_router, "get_drive_service", spy_service)
    monkeypatch.setattr(backup_router, "upload_file", lambda *a, **k: calls.append("upload"))
    monkeypatch.setattr(backup_router, "apply_drive_retention", lambda *a, **k: calls.append("drive_ret"))
    local_ret = []
    real_ret = backup_router.apply_local_retention
    monkeypatch.setattr(
        backup_router, "apply_local_retention",
        lambda *a, **k: (local_ret.append(1), real_ret(*a, **k))[1],
    )

    body = client.post("/backup").json()

    # Costruire il client (nessuna rete) e' ammesso; upload e retention Drive no.
    assert "upload" not in calls and "drive_ret" not in calls
    assert body["drive_uploaded"] is False
    assert body["drive_error"] == outcome_message("folder_id_missing")
    assert os.path.exists(body["db_path"]) and os.path.exists(body["xlsx_path"])
    assert local_ret == [1]
    last = client.get("/backup/last").json()["last"]
    assert last["drive_outcome"] == "folder_id_missing"
    assert last["message"] == outcome_message("folder_id_missing")


def test_auth_missing_checked_before_folder_id(tmp_path, monkeypatch):
    client, _e = _build_test_app(tmp_path, monkeypatch)
    monkeypatch.setattr(backup_router.settings, "gdrive_backup_folder_id", "")
    # token non montato (path di _build_test_app inesistente) + folder vuoto -> auth_missing
    client.post("/backup")
    assert client.get("/backup/last").json()["last"]["drive_outcome"] == "auth_missing"


def test_auth_missing_message_is_outcome_message_and_leaks_nothing(tmp_path, monkeypatch, caplog):
    # Token path configurato ma file assente: il testo e' quello dell'esito (nessun testo SA
    # fisso nel router) e il path non esce da risposta, ultimo esito, log.
    client, _e = _build_test_app(tmp_path, monkeypatch)
    missing = str(tmp_path / SENTINEL_PATH)
    monkeypatch.setattr(backup_router.settings, "google_oauth_token_path", missing)
    monkeypatch.setattr(backup_router.settings, "gdrive_backup_folder_id", SENTINEL)
    monkeypatch.setattr(backup_router.settings, "ai_api_key", "")
    caplog.set_level(logging.DEBUG)

    resp = client.post("/backup")
    last = client.get("/backup/last")

    assert resp.json()["drive_uploaded"] is False
    assert resp.json()["drive_error"] == outcome_message("auth_missing")
    assert "service account" not in resp.json()["drive_error"].lower()
    assert last.json()["last"]["drive_outcome"] == "auth_missing"
    assert last.json()["last"]["message"] == outcome_message("auth_missing")
    for text in (resp.text, last.text, caplog.text):
        assert SENTINEL not in text and missing not in text and SENTINEL_PATH not in text


def test_concurrent_run_backup_keeps_state_consistent(tmp_path, monkeypatch):
    client, _e = _build_test_app(tmp_path, monkeypatch)
    fake_result = SimpleNamespace(db_path="x.db", xlsx_path="x.xlsx", row_count=1)
    monkeypatch.setattr(backup_router, "create_backup", lambda *a, **k: fake_result)
    monkeypatch.setattr(backup_router, "apply_local_retention", lambda *a, **k: [])
    errors = []

    def worker(i):
        try:
            backup_router.run_backup(trigger="startup" if i % 2 else "manual")
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    state = backup_router._last_backup
    assert isinstance(state, dict) and set(state) == KEYS
    assert state["trigger"] in {"manual", "startup"}
    assert state["local_ok"] is True
    assert client.get("/backup/last").json()["last"] == state


@pytest.mark.parametrize("target", ["get_effective", "apply_local_retention"])
def test_post_local_failure_still_recorded(tmp_path, monkeypatch, target):
    client, _e = _build_test_app(tmp_path, monkeypatch)
    fake_result = SimpleNamespace(db_path="x.db", xlsx_path="x.xlsx", row_count=1)
    monkeypatch.setattr(backup_router, "create_backup", lambda *a, **k: fake_result)

    def boom(*_a, **_k):
        raise OSError(f"dettaglio interno {SENTINEL}")

    monkeypatch.setattr(backup_router, target, boom)

    with pytest.raises(OSError):
        backup_router.run_backup(trigger="startup")

    last = client.get("/backup/last").json()["last"]
    assert set(last) == KEYS
    assert last["trigger"] == "startup"
    assert last["local_ok"] is True
    assert last["message"] == backup_router._POST_LOCAL_FAILURE_MESSAGE
    assert SENTINEL not in str(last)


def test_last_at_is_utc_with_explicit_offset(tmp_path, monkeypatch):
    from datetime import datetime, timedelta

    client, _e = _build_test_app(tmp_path, monkeypatch)
    client.post("/backup")
    at = client.get("/backup/last").json()["last"]["at"]
    assert at.endswith("+00:00")
    parsed = datetime.fromisoformat(at)
    assert parsed.utcoffset() == timedelta(0)


def test_retention_failure_after_upload_message_does_not_contradict_uploaded(tmp_path, monkeypatch, caplog):
    # (A) upload riuscito, poi errore nella rotazione Drive.
    client, _e = _build_test_app(tmp_path, monkeypatch)
    token_path = _with_token(tmp_path, monkeypatch, SENTINEL)
    uploads = []
    monkeypatch.setattr(backup_router, "get_drive_service", lambda _p: FakeDrive())
    monkeypatch.setattr(backup_router, "upload_file", lambda *a, **k: uploads.append(a[1]))

    def boom(*_a, **_k):
        raise http_error(403, "insufficientFilePermissions", folder=SENTINEL)

    monkeypatch.setattr(backup_router, "apply_drive_retention", boom)
    caplog.set_level(logging.DEBUG)

    resp = client.post("/backup")
    body = resp.json()

    assert len(uploads) == 2
    assert body["drive_uploaded"] is True
    assert body["drive_error"] == backup_router._RETENTION_FAILURE_PREFIX + outcome_message("permission_denied")
    assert "caricato" in body["drive_error"] and "rotazione" in body["drive_error"]
    last = client.get("/backup/last").json()["last"]
    assert last["drive_uploaded"] is True
    assert last["drive_outcome"] == "permission_denied"
    assert last["message"] == body["drive_error"]
    for text in (resp.text, str(last), caplog.text):
        assert SENTINEL not in text and token_path not in text and SENTINEL_PATH not in text
    assert "stage=cleanup" in caplog.text


def test_retention_404_is_folder_not_found(tmp_path, monkeypatch):
    client, _e = _build_test_app(tmp_path, monkeypatch)
    _with_token(tmp_path, monkeypatch, SENTINEL)
    monkeypatch.setattr(backup_router, "get_drive_service", lambda _p: FakeDrive(fail={"list": http_error(404, "notFound")}))
    monkeypatch.setattr(backup_router, "upload_file", lambda *a, **k: "id")
    client.post("/backup")
    assert client.get("/backup/last").json()["last"]["drive_outcome"] == "folder_not_found"


def test_malformed_token_is_auth_invalid_like_probe(tmp_path, monkeypatch, caplog):
    # (B) token OAuth presente ma non valido: parsing reale in get_drive_service.
    client, _e = _build_test_app(tmp_path, monkeypatch)
    token_path = _with_token(tmp_path, monkeypatch, SENTINEL)
    with open(token_path, "w") as fh:
        fh.write("non json {")
    caplog.set_level(logging.DEBUG)

    resp = client.post("/backup")
    body = resp.json()

    assert resp.status_code == 200
    assert body["drive_uploaded"] is False
    assert body["drive_error"] == outcome_message("auth_invalid")
    last = client.get("/backup/last").json()["last"]
    assert last["drive_outcome"] == "auth_invalid"
    assert last["message"] == outcome_message("auth_invalid")
    assert set(last) == KEYS
    for text in (resp.text, str(last), caplog.text):
        assert SENTINEL not in text and token_path not in text and SENTINEL_PATH not in text
