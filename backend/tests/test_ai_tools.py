"""Test per `app/ai/tools.py` — registry read-only del layer AI (F6, ADR-0023).

Nessun mock: il tool registry e' wrapper su query/service esistenti, testato su DB
di test reale (stesso pattern di test_insights_service.py). Il guardrail centrale
di questa fase e' "nessun tool puo' scrivere" — verificato sia in modo statico
(nessun token di scrittura nel sorgente del modulo) sia comportamentale (i conteggi
delle tabelle non cambiano dopo aver chiamato ogni tool)."""
from __future__ import annotations

import inspect
from datetime import datetime

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.ai.tools as tools_module
from app.ai.tools import (
    MAX_TOOL_ROWS,
    TOOLS,
    get_accounts,
    get_categories,
    get_insights,
    list_transactions,
    tool_declarations,
)
from app.db import Base
from app.models import Account, Category, Transaction


def _build_test_session():
    # StaticPool: connessione unica in-memory condivisa (stesso pattern di
    # test_insights_service.py — i tool sono chiamati direttamente, nessun TestClient).
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    return Session


def _seed(Session):
    with Session() as session:
        session.add_all([Category(name="Alimentari"), Category(name="Trasporti")])
        session.add_all(
            [
                Account(name="principale", display_name=None),
                Account(name="secondario", display_name="Conto Secondario"),
            ]
        )
        session.add_all(
            [
                Transaction(
                    date=datetime(2026, 1, 10), amount=100.0, type="expense", category_raw="Alimentari",
                    account="principale", source="my_finance", hash_dedup="h1",
                    comment="spesa mensile", tag="casa",
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


# --- list_transactions: filtri singoli ----------------------------------------


def test_list_transactions_no_filters_returns_all():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        result = list_transactions(session)

    assert result["total_matching"] == 4
    assert result["returned"] == 4
    assert len(result["rows"]) == 4
    assert result["truncated"] is False
    assert result.get("note") is None


def test_list_transactions_date_from_excludes_earlier_rows():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        result = list_transactions(session, date_from=datetime(2026, 2, 1))

    assert result["total_matching"] == 1
    assert result["rows"][0]["category_raw"] == "Alimentari"
    assert result["rows"][0]["date"].startswith("2026-02")


def test_list_transactions_date_to_excludes_later_rows():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        result = list_transactions(session, date_to=datetime(2026, 1, 31))

    assert result["total_matching"] == 3


def test_list_transactions_date_from_and_date_to_are_inclusive_at_boundaries():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        result = list_transactions(
            session, date_from=datetime(2026, 1, 10), date_to=datetime(2026, 1, 10)
        )

    assert result["total_matching"] == 1
    assert result["rows"][0]["amount"] == 100.0


def test_list_transactions_category_filter():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        result = list_transactions(session, category="Trasporti")

    assert result["total_matching"] == 1
    assert result["rows"][0]["account"] == "secondario"


def test_list_transactions_category_filter_matches_canonical_and_raw_domains():
    # Regression: `category_raw` (dominio fonte) e `Category.name` (dominio canonico,
    # quello restituito da get_categories) divergono non appena una categoria pending
    # viene riconciliata (vedi CategoryPending/CategoryMap in models.py) — category_raw
    # resta per sempre il testo originale, mentre category_id punta al canonico. Il
    # filtro deve accettare entrambi, altrimenti le transazioni gia' riconciliate
    # spariscono silenziosamente dal risultato.
    Session = _build_test_session()
    with Session() as session:
        category = Category(name="Alimentari")
        session.add(category)
        session.flush()
        session.add_all(
            [
                Transaction(
                    date=datetime(2026, 3, 1), amount=42.0, type="expense",
                    category_raw="spesa alimentare", category_id=category.id,
                    account="principale", source="my_finance", hash_dedup="rec-1",
                ),
                Transaction(
                    date=datetime(2026, 3, 2), amount=15.0, type="expense",
                    category_raw="Trasporti", account="principale", source="my_finance",
                    hash_dedup="rec-2",
                ),
            ]
        )
        session.commit()

    with Session() as session:
        by_canonical_name = list_transactions(session, category="Alimentari")
        by_raw_label = list_transactions(session, category="spesa alimentare")

    for result in (by_canonical_name, by_raw_label):
        assert result["total_matching"] == 1
        assert result["rows"][0]["category_raw"] == "spesa alimentare"
        assert result["rows"][0]["amount"] == 42.0


def test_list_transactions_account_filter():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        result = list_transactions(session, account="principale")

    assert result["total_matching"] == 3


def test_list_transactions_amount_min_filter():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        result = list_transactions(session, amount_min=200.0)

    amounts = sorted(r["amount"] for r in result["rows"])
    assert amounts == [200.0, 1000.0]


def test_list_transactions_amount_max_filter():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        result = list_transactions(session, amount_max=100.0)

    amounts = sorted(r["amount"] for r in result["rows"])
    assert amounts == [50.0, 100.0]


def test_list_transactions_type_filter():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        result = list_transactions(session, type="income")

    assert result["total_matching"] == 1
    assert result["rows"][0]["category_raw"] == "Stipendio"


def test_list_transactions_combines_category_and_account_filters():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        result = list_transactions(session, category="Alimentari", account="principale")

    assert result["total_matching"] == 2


def test_list_transactions_rows_include_comment_and_tag():
    # ADR-0023 p.9: comment/tag NON vanno esclusi "per prudenza".
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        result = list_transactions(session, account="principale", date_to=datetime(2026, 1, 10))

    assert result["rows"][0]["comment"] == "spesa mensile"
    assert result["rows"][0]["tag"] == "casa"


# --- list_transactions: cap righe / troncamento dichiarato ---------------------


def test_max_tool_rows_is_200():
    assert MAX_TOOL_ROWS == 200


def test_list_transactions_truncates_over_cap_and_declares_it():
    Session = _build_test_session()
    with Session() as session:
        session.add_all(
            [
                Transaction(
                    date=datetime(2026, 3, 1), amount=1.0, type="expense", category_raw="Varie",
                    account="principale", source="my_finance", hash_dedup=f"cap-{i}",
                )
                for i in range(205)
            ]
        )
        session.commit()

    with Session() as session:
        result = list_transactions(session)

    assert result["total_matching"] == 205
    assert result["returned"] == MAX_TOOL_ROWS
    assert len(result["rows"]) == MAX_TOOL_ROWS
    assert result["truncated"] is True
    assert result["note"] is not None
    assert "200" in result["note"]
    assert "205" in result["note"]


# --- get_insights: propaga i filtri al service layer ----------------------------


def test_get_insights_propagates_account_filter():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        result = get_insights(session, account="secondario")

    assert result == {
        "monthly_trend": [{"year_month": "2026-01", "income": 0.0, "expense": 50.0}],
        "category_breakdown": [{"category_raw": "Trasporti", "total": 50.0}],
        "cumulative_balance": [
            {"year_month": "2026-01", "balance": -50.0, "cumulative_balance": -50.0}
        ],
        # balance_by_account non accetta filtro account (aggregazione gia' per conto,
        # stesso comportamento di GET /insights, routers/insights.py)
        "balance_by_account": [
            {"account": "principale", "balance": 700.0},
            {"account": "secondario", "balance": -50.0},
        ],
    }


def test_get_insights_propagates_date_from_filter():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        result = get_insights(session, date_from=datetime(2026, 2, 1))

    assert result == {
        "monthly_trend": [{"year_month": "2026-02", "income": 0.0, "expense": 200.0}],
        "category_breakdown": [{"category_raw": "Alimentari", "total": 200.0}],
        "cumulative_balance": [
            {"year_month": "2026-02", "balance": -200.0, "cumulative_balance": -200.0}
        ],
        "balance_by_account": [{"account": "principale", "balance": -200.0}],
    }


# --- get_accounts / get_categories: wrapper diretti -----------------------------


def test_get_accounts_returns_all_accounts():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        result = get_accounts(session)

    assert result == [
        {"id": 1, "name": "principale", "display_name": None},
        {"id": 2, "name": "secondario", "display_name": "Conto Secondario"},
    ]


def test_get_categories_returns_all_categories():
    Session = _build_test_session()
    _seed(Session)

    with Session() as session:
        result = get_categories(session)

    assert result == [
        {"id": 1, "name": "Alimentari"},
        {"id": 2, "name": "Trasporti"},
    ]


# --- guardrail centrale: nessun tool di scrittura -------------------------------

_WRITE_VERBS = (
    "create", "insert", "update", "delete", "put", "patch", "post",
    "remove", "resolve", "backfill", "write", "add", "restore",
)


def test_registry_tool_names_contain_no_write_verb():
    for name in TOOLS:
        lowered = name.lower()
        for verb in _WRITE_VERBS:
            assert verb not in lowered, f"il tool '{name}' contiene il verbo di scrittura '{verb}'"


def test_registry_module_source_contains_no_write_statements():
    source = inspect.getsource(tools_module)
    forbidden_tokens = (
        "session.add(", "session.delete(", "session.commit(", "session.flush(",
        "insert(", "update(", "delete(",
    )
    for token in forbidden_tokens:
        assert token not in source, f"trovato token di scrittura vietato nel registry: {token!r}"


def test_tools_never_mutate_the_database():
    Session = _build_test_session()
    _seed(Session)

    def _counts(session):
        return (
            session.execute(select(func.count()).select_from(Transaction)).scalar_one(),
            session.execute(select(func.count()).select_from(Account)).scalar_one(),
            session.execute(select(func.count()).select_from(Category)).scalar_one(),
        )

    with Session() as session:
        before = _counts(session)

    with Session() as session:
        for fn in TOOLS.values():
            fn(session)
        session.commit()  # se un tool avesse scritto senza commit esplicito, lo rende comunque visibile

    with Session() as session:
        after = _counts(session)

    assert before == after


# --- tool_declarations(): schema JSON neutro rispetto al provider ---------------


def test_tool_declarations_covers_exactly_the_registry_no_orphans():
    declarations = tool_declarations()
    declared_names = [d["name"] for d in declarations]

    assert set(declared_names) == set(TOOLS.keys())
    assert len(declared_names) == len(set(declared_names))  # niente doppioni
    assert len(declarations) == len(TOOLS)


def test_tool_declarations_are_provider_neutral_json_schema():
    for decl in tool_declarations():
        assert set(decl.keys()) >= {"name", "description", "parameters"}
        assert isinstance(decl["description"], str) and decl["description"]
        params = decl["parameters"]
        assert params["type"] == "object"
        assert "properties" in params
        # forma neutra: niente chiavi specifiche di un provider (es. Gemini/OpenAI)
        assert "functionDeclarations" not in decl
        assert "function" not in decl
