"""Test di routing per l'invariante ADR-0033 e per il comportamento HTTP reale
di `mount_spa()` (T7).

Il test esistente in `test_ai_router.py`
(`test_ai_query_route_is_registered_before_spa_catchall_in_real_app`) ispeziona
`app.routes` proprio per non dipendere da `frontend_dist`, ma per lo stesso
motivo non puo' da solo provare che una route SPA venga effettivamente servita
come HTML (serve un file system reale con `index.html`, che quel test non
costruisce). Qui invece, in un file nuovo e dedicato (distinto da
`test_settings_router.py`/`test_backup_router.py`, che testano le funzionalita'
dei rispettivi router, non l'instradamento SPA/API):

- Test 1 verifica l'invariante statico di ADR-0033 (nessuna `SPA_ROUTES`
  coincide con un path API esatto). Ispeziona direttamente `app.main.app`
  (stesso pattern di `test_ai_router.py:190`, `from app.main import app as
  ...`) -- l'app reale assemblata da main.py, sempre sincronizzata per
  costruzione con qualunque `app.include_router(...)` presente o futuro,
  invece di una lista di router mantenuta a mano nel test (fragile: un router
  aggiunto a `main.py` senza aggiornare quella lista lascerebbe il test cieco
  proprio al tipo di regressione che deve impedire -- finding T7-review).
  L'unica particolarita' da gestire e' che `app.main.app` si comporta
  diversamente a seconda che `frontend_dist` esista o meno sul filesystem in
  cui gira il processo di test: quando NON esiste (questo e' il caso in
  questo ambiente di sviluppo, che non ha un frontend buildato), `main.py`
  registra un fallback JSON di sviluppo proprio su path "/" (`@app.get("/")
  def root()`), che collide letteralmente con "/" in `SPA_ROUTES` pur non
  essendo affatto una violazione di ADR-0033 -- i due rami (fallback dev vs
  `mount_spa()`) sono mutuamente esclusivi, mai registrati insieme.
  `_registered_api_paths()` esclude quella sola route per IDENTITA' della
  funzione endpoint (`route.endpoint is main_module.root`), non per il suo
  path, cosi' da non nascondere mai una vera futura violazione su "/". Quando
  `frontend_dist` e' presente, `main_module.root` non esiste come attributo
  di modulo (`getattr(..., None)` -> `None`): l'esclusione diventa un no-op
  innocuo, dato che in quel ramo "/" e' servito da `serve_frontend`
  (`/{full_path:path}`), gia' escluso perche' parametrizzato.
- Test 2 verifica il comportamento HTTP end-to-end: costruisce un'app di prova
  con i router reali + `mount_spa()` su una directory temporanea (fixture
  `tmp_path`, mai una directory nel repo), e prova le 4 combinazioni richieste
  (endpoint API -> JSON, route SPA -> HTML).
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main as main_module
from app.db import Base, get_session
from app.main import SPA_ROUTES, mount_spa
from app.routers import (
    accounts,
    ai,
    backup,
    categories,
    imports,
    insights,
    settings as settings_router,
    transactions,
)

_EXPECTED_SPA_ROUTES = frozenset(
    {
        "/",
        "/transazioni",
        "/import",
        "/categorie-pending",
        "/conti",
        "/backup-restore",
        "/assistente-ai",
        "/impostazioni",
    }
)

# Stessi router (e stesso ordine) di `app.include_router(...)` in main.py.
# Usati SOLO dal Test 2 (`_build_test_app_with_spa`) per assemblare un'app di
# prova con `mount_spa()` puntato a una directory temporanea -- non piu' da
# `_registered_api_paths()` (Test 1), che ora ispeziona `app.main.app` reale
# direttamente (T7-review) proprio per non dipendere da questa lista tenuta a
# mano.
_API_ROUTERS = (
    imports.router,
    categories.router,
    backup.router,
    transactions.router,
    accounts.router,
    insights.router,
    ai.router,
    settings_router.router,
)


def _registered_api_paths() -> frozenset[str]:
    """Path esatti (non parametrizzati) di ogni route effettivamente
    registrata su `app.main.app` -- l'app reale assemblata da main.py, non
    una lista di router ricostruita a mano nel test (finding T7-review: una
    lista manuale non vedrebbe mai un router futuro aggiunto a `main.py`
    senza aggiornarla anche qui). Resta cosi' automaticamente completo
    rispetto a qualunque router aggiunto in futuro (Blocco B/C: F11/F12/...).

    Esclude:
    - i path parametrizzati (es. `/transactions/{transaction_id}`), che non
      possono mai coincidere carattere per carattere con una voce letterale
      di `SPA_ROUTES`;
    - la sola route del fallback JSON dev-only `root()` (ramo `else:` di
      `main.py`, registrato su "/" solo quando `frontend_dist` NON esiste sul
      filesystem di questo processo -- il caso di questo ambiente di
      sviluppo). Esclusa per IDENTITA' della funzione endpoint
      (`route.endpoint is main_module.root`), non per il suo path "/": se in
      futuro una vera route API venisse registrata su "/" da un endpoint
      diverso da `root`, questa esclusione non la nasconderebbe. Quando
      `frontend_dist` e' presente (build di produzione/Docker),
      `main_module.root` non esiste come attributo di modulo (il ramo
      `else:` non viene eseguito): `getattr(..., None)` vale `None`, il
      confronto per identita' e' sempre falso, quindi l'esclusione e' un
      no-op innocuo -- in quel ramo "/" e' servito da `serve_frontend`
      (route `/{full_path:path}`), gia' escluso perche' parametrizzato.
    """
    dev_root = getattr(main_module, "root", None)
    paths: set[str] = set()
    for route in main_module.app.routes:
        path = getattr(route, "path", None)
        if not path or "{" in path:
            continue
        if dev_root is not None and getattr(route, "endpoint", None) is dev_root:
            continue
        paths.add(path)
    return frozenset(paths)


# --- Test 1: invariante ADR-0033 -------------------------------------------------


def test_spa_routes_are_exactly_the_eight_expected_paths():
    assert SPA_ROUTES == _EXPECTED_SPA_ROUTES
    assert "/backup" not in SPA_ROUTES


def test_spa_routes_never_collide_with_a_registered_api_endpoint_path():
    api_paths = _registered_api_paths()
    assert SPA_ROUTES.isdisjoint(api_paths)


# --- Test 2: comportamento HTTP reale (API vs SPA) -------------------------------


def _build_test_app_with_spa(tmp_path) -> TestClient:
    dist_dir = tmp_path / "frontend_dist"
    (dist_dir / "assets").mkdir(parents=True)
    (dist_dir / "index.html").write_text(
        "<!doctype html><html><body>spa-index-marker</body></html>", encoding="utf-8"
    )

    # DB in-memory reale (StaticPool: stessa connessione fra thread di test e
    # thread pool di FastAPI), stesso pattern di test_settings_router.py --
    # serve solo per GET /settings, che dipende da get_session.
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
    for r in _API_ROUTERS:
        app.include_router(r)
    app.dependency_overrides[get_session] = override_get_session

    mount_spa(app, str(dist_dir))

    return TestClient(app)


def test_api_endpoints_return_json_and_spa_routes_return_html(tmp_path):
    client = _build_test_app_with_spa(tmp_path)
    headers = {"Accept": "text/html"}

    resp_settings = client.get("/settings", headers=headers)
    assert resp_settings.status_code == 200
    assert resp_settings.headers["content-type"].startswith("application/json")

    resp_impostazioni = client.get("/impostazioni", headers=headers)
    assert resp_impostazioni.status_code == 200
    assert resp_impostazioni.headers["content-type"].startswith("text/html")
    assert "spa-index-marker" in resp_impostazioni.text

    resp_backup = client.get("/backup", headers=headers)
    assert resp_backup.status_code == 200
    assert resp_backup.headers["content-type"].startswith("application/json")

    resp_backup_restore = client.get("/backup-restore", headers=headers)
    assert resp_backup_restore.status_code == 200
    assert resp_backup_restore.headers["content-type"].startswith("text/html")
    assert "spa-index-marker" in resp_backup_restore.text
