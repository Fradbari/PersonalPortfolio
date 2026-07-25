"""Test di `POST /transactions` (T7, F11/ADR-0028): inserimento manuale, ordinale
`#n`, 409 su duplicato, compatibilita' con l'importer."""
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.ingestion.reconciliation import compute_hash_dedup
from app.models import Account, Category, Transaction
from app.routers import transactions as transactions_router


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
    app.include_router(transactions_router.router)
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), Session


def _seed_category(Session, name="Alimentari") -> int:
    with Session() as session:
        cat = Category(name=name)
        session.add(cat)
        session.commit()
        return cat.id


VALID_BODY = {
    "date": "2026-01-05T00:00:00",
    "amount": 12.5,
    "currency": "EUR",
    "type": "expense",
    "account": "principale",
    "comment": "pranzo",
    "tag": None,
}


def test_create_transaction_unknown_category_returns_404_and_no_insert():
    client, Session = _build_test_app()

    resp = client.post("/transactions", json={**VALID_BODY, "category_id": 999})

    assert resp.status_code == 404
    with Session() as session:
        assert session.query(Transaction).count() == 0


def test_create_transaction_success_sets_manual_source_and_null_batch():
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)

    resp = client.post("/transactions", json={**VALID_BODY, "category_id": cat_id})

    assert resp.status_code == 200
    expected_hash = compute_hash_dedup(
        datetime(2026, 1, 5), 12.5, "Alimentari", "principale", "expense"
    )
    with Session() as session:
        row = session.execute(
            select(Transaction.source, Transaction.import_batch_id, Transaction.hash_dedup).where(
                Transaction.hash_dedup == expected_hash
            )
        ).one()
        assert row.source == "manual"
        assert row.import_batch_id is None


def test_create_transaction_registers_account_as_is():
    """ADR-0006: conti ignoti importati as-is, anche per l'inserimento manuale — senza
    questo, un conto digitato a mano nel form non comparirebbe mai in `/accounts`."""
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)

    resp = client.post(
        "/transactions", json={**VALID_BODY, "category_id": cat_id, "account": "conto-nuovo"}
    )

    assert resp.status_code == 200
    with Session() as session:
        assert session.execute(select(Account).where(Account.name == "conto-nuovo")).scalar_one_or_none() is not None


def test_create_transaction_duplicate_without_allow_returns_409_with_twin():
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)
    body = {**VALID_BODY, "category_id": cat_id}

    first = client.post("/transactions", json=body)
    assert first.status_code == 200
    twin_id = first.json()["id"]

    second = client.post("/transactions", json=body)

    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["transaction"]["id"] == twin_id
    with Session() as session:
        assert session.query(Transaction).count() == 1


def test_create_transaction_duplicate_with_allow_duplicate_creates_ordinal_1():
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)
    body = {**VALID_BODY, "category_id": cat_id}

    first = client.post("/transactions", json=body)
    assert first.status_code == 200

    second = client.post("/transactions", json={**body, "allow_duplicate": True})

    assert second.status_code == 200
    base_hash = compute_hash_dedup(datetime(2026, 1, 5), 12.5, "Alimentari", "principale", "expense")
    with Session() as session:
        hashes = set(session.execute(select(Transaction.hash_dedup)).scalars())
        assert hashes == {base_hash, f"{base_hash}#1"}


def test_create_transaction_importer_lookup_does_not_match_ordinal_suffix():
    """Criterio T7 #3: l'importer deduplica con `.in_(hashes)` (match esatto) su hash
    calcolati dai dati sorgente — che sono sempre hash BASE, mai suffissati. Una riga
    manuale forzata (`#1`) non deve quindi mai risultare "duplicato" di un futuro
    import con gli stessi campi stabili."""
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)
    body = {**VALID_BODY, "category_id": cat_id}

    client.post("/transactions", json=body)
    client.post("/transactions", json={**body, "allow_duplicate": True})  # crea #1

    reimport_hash = compute_hash_dedup(datetime(2026, 1, 5), 12.5, "Alimentari", "principale", "expense")
    with Session() as session:
        matched = set(
            session.execute(
                select(Transaction.hash_dedup).where(Transaction.hash_dedup.in_([reimport_hash]))
            ).scalars()
        )
    # Il match esatto trova SOLO la riga base, mai la #1, anche se questa condivide
    # tutti i campi stabili con l'hash ricalcolato dall'importer.
    assert matched == {reimport_hash}


def test_create_transaction_retry_succeeds_on_second_attempt_when_ordinal_stale():
    """Simula l'effetto osservabile di una race fra due richieste concorrenti: la
    prima lettura dell'ordinale libero e' stale (restituisce un valore gia' occupato),
    l'INSERT solleva IntegrityError sul vincolo UNIQUE, e il retry con una nuova
    lettura ha successo. La concorrenza vera non e' simulabile con TestClient
    sincrono/fixture a connessione singola (dichiarato in ADR-0028 p.5) — qui si
    verifica che il MECCANISMO di retry sia corretto dato un conflitto reale."""
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)
    body = {**VALID_BODY, "category_id": cat_id}

    client.post("/transactions", json=body)  # hash base
    client.post("/transactions", json={**body, "allow_duplicate": True})  # occupa #1

    with patch.object(transactions_router, "_next_free_ordinal", side_effect=[1, 2]):
        resp = client.post("/transactions", json={**body, "allow_duplicate": True})

    assert resp.status_code == 200
    base_hash = compute_hash_dedup(datetime(2026, 1, 5), 12.5, "Alimentari", "principale", "expense")
    with Session() as session:
        hashes = set(session.execute(select(Transaction.hash_dedup)).scalars())
        assert hashes == {base_hash, f"{base_hash}#1", f"{base_hash}#2"}


def test_create_transaction_retry_gives_409_when_ordinal_always_colliding():
    """Costante (finto) sempre occupato -> 409 dopo il numero massimo di tentativi,
    non un loop infinito."""
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)
    body = {**VALID_BODY, "category_id": cat_id}

    client.post("/transactions", json=body)  # hash base
    client.post("/transactions", json={**body, "allow_duplicate": True})  # occupa #1

    with patch.object(transactions_router, "_next_free_ordinal", return_value=1):
        resp = client.post("/transactions", json={**body, "allow_duplicate": True})

    assert resp.status_code == 409
    with Session() as session:
        # Solo le due righe create prima del patch: nessun inserimento spurio dal loop.
        assert session.query(Transaction).count() == 2


def test_create_transaction_rejects_non_positive_amount():
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)

    resp = client.post("/transactions", json={**VALID_BODY, "category_id": cat_id, "amount": 0})

    assert resp.status_code == 422


def test_create_transaction_rejects_invalid_type():
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)

    resp = client.post("/transactions", json={**VALID_BODY, "category_id": cat_id, "type": "transfer"})

    assert resp.status_code == 422


def test_create_transaction_rejects_date_too_far_in_future():
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)
    future_date = (datetime.utcnow() + timedelta(days=30)).isoformat()

    resp = client.post(
        "/transactions", json={**VALID_BODY, "category_id": cat_id, "date": future_date}
    )

    assert resp.status_code == 422
