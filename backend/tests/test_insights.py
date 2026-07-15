from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.models import Transaction
from app.routers import insights as insights_router


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
    app.include_router(insights_router.router)
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), Session


def _seed(Session):
    with Session() as session:
        session.add_all(
            [
                Transaction(
                    date=datetime(2026, 1, 10), amount=100.0, type="expense", category_raw="Alimentari",
                    account="principale", source="my_finance", hash_dedup="h1",
                ),
                Transaction(
                    date=datetime(2026, 1, 15), amount=50.0, type="expense", category_raw="Trasporti",
                    account="secondario", source="my_finance", hash_dedup="h2",
                ),
                Transaction(
                    date=datetime(2026, 1, 20), amount=1000.0, type="income", category_raw="Stipendio",
                    account="principale", source="my_finance", hash_dedup="h3",
                ),
                Transaction(
                    date=datetime(2026, 2, 5), amount=200.0, type="expense", category_raw="Alimentari",
                    account="principale", source="my_finance", hash_dedup="h4",
                ),
            ]
        )
        session.commit()


def test_monthly_trend_groups_income_and_expense_by_month():
    client, Session = _build_test_app()
    _seed(Session)

    resp = client.get("/insights")

    assert resp.status_code == 200
    trend = resp.json()["monthly_trend"]
    assert trend == [
        {"year_month": "2026-01", "income": 1000.0, "expense": 150.0},
        {"year_month": "2026-02", "income": 0.0, "expense": 200.0},
    ]


def test_category_breakdown_sums_expense_by_category_raw():
    client, Session = _build_test_app()
    _seed(Session)

    resp = client.get("/insights")

    breakdown = {b["category_raw"]: b["total"] for b in resp.json()["category_breakdown"]}
    assert breakdown == {"Alimentari": 300.0, "Trasporti": 50.0}


def test_cumulative_balance_accumulates_across_months():
    client, Session = _build_test_app()
    _seed(Session)

    resp = client.get("/insights")

    cumulative = resp.json()["cumulative_balance"]
    assert cumulative == [
        {"year_month": "2026-01", "balance": 850.0, "cumulative_balance": 850.0},
        {"year_month": "2026-02", "balance": -200.0, "cumulative_balance": 650.0},
    ]


def test_balance_by_account_nets_income_minus_expense():
    client, Session = _build_test_app()
    _seed(Session)

    resp = client.get("/insights")

    by_account = {b["account"]: b["balance"] for b in resp.json()["balance_by_account"]}
    assert by_account == {"principale": 700.0, "secondario": -50.0}


def test_insights_empty_db_returns_empty_lists():
    client, _Session = _build_test_app()

    resp = client.get("/insights")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "monthly_trend": [],
        "category_breakdown": [],
        "cumulative_balance": [],
        "balance_by_account": [],
    }
