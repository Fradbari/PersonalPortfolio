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
    """Comando speciale FTS5 con `rank=1` (fix post-review, Finding 1 CRITICAL): la
    forma SENZA l'argomento `rank` verifica solo la consistenza interna delle
    strutture FTS5 (le shadow table fra loro), NON il confronto con la content
    table esterna (`transactions`) — un trigger UPDATE rotto che facesse solo
    l'insert (mai la meta' delete) NON la farebbe sollevare, desincronizzando
    l'indice in silenzio (il vecchio termine resterebbe cercabile insieme al
    nuovo). La forma con `rank=1` include il confronto con la content table e
    rileva quel bug: verificato empiricamente che non solleva su trigger corretti
    e solleva `database disk image is malformed` su un trigger UPDATE insert-only.
    Richiede SQLite >= 3.41 (presente sia in locale sia nel container Docker del
    progetto).

    Le chiamate a questa funzione nei test sono affermazioni "non deve sollevare"
    — nessun try/except: se solleva, il test fallisce naturalmente."""
    connection.execute(
        text("INSERT INTO transactions_fts(transactions_fts, rank) VALUES ('integrity-check', 1)")
    )


def _match_count(connection, term: str) -> int:
    """Numero di righe che matchano `term` in `transactions_fts` — asserzione
    comportamentale diretta (fix post-review, Finding 1 CRITICAL), indipendente
    dalla versione SQLite: un trigger UPDATE rotto (solo insert, mai la meta'
    delete) lascerebbe il valore VECCHIO ancora cercabile dopo l'update. Usata nei
    test insieme a `_integrity_check` invece che da sola, come rete di sicurezza
    aggiuntiva."""
    row = connection.execute(
        text("SELECT COUNT(*) FROM transactions_fts WHERE transactions_fts MATCH :term"),
        {"term": term},
    ).fetchone()
    return row[0]


def _trigger_names(connection) -> list[str]:
    """Trigger il cui nome comincia per `trg_transactions_fts` (fix post-review,
    Finding 3 MINOR: filtro per prefisso invece di `type='trigger'` puro). Oggi e'
    innocuo perche' nessun'altra migration crea trigger, ma senza il filtro per
    prefisso un futuro trigger non-FTS romperebbe silenziosamente sia
    `== TRIGGER_NAMES` sia `== []` con un fallimento fuorviante in questo file."""
    rows = connection.execute(
        text(
            "SELECT name FROM sqlite_master "
            "WHERE type='trigger' AND name LIKE 'trg_transactions_fts%' "
            "ORDER BY name"
        )
    ).fetchall()
    return [row[0] for row in rows]


def _fts_object_names(connection) -> list[str]:
    """Tabelle il cui nome inizia per `transactions_fts` — la virtual table
    principale PIU' le shadow table FTS5 (`_data`, `_idx`, `_docsize`, `_config`).

    ATTENZIONE (fix post-review, Finding 2 IMPORTANT — la docstring originale
    affermava il contrario): benche' il filtro SQL includa `type='trigger'`,
    questa funzione NON intercetta MAI i 3 trigger di sincronizzazione — si
    chiamano `trg_transactions_fts_insert/_delete/_update` (prefisso `trg_`, non
    `transactions_fts`), quindi `LIKE 'transactions_fts%'` non li include mai. Per
    verificare che i trigger siano stati droppati (es. dopo un downgrade) usare
    SEMPRE `_trigger_names()` separatamente — vedi
    `test_round_trip_upgrade_downgrade_reupgrade`."""
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
    seguito da 'integrity-check' (fix post-review: ora con `rank=1`, verifica anche
    contro la content table esterna — vedi `_integrity_check`), non solleva —
    dimostra che la meta' DELETE del trigger UPDATE usa valori identici (stessa
    trasformazione RAW) a quelli indicizzati dall'INSERT originale.

    Copre entrambe le direzioni (fix post-review, Finding 4 MINOR — prima c'era
    solo NULL -> valore):
    - `txn_null_to_value`: `comment`/`tag` partono NULL (nullable in models.py) e
      diventano valorizzati;
    - `txn_value_to_null`: `comment`/`tag` partono valorizzati e diventano NULL —
      la direzione in cui l'indice deve PERDERE token, non solo guadagnarli.

    Oltre a 'integrity-check', verifica anche il comportamento diretto via MATCH
    (fix post-review, Finding 1 CRITICAL): un trigger UPDATE rotto (che facesse
    solo l'insert, mai la meta' delete — esattamente il bug che D6 deve prevenire)
    lascerebbe il valore VECCHIO ancora cercabile dopo l'update, cosa che la sola
    'integrity-check' SENZA `rank` non cattura (verificato empiricamente prima di
    questo fix, vedi report T3 e fix post-review)."""
    Session = sessionmaker(bind=fts_engine, future=True)
    with Session() as session:
        txn_null_to_value = _make_transaction(
            category_raw="Trasporti", comment=None, tag=None, hash_dedup="fts-crit2-null"
        )
        txn_value_to_null = _make_transaction(
            category_raw="Trasporti",
            comment="nota originale",
            tag="lavoro",
            hash_dedup="fts-crit2-tonull",
        )
        session.add_all([txn_null_to_value, txn_value_to_null])
        session.commit()

        txn_null_to_value.comment = "biglietto treno"
        txn_null_to_value.tag = "viaggio"
        txn_value_to_null.comment = None
        txn_value_to_null.tag = None
        session.commit()

    with fts_engine.connect() as conn:
        _integrity_check(conn)  # non deve sollevare (rank=1: content table inclusa)
        conn.commit()

    with fts_engine.connect() as conn:
        # NULL -> valore: il nuovo termine deve essere trovabile.
        assert _match_count(conn, "biglietto") == 1
        # valore -> NULL: il vecchio termine NON deve essere piu' trovabile. E'
        # l'assert che un trigger UPDATE insert-only (bug che D6 deve prevenire)
        # farebbe fallire, perche' lascerebbe il valore vecchio ancora indicizzato
        # insieme a quello nuovo.
        assert _match_count(conn, "originale") == 0


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
    -> 0 righe fra tabella+shadow table (`_fts_object_names`, prefisso
    `transactions_fts`) E 0 trigger (`_trigger_names`, verificato SEPARATAMENTE:
    fix post-review, Finding 2 IMPORTANT — i trigger si chiamano
    `trg_transactions_fts_*`, il pattern `LIKE 'transactions_fts%'` di
    `_fts_object_names` non li include mai, quindi prima di questo fix
    l'asserzione sui trigger dopo il downgrade non veniva mai fatta) ->
    re-upgrade a head -> 3 trigger + integrity-check OK.

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
        # Fix post-review (Finding 2 IMPORTANT): asserzione esplicita e separata
        # sui trigger — `_fts_object_names` sopra non li intercetta mai (vedi la
        # sua docstring), quindi senza questa riga il downgrade dei 3 trigger non
        # era mai verificato dal round-trip.
        assert _trigger_names(conn) == []

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
