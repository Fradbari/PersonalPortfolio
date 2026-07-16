from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.models import Account
from app.routers import accounts as accounts_router


def _build_test_app():
    # StaticPool: FastAPI esegue gli endpoint sync in un thread pool separato dal
    # thread di test — senza StaticPool ogni thread vedrebbe un DB `:memory:` diverso
    # (SingletonThreadPool e' per-thread) e Base.metadata.create_all() risulterebbe
    # invisibile all'endpoint ("no such table"). StaticPool forza un'unica connessione
    # condivisa fra tutti i thread.
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
    app.include_router(accounts_router.router)
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), Session


def _seed(Session) -> int:
    with Session() as session:
        acc = Account(name="principale")
        session.add(acc)
        session.commit()
        return acc.id


def test_list_accounts_returns_name_and_display_name():
    client, Session = _build_test_app()
    _seed(Session)

    resp = client.get("/accounts")

    assert resp.status_code == 200
    body = resp.json()
    assert body == [{"id": body[0]["id"], "name": "principale", "display_name": None}]


def test_update_account_sets_display_name():
    client, Session = _build_test_app()
    account_id = _seed(Session)

    resp = client.patch(f"/accounts/{account_id}", json={"display_name": "Conto corrente"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "Conto corrente"
    assert body["name"] == "principale"


def test_update_account_rejects_empty_display_name():
    client, Session = _build_test_app()
    account_id = _seed(Session)

    resp = client.patch(f"/accounts/{account_id}", json={"display_name": "   "})

    assert resp.status_code == 422


def test_update_account_missing_returns_404():
    client, Session = _build_test_app()
    _seed(Session)

    resp = client.patch("/accounts/999", json={"display_name": "X"})

    assert resp.status_code == 404
