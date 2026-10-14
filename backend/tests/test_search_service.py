"""Test di `app/services/search.py` (T5, F12/ADR-0029)."""
from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Transaction
from app.services.search import build_match_expression, fts_available, rebuild_fts_index

HOSTILE_INPUTS = [
    '"',
    "*",
    "-x",
    "NEAR(a b)",
    "AND",
    "()",
    "'",
    "😀 emoji test",
]


# ---------------------------------------------------------------------------
# build_match_expression — funzione pura, nessun DB necessario per None/vuoto.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("q", [None, "", "   ", "\t\n"])
def test_build_match_expression_none_on_empty_or_blank(q):
    assert build_match_expression(q) is None


def test_build_match_expression_single_token():
    assert build_match_expression("pranzo") == '"pranzo"*'


def test_build_match_expression_multi_token_space_separated():
    assert build_match_expression("pranzo fuori") == '"pranzo"* "fuori"*'


def test_build_match_expression_escapes_embedded_double_quote():
    # Una virgoletta doppia interna va raddoppiata (escape FTS5), non lasciata singola:
    # una singola `"` non bilanciata romperebbe la sintassi della stringa quotata.
    assert build_match_expression('foo"bar') == '"foo""bar"*'


@pytest.mark.parametrize("q", HOSTILE_INPUTS)
def test_build_match_expression_hostile_inputs_never_raise_on_real_fts5(q):
    """Ogni input ostile deve produrre un'espressione MATCH sintatticamente valida —
    verificato contro un vero indice FTS5 in memoria, non solo per ispezione della
    stringa. Nessuna parola chiave FTS5 (AND/OR/NOT/NEAR), parentesi o virgoletta
    spaiata deve poter causare un errore di sintassi: sono tutte diventate testo
    letterale dentro il quoting di `build_match_expression`."""
    engine = create_engine("sqlite://", future=True)
    with engine.connect() as conn:
        conn.execute(text("CREATE VIRTUAL TABLE t USING fts5(body)"))
        conn.execute(text("INSERT INTO t(rowid, body) VALUES (1, 'riga di prova')"))
        conn.commit()

        expr = build_match_expression(q)
        assert expr is not None  # tutti gli input ostili qui sono non-vuoti
        # Non deve sollevare OperationalError (errore di sintassi FTS5).
        conn.execute(text("SELECT rowid FROM t WHERE t MATCH :expr"), {"expr": expr})


def test_build_match_expression_and_is_literal_not_operator():
    """`AND` non deve comportarsi da operatore booleano: quotato, cerca la parola
    letterale "AND" nel testo, non applica un AND fra i token vicini."""
    engine = create_engine("sqlite://", future=True)
    with engine.connect() as conn:
        conn.execute(text("CREATE VIRTUAL TABLE t USING fts5(body)"))
        conn.execute(text("INSERT INTO t(rowid, body) VALUES (1, 'contiene la parola AND qui')"))
        conn.execute(text("INSERT INTO t(rowid, body) VALUES (2, 'nessuna parola chiave qui')"))
        conn.commit()

        expr = build_match_expression("AND")
        rows = conn.execute(text("SELECT rowid FROM t WHERE t MATCH :expr"), {"expr": expr}).fetchall()
        assert [r[0] for r in rows] == [1]


# ---------------------------------------------------------------------------
# fts_available — richiede un vero DB (migrato o no).
# ---------------------------------------------------------------------------


def test_fts_available_true_on_migrated_db(fts_engine):
    Session = sessionmaker(bind=fts_engine, future=True)
    with Session() as session:
        assert fts_available(session) is True


def test_fts_available_false_when_table_missing():
    # Base.metadata.create_all(): stesso schema usato dal resto della suite prima di
    # T3 — non conosce le virtual table, quindi `transactions_fts` non esiste qui.
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as session:
        assert fts_available(session) is False


# ---------------------------------------------------------------------------
# rebuild_fts_index — ricostruisce l'indice da `transactions` anche se
# `transactions_fts` è stato desincronizzato manualmente (simula il caso reale:
# un restore sovrascrive `transactions` senza passare dai trigger).
# ---------------------------------------------------------------------------


def test_rebuild_fts_index_resyncs_after_manual_desync(fts_engine):
    Session = sessionmaker(bind=fts_engine, future=True)
    with Session() as session:
        txn = Transaction(
            date=datetime(2026, 3, 1),
            amount=42.0,
            currency="EUR",
            type="expense",
            category_raw="Alimentari",
            account="principale",
            comment="pranzo aziendale",
            tag=None,
            source="my_finance",
            hash_dedup="rebuild-test-1",
        )
        session.add(txn)
        session.commit()
        txn_id = txn.id

    # Desincronizza manualmente l'indice: rimuove la riga da transactions_fts SENZA
    # passare dal trigger DELETE (che invece terrebbe tutto coerente) — simula lo
    # stato in cui un restore lascerebbe l'indice se nessuno lo ricostruisse.
    with fts_engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO transactions_fts(transactions_fts, rowid, comment, tag, category_raw, account) "
                "VALUES ('delete', :id, 'pranzo aziendale', NULL, 'Alimentari', 'principale')"
            ),
            {"id": txn_id},
        )
        conn.commit()

        rows = conn.execute(
            text("SELECT rowid FROM transactions_fts WHERE transactions_fts MATCH 'pranzo'")
        ).fetchall()
        assert rows == []  # desincronizzato: la riga non si trova più

    rebuild_fts_index(fts_engine)

    with fts_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT rowid FROM transactions_fts WHERE transactions_fts MATCH 'pranzo'")
        ).fetchall()
        assert [r[0] for r in rows] == [txn_id]  # rebuild ha ripristinato la riga
        conn.execute(text("INSERT INTO transactions_fts(transactions_fts) VALUES ('integrity-check')"))
        conn.commit()
