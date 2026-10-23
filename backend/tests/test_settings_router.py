"""Test per `app/routers/settings.py` — `GET`/`PUT /settings` (F9, ADR-0027, T3).

Stesso pattern di `test_accounts.py`/`test_ai_router.py`: FastAPI minimale con
solo il router sotto test, DB SQLite in-memory reale via `StaticPool`
(dependency override di `get_session`) — nessun mock di DB o business logic
(ADR-0018 p.7).

I tre test di blacklist in coda riformulano ADR-0027 rettifica p.8: (a) nessun
*valore* di secret nella risposta di GET (sentinelle iniettate via monkeypatch
su `app.config.settings`); (b) nessuna chiave blacklistata nell'array
`settings[]`; (c) `PUT` su chiave blacklistata e su chiave inesistente ->
stesso messaggio 400 (anti-enumerazione).
"""
from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings as app_settings
from app.db import Base, get_session
from app.models import Settings
from app.routers import settings as settings_router
from app.services.settings import BLACKLIST, WHITELIST


def _build_test_app():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    def override_get_session():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    app.include_router(settings_router.router)
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), Session


# --- GET /settings: forma della risposta --------------------------------------


def test_get_settings_returns_all_six_whitelist_keys_with_shape():
    client, _ = _build_test_app()

    resp = client.get("/settings")

    assert resp.status_code == 200
    body = resp.json()
    keys = {item["key"] for item in body["settings"]}
    assert keys == set(WHITELIST.keys())
    for item in body["settings"]:
        assert set(item.keys()) == {"key", "value", "source", "applies_when"}
        assert item["source"] in ("db", "env", "default")
        assert item["applies_when"] == WHITELIST[item["key"]]["applies_when"]


def test_get_settings_sources_before_any_write():
    # Le 3 chiavi senza env_attr sono "default"; le 3 con env_attr sono "env"
    # finche' nulla e' stato scritto nel DB (ADR-0027 p.3).
    client, _ = _build_test_app()

    resp = client.get("/settings")

    sources = {item["key"]: item["source"] for item in resp.json()["settings"]}
    assert sources["theme"] == "default"
    assert sources["metabase_url"] == "default"
    assert sources["ai_history_max_turns"] == "default"
    assert sources["import_min_year"] == "env"
    assert sources["backup_retention"] == "env"
    assert sources["backup_on_startup"] == "env"


def test_get_settings_secrets_status_has_three_blacklist_keys_with_configured_bool():
    client, _ = _build_test_app()

    resp = client.get("/settings")

    secrets_status = resp.json()["secrets_status"]
    assert set(secrets_status.keys()) == set(BLACKLIST)
    for entry in secrets_status.values():
        assert set(entry.keys()) == {"configured"}
        assert isinstance(entry["configured"], bool)


# --- secrets_status: ramo True/False per ciascuna chiave (review finale Blocco A,
# Finding 1) ---------------------------------------------------------------------


def test_secrets_status_google_oauth_token_path_false_when_path_empty(monkeypatch):
    # Default vuoto (ADR-0035): nessun token configurato -> badge spento.
    monkeypatch.setattr(app_settings, "google_oauth_token_path", "")
    client, _ = _build_test_app()

    resp = client.get("/settings")

    assert resp.json()["secrets_status"]["google_oauth_token_path"]["configured"] is False


def test_secrets_status_google_oauth_token_path_false_when_file_absent(monkeypatch, tmp_path):
    # Path valorizzato ma file inesistente: il badge riflette l'esistenza reale
    # del file (os.path.exists), non la sola valorizzazione della stringa.
    missing_path = tmp_path / "does-not-exist" / "token.json"
    monkeypatch.setattr(app_settings, "google_oauth_token_path", str(missing_path))
    client, _ = _build_test_app()

    resp = client.get("/settings")

    assert resp.json()["secrets_status"]["google_oauth_token_path"]["configured"] is False


def test_secrets_status_google_oauth_token_path_false_when_path_is_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(app_settings, "google_oauth_token_path", str(tmp_path))
    client, _ = _build_test_app()

    resp = client.get("/settings")

    assert resp.json()["secrets_status"]["google_oauth_token_path"]["configured"] is False


def test_secrets_status_google_oauth_token_path_true_when_file_present(monkeypatch, tmp_path):
    # File temporaneo con contenuto innocuo: l'esistenza basta, il contenuto non
    # viene mai letto.
    real_path = tmp_path / "token.json"
    real_path.write_text("{}")
    monkeypatch.setattr(app_settings, "google_oauth_token_path", str(real_path))
    client, _ = _build_test_app()

    resp = client.get("/settings")

    assert resp.json()["secrets_status"]["google_oauth_token_path"]["configured"] is True


def test_secrets_status_ai_api_key_false_when_empty_true_when_set(monkeypatch):
    monkeypatch.setattr(app_settings, "ai_api_key", "")
    client, _ = _build_test_app()
    resp = client.get("/settings")
    assert resp.json()["secrets_status"]["ai_api_key"]["configured"] is False

    monkeypatch.setattr(app_settings, "ai_api_key", "some-key")
    client, _ = _build_test_app()
    resp = client.get("/settings")
    assert resp.json()["secrets_status"]["ai_api_key"]["configured"] is True


def test_secrets_status_gdrive_backup_folder_id_false_when_empty_true_when_set(monkeypatch):
    monkeypatch.setattr(app_settings, "gdrive_backup_folder_id", "")
    client, _ = _build_test_app()
    resp = client.get("/settings")
    assert resp.json()["secrets_status"]["gdrive_backup_folder_id"]["configured"] is False

    monkeypatch.setattr(app_settings, "gdrive_backup_folder_id", "some-folder-id")
    client, _ = _build_test_app()
    resp = client.get("/settings")
    assert resp.json()["secrets_status"]["gdrive_backup_folder_id"]["configured"] is True


# --- PUT /settings: scrittura e riflessione in GET ----------------------------


def test_put_settings_writes_values_and_get_reflects_them():
    client, _ = _build_test_app()

    put_resp = client.put("/settings", json={"theme": "dark", "ai_history_max_turns": 10})
    assert put_resp.status_code == 200

    get_resp = client.get("/settings")
    values = {item["key"]: (item["value"], item["source"]) for item in get_resp.json()["settings"]}
    assert values["theme"] == ("dark", "db")
    assert values["ai_history_max_turns"] == (10, "db")


def test_put_settings_rejects_unknown_key_with_400():
    client, Session = _build_test_app()

    resp = client.put("/settings", json={"not_a_real_setting": "x"})

    assert resp.status_code == 400
    with Session() as session:
        assert session.get(Settings, "not_a_real_setting") is None


def test_put_settings_rejects_blacklist_key_with_400():
    client, _ = _build_test_app()

    resp = client.put("/settings", json={"ai_api_key": "leak"})

    assert resp.status_code == 400


def test_put_settings_rejects_google_oauth_token_path_with_fixed_400_message():
    # Stessa risposta di una chiave sconosciuta (anti-enumerazione, ADR-0027 p.8).
    client, Session = _build_test_app()

    resp = client.put("/settings", json={"google_oauth_token_path": "/x/token.json"})
    resp_unknown = client.put("/settings", json={"does_not_exist_at_all": "x"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == resp_unknown.json()["detail"]
    assert "google_oauth_token_path" not in resp.text
    with Session() as session:
        assert session.get(Settings, "google_oauth_token_path") is None


def test_put_settings_invalid_key_writes_nothing_even_mixed_with_valid_keys():
    client, Session = _build_test_app()

    resp = client.put("/settings", json={"theme": "dark", "not_a_real_setting": "x"})

    assert resp.status_code == 400
    with Session() as session:
        assert session.get(Settings, "theme") is None


# --- Blacklist: 3 asserzioni (ADR-0027 rettifica p.8) -------------------------


def test_get_settings_never_leaks_blacklisted_secret_values(monkeypatch):
    monkeypatch.setattr(app_settings, "ai_api_key", "SENTINEL-AI-API-KEY")
    monkeypatch.setattr(app_settings, "google_oauth_token_path", "SENTINEL-OAUTH-TOKEN-PATH")
    monkeypatch.setattr(app_settings, "gdrive_backup_folder_id", "SENTINEL-DRIVE-FOLDER-ID")
    client, _ = _build_test_app()

    resp = client.get("/settings")

    raw = json.dumps(resp.json())
    assert "SENTINEL-AI-API-KEY" not in raw
    assert "SENTINEL-OAUTH-TOKEN-PATH" not in raw
    assert "SENTINEL-DRIVE-FOLDER-ID" not in raw


def test_get_settings_settings_array_never_contains_blacklisted_keys():
    client, _ = _build_test_app()

    resp = client.get("/settings")

    keys = {item["key"] for item in resp.json()["settings"]}
    assert keys.isdisjoint(BLACKLIST)


def test_put_settings_blacklisted_key_and_unknown_key_return_identical_message():
    client, _ = _build_test_app()

    resp_blacklist = client.put("/settings", json={"ai_api_key": "leak"})
    resp_unknown = client.put("/settings", json={"does_not_exist_at_all": "x"})

    assert resp_blacklist.status_code == 400
    assert resp_unknown.status_code == 400
    assert resp_blacklist.json()["detail"] == resp_unknown.json()["detail"]


# --- Boot reale: nessun AttributeError da shadowing di app.config.settings ---


def test_main_app_boots_without_shadowing_app_config_settings(monkeypatch):
    """Rischio identificato in pianificazione T3: un import nudo di `settings`
    (il router) nella riga `from app.routers import ...` di `main.py`
    sovrascriverebbe silenziosamente `from app.config import settings` (riga
    precedente) — errore che NON esplode all'import, solo al primo utilizzo
    reale di `settings.backup_on_startup` (lifespan) o `settings.db_path`
    (`/health`). Import reale del modulo + trigger di entrambi i path.

    Da T5: il lifespan legge `backup_on_startup` via `get_effective`, che apre
    una `SessionLocal` reale puntata al `db_path` di default di
    `app.config.Settings` (`/data/portfolio.db`) -- path che su una macchina di
    sviluppo locale senza container non esiste. Il test non dipende da un DB
    raggiungibile ne' migrato (vedi patch sotto: engine vuoto, nessuna tabella).
    Fix T5-review (`app/main.py`): la lettura e' avvolta in try/except, stesso
    stile di `_run_startup_backup` (ADR-0018 punto 6) -- se fallisce (file
    irraggiungibile o tabella non ancora migrata), il backup di avvio viene
    semplicemente saltato con un warning, il boot non si interrompe. Solo
    lettura (`get_effective` non scrive mai), quindi nessun side-effect anche
    nei rari ambienti dove `/data` esistesse davvero."""
    from app import main as main_module
    from app.services import settings as settings_service

    # Il lifespan usa l'engine di modulo (rebuild FTS) e SessionLocal (get_effective):
    # senza patch toccherebbero il path di produzione (/data/portfolio.db). Engine vuoto
    # (nessuna tabella): il boot deve comunque completare, come descritto sopra.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    monkeypatch.setattr(main_module, "engine", engine)
    monkeypatch.setattr(settings_service, "SessionLocal", sessionmaker(bind=engine, future=True))

    with TestClient(main_module.app) as client:  # trigghera il lifespan (startup)
        resp = client.get("/health")

    assert resp.status_code == 200
    assert "db_path" in resp.json()
