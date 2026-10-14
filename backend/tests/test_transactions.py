from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.models import Category, Transaction
from app.routers import transactions as transactions_router
from conftest import run_alembic_upgrade


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


def _build_fts_test_app(tmp_path):
    """Come `_build_test_app()`, ma su un DB migrato per davvero con Alembic (T3/T4,
    fixture `fts_engine` di `conftest.py`) invece di `Base.metadata.create_all()`:
    serve solo ai test che esercitano il filtro `q` (`transactions_fts` esiste solo
    dopo la migration 0005, mai su `create_all()`)."""
    db_path = tmp_path / "transactions_router_fts_test.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    with engine.connect() as connection:
        run_alembic_upgrade(connection)
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


def test_list_transactions_pagination_stable_with_same_date():
    # DEBT-01: senza tiebreaker su id, righe con la stessa date possono duplicarsi
    # o saltare tra pagine consecutive (ordine non garantito da SQLite in assenza di
    # una seconda chiave di ordinamento esplicita).
    client, Session = _build_test_app()
    with Session() as session:
        same_date = datetime(2026, 3, 10)
        session.add_all(
            [
                Transaction(
                    date=same_date, amount=float(i), currency="EUR", type="expense",
                    category_raw="Alimentari", account="principale",
                    source="my_finance", hash_dedup=f"same-date-{i}",
                )
                for i in range(5)
            ]
        )
        session.commit()

    seen_ids: list[int] = []
    for page in (1, 2, 3):
        resp = client.get("/transactions", params={"page": page, "page_size": 2})
        assert resp.status_code == 200
        seen_ids.extend(item["id"] for item in resp.json()["items"])

    assert len(seen_ids) == 5
    assert len(set(seen_ids)) == 5  # nessuna riga duplicata tra pagine
    assert seen_ids == sorted(seen_ids, reverse=True)  # date.desc() + id.desc() -> id decrescente


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


def test_update_transaction_ignores_immutable_fields_in_body():
    client, Session = _build_test_app()
    _seed(Session)
    with Session() as session:
        txn = session.query(Transaction).filter_by(hash_dedup="h1").one()
        txn_id = txn.id
        original_amount = txn.amount
        original_date = txn.date.isoformat()
        original_category_raw = txn.category_raw
        original_account = txn.account
        original_type = txn.type
        original_hash = txn.hash_dedup

    resp = client.put(
        f"/transactions/{txn_id}",
        json={
            "comment": "nota",
            "amount": 999999.0,
            "date": "2099-12-31T00:00:00",
            "category_raw": "Hackerata",
            "account": "conto-fantasma",
            "type": "income",
            "hash_dedup": "manomesso",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["comment"] == "nota"  # editable field applied
    # campi stabili invariati (ADR-0005/ADR-0013) nonostante il tentativo nel body
    assert body["amount"] == original_amount
    assert body["date"] == original_date
    assert body["category_raw"] == original_category_raw
    assert body["account"] == original_account
    assert body["type"] == original_type
    with Session() as session:
        assert session.get(Transaction, txn_id).hash_dedup == original_hash


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


# ---------------------------------------------------------------------------
# T6 (F12, ADR-0029): filtri avanzati, group_by, ricerca full-text.
# ---------------------------------------------------------------------------


def test_list_transactions_filters_by_date_range():
    client, Session = _build_test_app()
    _seed(Session)  # h1: 2026-01-05 (Alimentari), h2: 2026-02-05 (Stipendio)

    resp = client.get("/transactions", params={"date_from": "2026-02-01"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["category_raw"] == "Stipendio"

    resp = client.get("/transactions", params={"date_to": "2026-01-31"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["category_raw"] == "Alimentari"


def test_list_transactions_filters_by_amount_range():
    client, Session = _build_test_app()
    _seed(Session)  # importi: 10.0 (Alimentari) e 1500.0 (Stipendio)

    resp = client.get("/transactions", params={"amount_min": 100})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["amount"] == 1500.0

    resp = client.get("/transactions", params={"amount_max": 100})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["amount"] == 10.0


def test_list_transactions_filters_by_tag():
    client, Session = _build_test_app()
    with Session() as session:
        session.add_all(
            [
                Transaction(
                    date=datetime(2026, 1, 5), amount=10.0, currency="EUR", type="expense",
                    category_raw="Alimentari", account="principale", tag="lavoro",
                    source="my_finance", hash_dedup="tag-1",
                ),
                Transaction(
                    date=datetime(2026, 1, 6), amount=20.0, currency="EUR", type="expense",
                    category_raw="Alimentari", account="principale", tag=None,
                    source="my_finance", hash_dedup="tag-2",
                ),
            ]
        )
        session.commit()

    resp = client.get("/transactions", params={"tag": "lavoro"})

    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["amount"] == 10.0


def test_list_transactions_group_by_category_returns_subtotals():
    client, Session = _build_test_app()
    with Session() as session:
        session.add_all(
            [
                Transaction(
                    date=datetime(2026, 1, 5), amount=10.0, currency="EUR", type="expense",
                    category_raw="Alimentari", account="principale",
                    source="my_finance", hash_dedup="g1",
                ),
                Transaction(
                    date=datetime(2026, 1, 6), amount=20.0, currency="EUR", type="expense",
                    category_raw="Alimentari", account="principale",
                    source="my_finance", hash_dedup="g2",
                ),
                Transaction(
                    date=datetime(2026, 2, 1), amount=100.0, currency="EUR", type="income",
                    category_raw="Stipendio", account="principale",
                    source="my_finance", hash_dedup="g3",
                ),
            ]
        )
        session.commit()

    resp = client.get("/transactions", params={"group_by": "category"})

    assert resp.status_code == 200
    body = resp.json()
    assert "items" not in body  # ramo a short-circuit: solo subtotali (rettifica ADR-0029 p.6)
    groups = {g["key"]: g for g in body["groups"]}
    assert groups["Alimentari"] == {"key": "Alimentari", "count": 2, "total": 30.0}
    assert groups["Stipendio"] == {"key": "Stipendio", "count": 1, "total": 100.0}


def test_list_transactions_group_by_ignores_pagination():
    client, Session = _build_test_app()
    with Session() as session:
        session.add_all(
            [
                Transaction(
                    date=datetime(2026, 1, d), amount=1.0, currency="EUR", type="expense",
                    category_raw="Alimentari", account="principale",
                    source="my_finance", hash_dedup=f"page-{d}",
                )
                for d in range(1, 6)
            ]
        )
        session.commit()

    # page_size=1 non deve spezzare il subtotale del gruppo fra due pagine: il ramo
    # group_by ignora page/page_size per costruzione (rettifica ADR-0029 p.6).
    resp = client.get("/transactions", params={"group_by": "category", "page": 1, "page_size": 1})

    assert resp.status_code == 200
    groups = resp.json()["groups"]
    assert len(groups) == 1
    assert groups[0]["count"] == 5
    assert groups[0]["total"] == 5.0


def test_list_transactions_group_by_month_and_account():
    client, Session = _build_test_app()
    with Session() as session:
        session.add_all(
            [
                Transaction(
                    date=datetime(2026, 1, 5), amount=10.0, currency="EUR", type="expense",
                    category_raw="Alimentari", account="principale",
                    source="my_finance", hash_dedup="ma1",
                ),
                Transaction(
                    date=datetime(2026, 2, 5), amount=20.0, currency="EUR", type="expense",
                    category_raw="Alimentari", account="secondario",
                    source="my_finance", hash_dedup="ma2",
                ),
            ]
        )
        session.commit()

    resp = client.get("/transactions", params={"group_by": "month"})
    months = {g["key"]: g for g in resp.json()["groups"]}
    assert months["2026-01"]["total"] == 10.0
    assert months["2026-02"]["total"] == 20.0

    resp = client.get("/transactions", params={"group_by": "account"})
    accounts = {g["key"]: g for g in resp.json()["groups"]}
    assert accounts["principale"]["total"] == 10.0
    assert accounts["secondario"]["total"] == 20.0


def test_list_transactions_group_by_combined_with_active_filter():
    """Important dalla review T6: nessun test copriva group_by insieme a un filtro
    attivo. `conditions` e' costruita una volta sola e riusata identica da entrambi i
    rami (group_by e paginato) — qui si verifica che il subtotale rifletta SOLO le
    righe che passano anche il filtro, non l'intero dataset."""
    client, Session = _build_test_app()
    with Session() as session:
        session.add_all(
            [
                Transaction(
                    date=datetime(2026, 1, 5), amount=10.0, currency="EUR", type="expense",
                    category_raw="Alimentari", account="principale", tag="lavoro",
                    source="my_finance", hash_dedup="cf1",
                ),
                Transaction(
                    date=datetime(2026, 1, 6), amount=20.0, currency="EUR", type="expense",
                    category_raw="Alimentari", account="principale", tag=None,
                    source="my_finance", hash_dedup="cf2",
                ),
                Transaction(
                    date=datetime(2026, 2, 1), amount=100.0, currency="EUR", type="expense",
                    category_raw="Alimentari", account="principale", tag="lavoro",
                    source="my_finance", hash_dedup="cf3",
                ),
            ]
        )
        session.commit()

    resp = client.get("/transactions", params={"group_by": "category", "tag": "lavoro"})

    assert resp.status_code == 200
    groups = resp.json()["groups"]
    # Solo cf1 e cf3 hanno tag="lavoro": cf2 (senza tag) resta fuori dal subtotale.
    assert groups == [{"key": "Alimentari", "count": 2, "total": 110.0}]


def test_list_transactions_full_text_search_matches_comment(tmp_path):
    client, Session = _build_fts_test_app(tmp_path)
    with Session() as session:
        session.add_all(
            [
                Transaction(
                    date=datetime(2026, 1, 5), amount=10.0, currency="EUR", type="expense",
                    category_raw="Alimentari", account="principale",
                    comment="pranzo fuori con amici", source="my_finance", hash_dedup="q1",
                ),
                Transaction(
                    date=datetime(2026, 1, 6), amount=20.0, currency="EUR", type="expense",
                    category_raw="Alimentari", account="principale",
                    comment="spesa supermercato", source="my_finance", hash_dedup="q2",
                ),
            ]
        )
        session.commit()

    resp = client.get("/transactions", params={"q": "pranzo"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["comment"] == "pranzo fuori con amici"


def test_list_transactions_full_text_search_hostile_query_never_500(tmp_path):
    """q con parole chiave/sintassi FTS5 (AND, parentesi, virgolette spaiate) non deve
    mai dare 500: `build_match_expression` (T5) le neutralizza in testo letterale."""
    client, _ = _build_fts_test_app(tmp_path)

    resp = client.get("/transactions", params={"q": 'AND ("unbalanced'})

    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_list_transactions_q_blank_means_no_filter(tmp_path):
    client, Session = _build_fts_test_app(tmp_path)
    _seed(Session)

    resp = client.get("/transactions", params={"q": "   "})

    assert resp.status_code == 200
    assert resp.json()["total"] == 2


def test_list_transactions_q_returns_503_when_fts_unavailable():
    # Base.metadata.create_all(): transactions_fts esiste solo dopo la migration 0005,
    # quindi qui non c'e' mai. Deve rispondere 503, mai un 500 con lo stack SQLite grezzo.
    client, Session = _build_test_app()
    _seed(Session)

    resp = client.get("/transactions", params={"q": "pranzo"})

    assert resp.status_code == 503
