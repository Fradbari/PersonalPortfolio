"""Test diretti (no HTTP) per le funzioni F13 di `app/services/insights.py`
(ADR-0030): finestra `months`, `savings_rate_fraction` condivisa, `kpi_summary`,
`cash_flow`, `savings_trend`, `category_donut`, `month_over_month`,
`panels_summary`. Stesso pattern di `test_insights_service.py` (session diretta,
nessun TestClient): qui il service e' chiamato direttamente.

`GET /insights/panels` e il suo wiring HTTP sono testati separatamente in
`test_insights_panels.py`."""
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Transaction
from app.services.insights import (
    previous_year_month,
    resolve_window_start,
    savings_rate_fraction,
    cash_flow,
    category_donut,
    kpi_summary,
    month_over_month,
    panels_summary,
    savings_trend,
)


def _build_test_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    return Session


def _txn(**kwargs) -> Transaction:
    defaults = dict(currency="EUR", account="principale", source="my_finance")
    defaults.update(kwargs)
    return Transaction(**defaults)


# --- resolve_window_start (finestra `months`, risoluzione 1) -----------------


def test_resolve_window_start_12_months_ends_on_current_month():
    # 12 mesi calendario che finiscono a luglio 2026 incluso -> parte da agosto 2025.
    assert resolve_window_start(months=12, now=datetime(2026, 7, 27)) == datetime(2025, 8, 1)


def test_resolve_window_start_1_month_is_just_the_current_month():
    assert resolve_window_start(months=1, now=datetime(2026, 7, 27)) == datetime(2026, 7, 1)


def test_resolve_window_start_crosses_year_boundary():
    # 3 mesi calendario che finiscono a gennaio 2026 incluso -> parte da novembre 2025.
    assert resolve_window_start(months=3, now=datetime(2026, 1, 15)) == datetime(2025, 11, 1)


def test_resolve_window_start_12_months_from_january():
    # caso limite: mese corrente = gennaio, sottrarre 11 mesi scavalca l'anno due volte nel calcolo.
    assert resolve_window_start(months=12, now=datetime(2026, 1, 1)) == datetime(2025, 2, 1)


# --- previous_year_month (rollover anno) --------------------------------------


def test_previous_year_month_ordinary_month():
    assert previous_year_month("2026-07") == "2026-06"


def test_previous_year_month_january_rolls_back_to_december_prior_year():
    assert previous_year_month("2026-01") == "2025-12"


# --- savings_rate_fraction (condivisa fra kpi e savings_trend) -------------------------


def test_savings_rate_fraction_zero_income_is_zero_not_null_even_with_expense():
    assert savings_rate_fraction(0.0, 0.0) == 0.0
    assert savings_rate_fraction(0.0, 100.0) == 0.0


def test_savings_rate_fraction_ordinary_case():
    assert savings_rate_fraction(1000.0, 850.0) == 0.15


def test_savings_rate_fraction_negative_when_expense_exceeds_income():
    assert savings_rate_fraction(1000.0, 1200.0) == -0.2


def test_savings_rate_fraction_rounds_to_4_decimals():
    assert savings_rate_fraction(300.0, 100.0) == 0.6667


# --- kpi_summary (pura, da trend) ----------------------------------------------


def test_kpi_summary_sums_trend_and_shares_savings_rate_fraction_formula():
    trend = [
        {"year_month": "2026-01", "income": 1000.0, "expense": 150.0},
        {"year_month": "2026-02", "income": 300.0, "expense": 200.0},
    ]
    assert kpi_summary(trend) == {
        "income": 1300.0,
        "expense": 350.0,
        "net": 950.0,
        "savings_rate": 0.7308,
    }


def test_kpi_summary_empty_trend_is_all_zero():
    assert kpi_summary([]) == {"income": 0.0, "expense": 0.0, "net": 0.0, "savings_rate": 0.0}


# --- cash_flow (pura, da trend) ------------------------------------------------


def test_cash_flow_adds_net_per_month():
    trend = [
        {"year_month": "2026-01", "income": 1000.0, "expense": 150.0},
        {"year_month": "2026-02", "income": 300.0, "expense": 200.0},
    ]
    assert cash_flow(trend) == [
        {"year_month": "2026-01", "income": 1000.0, "expense": 150.0, "net": 850.0},
        {"year_month": "2026-02", "income": 300.0, "expense": 200.0, "net": 100.0},
    ]


def test_cash_flow_empty_trend_is_empty_list_not_padded():
    assert cash_flow([]) == []


# --- savings_trend (pura, da trend, stessa formula di kpi_summary) ------------


def test_savings_trend_per_point_matches_savings_rate_fraction_formula():
    trend = [
        {"year_month": "2026-01", "income": 1000.0, "expense": 150.0},
        {"year_month": "2026-02", "income": 300.0, "expense": 200.0},
    ]
    assert savings_trend(trend) == [
        {"year_month": "2026-01", "savings_rate": 0.85},
        {"year_month": "2026-02", "savings_rate": 0.3333},
    ]


def test_savings_trend_zero_income_month_is_zero_not_null():
    trend = [{"year_month": "2026-03", "income": 0.0, "expense": 40.0}]
    assert savings_trend(trend) == [{"year_month": "2026-03", "savings_rate": 0.0}]


# --- category_donut (top 6 + "Altro", solo spese) ------------------------------


def _seed_categories(session, amounts: dict[str, float], *, type_: str = "expense", account="principale"):
    for i, (cat, amount) in enumerate(amounts.items()):
        session.add(
            _txn(
                date=datetime(2026, 1, 10),
                amount=amount,
                type=type_,
                category_raw=cat,
                account=account,
                hash_dedup=f"cat-{i}-{cat}",
            )
        )
    session.commit()


def test_category_donut_8_categories_keeps_top_6_and_buckets_the_rest_as_altro():
    Session = _build_test_session()
    amounts = {
        "C1": 800.0, "C2": 700.0, "C3": 600.0, "C4": 500.0,
        "C5": 400.0, "C6": 300.0, "C7": 200.0, "C8": 100.0,
    }
    with Session() as session:
        _seed_categories(session, amounts)
        result = category_donut(session)

    assert len(result) == 7
    assert result[:6] == [
        {"category_raw": "C1", "total": 800.0},
        {"category_raw": "C2", "total": 700.0},
        {"category_raw": "C3", "total": 600.0},
        {"category_raw": "C4", "total": 500.0},
        {"category_raw": "C5", "total": 400.0},
        {"category_raw": "C6", "total": 300.0},
    ]
    assert result[6] == {"category_raw": "Altro", "total": 300.0}  # 200 + 100


def test_category_donut_orders_by_total_not_alphabetically():
    # Ordine alfabetico (A..H) opposto a quello per importo: distingue "top 6 per totale"
    # da "prime 6 in ordine alfabetico".
    Session = _build_test_session()
    amounts = {
        "Alfa": 10.0, "Beta": 20.0, "Gamma": 30.0, "Delta": 40.0,
        "Epsilon": 500.0, "Zeta": 600.0, "Eta": 700.0, "Theta": 800.0,
    }
    with Session() as session:
        _seed_categories(session, amounts)
        result = category_donut(session)

    assert result == [
        {"category_raw": "Theta", "total": 800.0},
        {"category_raw": "Eta", "total": 700.0},
        {"category_raw": "Zeta", "total": 600.0},
        {"category_raw": "Epsilon", "total": 500.0},
        {"category_raw": "Delta", "total": 40.0},
        {"category_raw": "Gamma", "total": 30.0},
        {"category_raw": "Altro", "total": 30.0},  # Beta 20 + Alfa 10
    ]


def test_category_donut_exactly_6_categories_has_no_altro_bucket():
    Session = _build_test_session()
    amounts = {"C1": 60.0, "C2": 50.0, "C3": 40.0, "C4": 30.0, "C5": 20.0, "C6": 10.0}
    with Session() as session:
        _seed_categories(session, amounts)
        result = category_donut(session)

    assert len(result) == 6
    assert all(row["category_raw"] != "Altro" for row in result)


def test_category_donut_exactly_7_categories_altro_is_just_the_7th():
    Session = _build_test_session()
    amounts = {"C1": 70.0, "C2": 60.0, "C3": 50.0, "C4": 40.0, "C5": 30.0, "C6": 20.0, "C7": 10.0}
    with Session() as session:
        _seed_categories(session, amounts)
        result = category_donut(session)

    assert len(result) == 7
    assert result[6] == {"category_raw": "Altro", "total": 10.0}


def test_category_donut_is_expense_only_income_never_appears():
    Session = _build_test_session()
    with Session() as session:
        session.add_all(
            [
                _txn(date=datetime(2026, 1, 5), amount=100.0, type="expense", category_raw="Alimentari",
                     hash_dedup="d1"),
                _txn(date=datetime(2026, 1, 6), amount=1000.0, type="income", category_raw="Stipendio",
                     hash_dedup="d2"),
            ]
        )
        session.commit()
        result = category_donut(session)

    assert result == [{"category_raw": "Alimentari", "total": 100.0}]


def test_category_donut_respects_account_filter():
    Session = _build_test_session()
    with Session() as session:
        session.add_all(
            [
                _txn(date=datetime(2026, 1, 5), amount=100.0, type="expense", category_raw="Alimentari",
                     account="principale", hash_dedup="a1"),
                _txn(date=datetime(2026, 1, 6), amount=40.0, type="expense", category_raw="Alimentari",
                     account="secondario", hash_dedup="a2"),
            ]
        )
        session.commit()
        result = category_donut(session, account="secondario")

    assert result == [{"category_raw": "Alimentari", "total": 40.0}]


# --- month_over_month -----------------------------------------------------------


def test_month_over_month_empty_db_is_null_months_and_empty_dicts():
    Session = _build_test_session()
    with Session() as session:
        result = month_over_month(session)

    assert result == {
        "current_month": None,
        "previous_month": None,
        "current": {},
        "previous": {},
        "delta_pct": {},
    }


def test_month_over_month_matches_frozen_contract_example():
    # Numeri presi alla lettera dall'esempio congelato in spec §7.
    Session = _build_test_session()
    with Session() as session:
        session.add_all(
            [
                _txn(date=datetime(2026, 6, 5), amount=98.00, type="expense", category_raw="Alimentari",
                     hash_dedup="f1"),
                _txn(date=datetime(2026, 6, 6), amount=60.00, type="expense", category_raw="Trasporti",
                     hash_dedup="f2"),
                _txn(date=datetime(2026, 7, 5), amount=120.50, type="expense", category_raw="Alimentari",
                     hash_dedup="f3"),
                _txn(date=datetime(2026, 7, 6), amount=45.00, type="expense", category_raw="Trasporti",
                     hash_dedup="f4"),
            ]
        )
        session.commit()
        result = month_over_month(session)

    assert result == {
        "current_month": "2026-07",
        "previous_month": "2026-06",
        "current": {"Alimentari": 120.50, "Trasporti": 45.00},
        "previous": {"Alimentari": 98.00, "Trasporti": 60.00},
        "delta_pct": {"Alimentari": 23.0, "Trasporti": -25.0},
    }


def test_month_over_month_rolls_over_year_boundary():
    Session = _build_test_session()
    with Session() as session:
        session.add_all(
            [
                _txn(date=datetime(2025, 12, 10), amount=50.0, type="expense", category_raw="Alimentari",
                     hash_dedup="y1"),
                _txn(date=datetime(2026, 1, 10), amount=70.0, type="expense", category_raw="Alimentari",
                     hash_dedup="y2"),
            ]
        )
        session.commit()
        result = month_over_month(session)

    assert result["current_month"] == "2026-01"
    assert result["previous_month"] == "2025-12"


def test_month_over_month_category_absent_from_previous_gives_null_delta():
    Session = _build_test_session()
    with Session() as session:
        session.add_all(
            [
                _txn(date=datetime(2026, 1, 10), amount=50.0, type="expense", category_raw="Alimentari",
                     hash_dedup="n1"),
                # "Intrattenimento" esiste solo nel mese corrente, assente dal precedente.
                _txn(date=datetime(2026, 2, 10), amount=30.0, type="expense", category_raw="Intrattenimento",
                     hash_dedup="n2"),
                _txn(date=datetime(2026, 2, 11), amount=55.0, type="expense", category_raw="Alimentari",
                     hash_dedup="n3"),
            ]
        )
        session.commit()
        result = month_over_month(session)

    assert result["current"]["Intrattenimento"] == 30.0
    assert result["previous"]["Intrattenimento"] == 0.0
    assert result["delta_pct"]["Intrattenimento"] is None


def test_month_over_month_category_absent_from_current_still_appears_as_zero():
    Session = _build_test_session()
    with Session() as session:
        session.add_all(
            [
                _txn(date=datetime(2026, 1, 10), amount=60.0, type="expense", category_raw="Trasporti",
                     hash_dedup="z1"),
                # febbraio non ha alcuna spesa "Trasporti".
                _txn(date=datetime(2026, 2, 10), amount=55.0, type="expense", category_raw="Alimentari",
                     hash_dedup="z2"),
            ]
        )
        session.commit()
        result = month_over_month(session)

    assert result["current"]["Trasporti"] == 0.0
    assert result["previous"]["Trasporti"] == 60.0
    assert result["delta_pct"]["Trasporti"] == -100.0


def test_month_over_month_excludes_income():
    Session = _build_test_session()
    with Session() as session:
        session.add_all(
            [
                _txn(date=datetime(2026, 1, 10), amount=50.0, type="expense", category_raw="Alimentari",
                     hash_dedup="i1"),
                _txn(date=datetime(2026, 1, 15), amount=1000.0, type="income", category_raw="Stipendio",
                     hash_dedup="i2"),
            ]
        )
        session.commit()
        result = month_over_month(session)

    assert "Stipendio" not in result["current"]
    assert "Stipendio" not in result["delta_pct"]


def test_month_over_month_respects_account_filter():
    Session = _build_test_session()
    with Session() as session:
        session.add_all(
            [
                _txn(date=datetime(2026, 1, 10), amount=50.0, type="expense", category_raw="Alimentari",
                     account="principale", hash_dedup="ac1"),
                _txn(date=datetime(2026, 1, 11), amount=999.0, type="expense", category_raw="Alimentari",
                     account="secondario", hash_dedup="ac2"),
            ]
        )
        session.commit()
        result = month_over_month(session, account="principale")

    assert result["current"] == {"Alimentari": 50.0}


# --- panels_summary (orchestratore) --------------------------------------------


def test_panels_summary_empty_db():
    Session = _build_test_session()
    with Session() as session:
        result = panels_summary(session)

    assert result == {
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


def test_panels_summary_explicit_date_from_bypasses_months_default():
    # months=1 sarebbe fortemente restrittivo se applicato: date_from esplicita
    # deve prevalere del tutto (risoluzione 1), quindi entrambi i mesi seminati
    # devono comparire lo stesso.
    Session = _build_test_session()
    with Session() as session:
        session.add_all(
            [
                _txn(date=datetime(2026, 1, 10), amount=100.0, type="expense", category_raw="Alimentari",
                     hash_dedup="ex1"),
                _txn(date=datetime(2026, 2, 10), amount=50.0, type="expense", category_raw="Alimentari",
                     hash_dedup="ex2"),
            ]
        )
        session.commit()
        result = panels_summary(session, date_from=datetime(2026, 1, 1), months=1)

    year_months = {p["year_month"] for p in result["cash_flow"]}
    assert year_months == {"2026-01", "2026-02"}


def test_panels_summary_months_default_truncates_not_pads():
    # Nessuna `date_from`: si applica il default via `months`. Il dataset ha solo
    # 2 mesi popolati dentro la finestra di 12 mesi -> l'output ne contiene 2,
    # MAI un array di 12 elementi con zeri di riempimento.
    Session = _build_test_session()
    now = datetime.utcnow()
    this_month = datetime(now.year, now.month, 15)
    six_months_back = resolve_window_start(months=6, now=now) + timedelta(days=10)

    with Session() as session:
        session.add_all(
            [
                _txn(date=six_months_back, amount=50.0, type="expense", category_raw="Alimentari",
                     hash_dedup="tr1"),
                _txn(date=this_month, amount=80.0, type="expense", category_raw="Alimentari",
                     hash_dedup="tr2"),
            ]
        )
        session.commit()
        result = panels_summary(session, months=12)

    assert len(result["cash_flow"]) == 2
    assert len(result["savings_trend"]) == 2
    year_months = {p["year_month"] for p in result["cash_flow"]}
    assert year_months == {
        f"{six_months_back.year:04d}-{six_months_back.month:02d}",
        f"{this_month.year:04d}-{this_month.month:02d}",
    }


def test_panels_summary_month_over_month_ignores_the_months_window():
    # `month_over_month` si ancora all'ultimo mese con dati REALI, non alla
    # finestra `months` mostrata dagli altri pannelli (risoluzione 5): una
    # transazione di 2 anni fa resta fuori da kpi/cash_flow (finestra a 12 mesi)
    # ma deve comunque comparire come current_month in month_over_month.
    Session = _build_test_session()
    now = datetime.utcnow()
    old_date = datetime(now.year - 2, now.month, 5)

    with Session() as session:
        session.add(
            _txn(date=old_date, amount=50.0, type="expense", category_raw="Alimentari", hash_dedup="old1")
        )
        session.commit()
        result = panels_summary(session, months=12)

    assert result["kpi"] == {"income": 0.0, "expense": 0.0, "net": 0.0, "savings_rate": 0.0}
    assert result["cash_flow"] == []
    assert result["month_over_month"]["current_month"] == f"{old_date.year:04d}-{old_date.month:02d}"
    assert result["month_over_month"]["current"] == {"Alimentari": 50.0}
