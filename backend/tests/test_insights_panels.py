"""Test HTTP per `GET /insights/panels` (F13, ADR-0030). Stesso pattern di
`test_insights.py`: FastAPI + TestClient + StaticPool su sqlite in-memory.

`GET /insights` stesso e i suoi 5 test in `test_insights.py` NON sono toccati da
questo file. Copertura dell'aritmetica pura/per-funzione in
`test_insights_panels_service.py`; qui si verifica solo il wiring HTTP (nomi dei
query param, forma JSON di una risposta reale, DB vuoto)."""
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.models import Transaction
from app.routers import insights as insights_router
from app.services.insights import resolve_window_start


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
    app.include_router(insights_router.router)
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), Session


def _seed(Session):
    with Session() as session:
        session.add_all(
            [
                Transaction(
                    date=datetime(2026, 1, 10), amount=100.0, type="expense", category_raw="Alimentari",
                    account="principale", source="my_finance", hash_dedup="p1",
                ),
                Transaction(
                    date=datetime(2026, 1, 15), amount=50.0, type="expense", category_raw="Trasporti",
                    account="secondario", source="my_finance", hash_dedup="p2",
                ),
                Transaction(
                    date=datetime(2026, 1, 20), amount=1000.0, type="income", category_raw="Stipendio",
                    account="principale", source="my_finance", hash_dedup="p3",
                ),
                Transaction(
                    date=datetime(2026, 2, 5), amount=200.0, type="expense", category_raw="Alimentari",
                    account="principale", source="my_finance", hash_dedup="p4",
                ),
            ]
        )
        session.commit()


def test_insights_panels_empty_db_returns_empty_lists_and_zeroed_kpi():
    client, _Session = _build_test_app()

    resp = client.get("/insights/panels")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "kpi": {"income": 0.0, "expense": 0.0, "net": 0.0, "savings_rate": 0.0},
        "cumulative_balance": [],
        "cash_flow": [],
        "category_donut": [],
        "savings_trend": [],
        "month_over_month": {
            "current_month": None,
            "previous_month": None,
            "current": {},
            "previous": {},
            "delta_pct": {},
        },
    }


def test_insights_panels_full_shape_with_explicit_date_range():
    client, Session = _build_test_app()
    _seed(Session)

    resp = client.get(
        "/insights/panels",
        params={"date_from": "2026-01-01T00:00:00", "date_to": "2026-02-28T23:59:59"},
    )

    assert resp.status_code == 200
    body = resp.json()

    assert body["kpi"] == {"income": 1000.0, "expense": 350.0, "net": 650.0, "savings_rate": 0.65}
    assert body["cumulative_balance"] == [
        {"year_month": "2026-01", "balance": 850.0, "cumulative_balance": 850.0},
        {"year_month": "2026-02", "balance": -200.0, "cumulative_balance": 650.0},
    ]
    assert body["cash_flow"] == [
        {"year_month": "2026-01", "income": 1000.0, "expense": 150.0, "net": 850.0},
        {"year_month": "2026-02", "income": 0.0, "expense": 200.0, "net": -200.0},
    ]
    assert body["category_donut"] == [
        {"category_raw": "Alimentari", "total": 300.0},
        {"category_raw": "Trasporti", "total": 50.0},
    ]
    assert body["savings_trend"] == [
        {"year_month": "2026-01", "savings_rate": 0.85},
        {"year_month": "2026-02", "savings_rate": 0.0},
    ]
    assert body["month_over_month"]["current_month"] == "2026-02"
    assert body["month_over_month"]["previous_month"] == "2026-01"
    assert body["month_over_month"]["delta_pct"]["Trasporti"] == -100.0


def test_insights_panels_account_filter():
    client, Session = _build_test_app()
    _seed(Session)

    resp = client.get(
        "/insights/panels",
        params={"date_from": "2026-01-01T00:00:00", "account": "secondario"},
    )

    body = resp.json()
    assert body["category_donut"] == [{"category_raw": "Trasporti", "total": 50.0}]


def test_insights_panels_explicit_date_from_bypasses_months_default():
    client, Session = _build_test_app()
    _seed(Session)

    resp = client.get(
        "/insights/panels", params={"date_from": "2026-01-01T00:00:00", "months": 1}
    )

    year_months = {p["year_month"] for p in resp.json()["cash_flow"]}
    assert year_months == {"2026-01", "2026-02"}


def test_insights_panels_months_default_wiring_end_to_end():
    # Nessuna date_from: il default via `months` deve arrivare fino alla query
    # reale attraverso il router, non solo nel service testato direttamente.
    client, Session = _build_test_app()
    now = datetime.utcnow()
    this_month = datetime(now.year, now.month, 10)
    old_date = resolve_window_start(months=6, now=now) + timedelta(days=5)

    with Session() as session:
        session.add_all(
            [
                Transaction(
                    date=old_date, amount=40.0, type="expense", category_raw="Alimentari",
                    account="principale", source="my_finance", hash_dedup="w1",
                ),
                Transaction(
                    date=this_month, amount=60.0, type="expense", category_raw="Alimentari",
                    account="principale", source="my_finance", hash_dedup="w2",
                ),
            ]
        )
        session.commit()

    resp = client.get("/insights/panels", params={"months": 12})

    body = resp.json()
    assert len(body["cash_flow"]) == 2
    assert body["kpi"]["expense"] == 100.0


def test_insights_get_endpoint_still_returns_its_own_shape_unaffected():
    # Non un sostituto dei 5 test di test_insights.py (invariati altrove): solo
    # una verifica veloce che le due route coesistano senza interferenze.
    client, Session = _build_test_app()
    _seed(Session)

    resp = client.get("/insights")

    assert resp.status_code == 200
    assert set(resp.json().keys()) == {
        "monthly_trend", "category_breakdown", "cumulative_balance", "balance_by_account",
    }
