"""Test permanente dei trigger FTS5 su `transactions_fts` (migration 0005, ADR-0029).

Gira SEMPRE su un DB migrato per davvero con Alembic (fixture `fts_engine`,
`conftest.py`), mai su `Base.metadata.create_all()`: quest'ultimo non conosce le
virtual table SQLite e non creerebbe ne' `transactions_fts` ne' i 3 trigger — un test
scritto sopra `create_all()` sarebbe un falso positivo (le asserzioni sui trigger non
proverebbero nulla, perche' i trigger semplicemente non ci sarebbero mai stati).
"""
from datetime import datetime

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models import Transaction
from conftest import BACKEND_DIR, run_alembic_downgrade, run_alembic_upgrade

TRIGGER_NAMES = [
    "trg_transactions_fts_delete",
    "trg_transactions_fts_insert",
    "trg_transactions_fts_update",
]

# Snapshot del DB reale catturato all'IMPORT di questo modulo — prima che qualunque
# test/fixture qui dentro possa girare. Usato solo da `test_real_db_untouched_...`
# alla fine del file (criterio 5).
_REAL_DB_PATH = BACKEND_DIR.parent / "data" / "portfolio.db"
_REAL_DB_STAT_BEFORE = _REAL_DB_PATH.stat() if _REAL_DB_PATH.exists() else None


def _integrity_check(connection) -> None:
    """Comando speciale FTS5: solleva se l'indice e la content table sono
    desincronizzati. Le chiamate a questa funzione nei test sono affermazioni "non deve
    sollevare" — nessun try/except: se solleva, il test fallisce naturalmente."""
    connection.execute(text("INSERT INTO transactions_fts(transactions_fts) VALUES ('integrity-check')"))


def _trigger_names(connection) -> list[str]:
    rows = connection.execute(
        text("SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name")
    ).fetchall()
    return [row[0] for row in rows]


def _fts_object_names(connection) -> list[str]:
    """Tabelle/trigger il cui nome inizia per `transactions_fts` — la virtual table
    principale PIU' le shadow table FTS5 (`_data`, `_idx`, `_docsize`, `_config`)."""
    rows = connection.execute(
        text(
            "SELECT name FROM sqlite_master "
            "WHERE type IN ('table','trigger') AND name LIKE 'transactions_fts%'"
        )
    ).fetchall()
    return [row[0] for row in rows]


def _make_transaction(**overrides) -> Transaction:
    defaults = dict(
        date=datetime(2026, 1, 5),
        amount=12.5,
        currency="EUR",
        type="expense",
        category_raw="Alimentari",
        account="principale",
        comment=None,
        tag=None,
        source="my_finance",
        hash_dedup="fts-test-default",
    )
    defaults.update(overrides)
    return Transaction(**defaults)


def test_integrity_check_ok_after_insert_update_delete(fts_engine):
    """Criterio 1 (brief T3): 'integrity-check' non solleva dopo insert + update +
    delete su `transactions`."""
    Session = sessionmaker(bind=fts_engine, future=True)
    with Session() as session:
        txn = _make_transaction(
            comment="pranzo fuori", tag="lavoro", hash_dedup="fts-crit1"
        )
        session.add(txn)
        session.commit()

        txn.comment = "cena in famiglia"
        session.commit()

        session.delete(txn)
        session.commit()

    with fts_engine.connect() as conn:
        _integrity_check(conn)  # non deve sollevare
        conn.commit()


def test_integrity_check_ok_after_update_comment_and_tag_d6(fts_engine):
    """Criterio 2 / vincolo D6 (brief T3): un UPDATE che modifica `comment` o `tag`,
    seguito da 'integrity-check', non solleva — dimostra che la meta' DELETE del
    trigger UPDATE usa valori identici (stessa trasformazione RAW) a quelli indicizzati
    dall'INSERT originale. Parte anche da `comment`/`tag` NULL (nullable in
    models.py) per coprire la transizione NULL -> valore, non solo valore -> valore."""
    Session = sessionmaker(bind=fts_engine, future=True)
    with Session() as session:
        txn = _make_transaction(
            category_raw="Trasporti", comment=None, tag=None, hash_dedup="fts-crit2"
        )
        session.add(txn)
        session.commit()

        txn.comment = "biglietto treno"
        txn.tag = "viaggio"
        session.commit()

    with fts_engine.connect() as conn:
        _integrity_check(conn)  # non deve sollevare
        conn.commit()


def test_batch_alter_table_recreate_always_drops_triggers(fts_engine):
    """Criterio 3 (brief T3): test permanente dei trigger — canary di D4, non fix.

    NOTA IMPORTANTE — correzione al punto 3(d) del piano approvato, verificata
    empiricamente prima di scrivere questo test (Alembic 1.14.0 reale, la stessa
    versione pinnata in requirements.txt): il piano diceva letteralmente "i 3
    trigger esistono ancora" dopo il `batch_alter_table(recreate='always')` del
    punto (c). E' FALSO, ed e' anche internamente incoerente con la motivazione
    data nello stesso punto per usare "always" invece di "never" (se i trigger
    sopravvivessero comunque ad "always", la scelta fra i due valori sarebbe
    indifferente — non lo e'). Verificato che (a) la ricostruzione grezza
    rename->create->copy->drop droppa il trigger, (b) il vero
    `Operations.batch_alter_table(recreate="always")` di Alembic da' lo stesso
    risultato, (c) un listener SQLAlchemy `after_create` sulla `Table` Python
    originale non si riattiva sulla tabella-ombra che Alembic costruisce
    internamente — quindi non esiste una contromisura automatica.

    Questo test DIMOSTRA il pericolo (D4), non lo risolve: e' un canary che deve
    restare rumoroso se in futuro qualcuno rompesse la disciplina "nessun altro
    batch_alter_table su `transactions` dopo la revision 0005" (vedi docstring
    della migration e ADR-0029). Se un giorno questa asserzione iniziasse a
    fallire perche' i trigger SOPRAVVIVONO, sarebbe una notizia importante (un
    cambio di comportamento Alembic/SQLite) e non un test da "aggiustare" al
    volo — fermarsi e capire perche', non invertire l'asserzione.
    """
    with fts_engine.connect() as conn:
        # (a) upgrade head e' gia' applicato dalla fixture `fts_engine`.
        # (b) i 3 trigger esistono.
        assert _trigger_names(conn) == TRIGGER_NAMES

        # (c) batch_alter_table(recreate="always") forza la ricostruzione
        # rename->create->copy->drop anche per un add_column altrimenti innocuo.
        # "always" e' obbligatorio: con "never" Alembic non ricostruirebbe la
        # tabella (nessun cambiamento richiede la ricostruzione per un semplice
        # add_column su SQLite) e i trigger sopravvivrebbero perche' la tabella
        # non sarebbe mai stata toccata — il test non proverebbe nulla.
        ctx = MigrationContext.configure(conn, opts={"render_as_batch": True})
        op = Operations(ctx)
        with op.batch_alter_table("transactions", recreate="always") as batch_op:
            batch_op.add_column(sa.Column("_fts_canary_probe", sa.String(), nullable=True))

        # (d) CORRETTO rispetto al testo letterale del piano (vedi nota sopra):
        # i 3 trigger sono SPARITI, non sopravvissuti.
        assert _trigger_names(conn) == []


def test_round_trip_upgrade_downgrade_reupgrade(fts_engine):
    """Criterio 4 (brief T3): round-trip completo.

    upgrade (gia' fatto dalla fixture) -> integrity-check OK -> downgrade a 0004
    -> 0 righe FTS (tabella + shadow table + trigger, tutte con prefisso
    `transactions_fts`) -> re-upgrade a head -> 3 trigger + integrity-check OK.

    Downgrade esplicito alla revision "0004" (non relativo "-1"): resta corretto
    anche se in futuro `head` si spostasse oltre 0005 per migration successive non
    legate a `transactions`/FTS5 — "0004" e' sempre "subito prima che FTS5
    esistesse", indipendentemente da quante revision vengano aggiunte dopo.
    """
    with fts_engine.connect() as conn:
        assert _trigger_names(conn) == TRIGGER_NAMES
        _integrity_check(conn)
        conn.commit()

    with fts_engine.connect() as conn:
        run_alembic_downgrade(conn, "0004")
        conn.commit()

    with fts_engine.connect() as conn:
        assert _fts_object_names(conn) == []

    with fts_engine.connect() as conn:
        run_alembic_upgrade(conn, "head")
        conn.commit()

    with fts_engine.connect() as conn:
        assert _trigger_names(conn) == TRIGGER_NAMES
        _integrity_check(conn)
        conn.commit()


def test_real_db_untouched_by_fts_trigger_tests():
    """Criterio 5 (brief T3): `data/portfolio.db` reale intatto dopo il run — questa
    infrastruttura di test usa esclusivamente `tmp_path` (vedi `fts_engine` in
    `conftest.py`), mai il DB reale.

    Confronta lo stato del file (dimensione + mtime) catturato all'IMPORT di questo
    modulo — quindi prima che qualunque test/fixture qui dentro potesse girare — con lo
    stato attuale. Dichiarato come test invece che solo come garanzia di design, cosi'
    una futura fixture che tocchi per errore `settings.db_path` verrebbe scoperta qui.
    Va per ultima nel file: pytest esegue i test in ordine di dichiarazione (nessun
    plugin di randomizzazione in requirements-dev.txt), quindi a questo punto tutti i
    test sopra sono gia' girati.
    """
    if _REAL_DB_STAT_BEFORE is None:
        if _REAL_DB_PATH.exists():
            pytest.fail(
                "data/portfolio.db e' stato CREATO durante il run della suite: "
                "qualcosa ha scritto sul path del DB reale."
            )
        pytest.skip("data/portfolio.db non presente in questo ambiente: nulla da proteggere.")

    after = _REAL_DB_PATH.stat()
    assert after.st_size == _REAL_DB_STAT_BEFORE.st_size
    assert after.st_mtime == _REAL_DB_STAT_BEFORE.st_mtime
