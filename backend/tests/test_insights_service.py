from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Transaction
from app.services.insights import (
    balance_by_account,
    category_breakdown,
    cumulative_balance,
    monthly_trend,
)


def _build_test_session():
    # StaticPool: connessione unica in-memory condivisa, coerente col pattern di
    # test_insights.py (qui non serve TestClient/thread pool separato perché il
    # service e' chiamato direttamente, ma manteniamo lo stesso setup DB).
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    return Session


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
                Transaction(
                    date=datetime(2026, 2, 10), amount=300.0, type="income", category_raw="Bonus",
                    account="secondario", source="my_finance", hash_dedup="h5",
                ),
            ]
        )
        session.commit()


# --- monthly_trend -----------------------------------------------------------


def test_monthly_trend_no_filters_matches_unfiltered_output():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        trend = monthly_trend(session)

    assert trend == [
        {"year_month": "2026-01", "income": 1000.0, "expense": 150.0},
        {"year_month": "2026-02", "income": 300.0, "expense": 200.0},
    ]


def test_monthly_trend_date_from_excludes_earlier_rows():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        trend = monthly_trend(session, date_from=datetime(2026, 2, 1))

    assert trend == [{"year_month": "2026-02", "income": 300.0, "expense": 200.0}]


def test_monthly_trend_date_to_excludes_later_rows():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        trend = monthly_trend(session, date_to=datetime(2026, 1, 31))

    assert trend == [{"year_month": "2026-01", "income": 1000.0, "expense": 150.0}]


def test_monthly_trend_date_from_and_date_to_are_inclusive_at_boundaries():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        trend = monthly_trend(session, date_from=datetime(2026, 1, 10), date_to=datetime(2026, 1, 20))

    # esclude solo la riga di febbraio; le righe esattamente sui bordi (10 e 20) restano
    assert trend == [{"year_month": "2026-01", "income": 1000.0, "expense": 150.0}]


def test_monthly_trend_account_filter():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        trend = monthly_trend(session, account="secondario")

    assert trend == [
        {"year_month": "2026-01", "income": 0.0, "expense": 50.0},
        {"year_month": "2026-02", "income": 300.0, "expense": 0.0},
    ]


def test_monthly_trend_type_filter():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        trend = monthly_trend(session, type_="income")

    assert trend == [
        {"year_month": "2026-01", "income": 1000.0, "expense": 0.0},
        {"year_month": "2026-02", "income": 300.0, "expense": 0.0},
    ]


def test_monthly_trend_combines_date_and_account_filters():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        trend = monthly_trend(session, date_from=datetime(2026, 2, 1), account="principale")

    assert trend == [{"year_month": "2026-02", "income": 0.0, "expense": 200.0}]


# --- category_breakdown -------------------------------------------------------


def test_category_breakdown_default_type_preserves_expense_only_behavior():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        breakdown = {c["category_raw"]: c["total"] for c in category_breakdown(session)}

    assert breakdown == {"Alimentari": 300.0, "Trasporti": 50.0}


def test_category_breakdown_type_none_includes_income_too():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        breakdown = {c["category_raw"]: c["total"] for c in category_breakdown(session, type_=None)}

    assert breakdown == {
        "Alimentari": 300.0,
        "Trasporti": 50.0,
        "Stipendio": 1000.0,
        "Bonus": 300.0,
    }


def test_category_breakdown_account_filter():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        breakdown = {c["category_raw"]: c["total"] for c in category_breakdown(session, account="principale")}

    assert breakdown == {"Alimentari": 300.0}


def test_category_breakdown_date_range_inclusive_at_boundaries():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        breakdown = {
            c["category_raw"]: c["total"]
            for c in category_breakdown(
                session, date_from=datetime(2026, 1, 10), date_to=datetime(2026, 1, 10)
            )
        }

    assert breakdown == {"Alimentari": 100.0}


# --- balance_by_account --------------------------------------------------------


def test_balance_by_account_no_filters_matches_unfiltered_output():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        by_account = {b["account"]: b["balance"] for b in balance_by_account(session)}

    assert by_account == {"principale": 700.0, "secondario": 250.0}


def test_balance_by_account_date_filter():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        by_account = {
            b["account"]: b["balance"]
            for b in balance_by_account(session, date_from=datetime(2026, 2, 1))
        }

    assert by_account == {"principale": -200.0, "secondario": 300.0}


def test_balance_by_account_type_filter():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        by_account = {
            b["account"]: b["balance"]
            for b in balance_by_account(session, type_="income")
        }

    assert by_account == {"principale": 1000.0, "secondario": 300.0}


# --- cumulative_balance (invariata, puro in-memory) ----------------------------


def test_cumulative_balance_accumulates_across_months():
    trend = [
        {"year_month": "2026-01", "income": 1000.0, "expense": 150.0},
        {"year_month": "2026-02", "income": 300.0, "expense": 200.0},
    ]

    assert cumulative_balance(trend) == [
        {"year_month": "2026-01", "balance": 850.0, "cumulative_balance": 850.0},
        {"year_month": "2026-02", "balance": 100.0, "cumulative_balance": 950.0},
    ]
