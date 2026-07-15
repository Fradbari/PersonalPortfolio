from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import models FIRST to ensure they're registered with Base
from app.models import Category, Transaction
from app.db import Base, get_session
from app.routers import transactions as transactions_router


def _build_test_app():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True)
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


def _seed(Session) -> int:
    with Session() as session:
        cat = Category(name="Alimentari")
        session.add(cat)
        session.flush()
        cat_id = cat.id
        session.add_all(
            [
                Transaction(
                    date=datetime(2026, 1, 5), amount=10.0, currency="EUR", type="expense",
                    category_raw="Alimentari", category_id=cat_id, account="principale",
                    source="my_finance", hash_dedup="h1",
                ),
                Transaction(
                    date=datetime(2026, 2, 5), amount=1500.0, currency="EUR", type="income",
                    category_raw="Stipendio", account="principale",
                    source="my_finance", hash_dedup="h2",
                ),
            ]
        )
        session.commit()
    return cat_id


def test_list_transactions_returns_all_with_total():
    client, Session = _build_test_app()
    _seed(Session)

    resp = client.get("/transactions")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert body["page"] == 1
    assert body["page_size"] == 50


def test_list_transactions_filters_by_year_month():
    client, Session = _build_test_app()
    _seed(Session)

    resp = client.get("/transactions", params={"year_month": "2026-01"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["category_raw"] == "Alimentari"


def test_list_transactions_filters_by_type():
    client, Session = _build_test_app()
    _seed(Session)

    resp = client.get("/transactions", params={"type": "income"})

    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_update_transaction_edits_comment_tag_category():
    client, Session = _build_test_app()
    cat_id = _seed(Session)
    with Session() as session:
        txn_id = session.query(Transaction).filter_by(hash_dedup="h2").one().id

    resp = client.put(
        f"/transactions/{txn_id}",
        json={"comment": "nota", "tag": "extra", "category_id": cat_id},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["comment"] == "nota"
    assert body["tag"] == "extra"
    assert body["category_id"] == cat_id
    # campi stabili invariati (ADR-0005/ADR-0013)
    assert body["amount"] == 1500.0
    assert body["category_raw"] == "Stipendio"


def test_update_transaction_rejects_unknown_category():
    client, Session = _build_test_app()
    _seed(Session)
    with Session() as session:
        txn_id = session.query(Transaction).filter_by(hash_dedup="h1").one().id

    resp = client.put(f"/transactions/{txn_id}", json={"category_id": 999})

    assert resp.status_code == 404


def test_update_transaction_missing_returns_404():
    client, Session = _build_test_app()
    _seed(Session)

    resp = client.put("/transactions/999", json={"comment": "x"})

    assert resp.status_code == 404


def test_delete_transaction_removes_row():
    client, Session = _build_test_app()
    _seed(Session)
    with Session() as session:
        txn_id = session.query(Transaction).filter_by(hash_dedup="h1").one().id

    resp = client.delete(f"/transactions/{txn_id}")

    assert resp.status_code == 200
    assert resp.json() == {"deleted_id": txn_id}
    with Session() as session:
        assert session.query(Transaction).count() == 1


def test_delete_transaction_missing_returns_404():
    client, Session = _build_test_app()
    _seed(Session)

    resp = client.delete("/transactions/999")

    assert resp.status_code == 404
