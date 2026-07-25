"""Test di `POST /transactions` (T7, F11/ADR-0028): inserimento manuale, ordinale
`#n`, 409 su duplicato, compatibilita' con l'importer."""
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.ingestion.reconciliation import compute_hash_dedup
from app.models import Account, Category, Transaction
from app.routers import transactions as transactions_router


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
    app.include_router(transactions_router.router)
    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), Session


def _seed_category(Session, name="Alimentari") -> int:
    with Session() as session:
        cat = Category(name=name)
        session.add(cat)
        session.commit()
        return cat.id


VALID_BODY = {
    "date": "2026-01-05T00:00:00",
    "amount": 12.5,
    "currency": "EUR",
    "type": "expense",
    "account": "principale",
    "comment": "pranzo",
    "tag": None,
}


def test_create_transaction_unknown_category_returns_404_and_no_insert():
    client, Session = _build_test_app()

    resp = client.post("/transactions", json={**VALID_BODY, "category_id": 999})

    assert resp.status_code == 404
    with Session() as session:
        assert session.query(Transaction).count() == 0


def test_create_transaction_success_sets_manual_source_and_null_batch():
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)

    resp = client.post("/transactions", json={**VALID_BODY, "category_id": cat_id})

    assert resp.status_code == 200
    expected_hash = compute_hash_dedup(
        datetime(2026, 1, 5), 12.5, "Alimentari", "principale", "expense"
    )
    with Session() as session:
        row = session.execute(
            select(Transaction.source, Transaction.import_batch_id, Transaction.hash_dedup).where(
                Transaction.hash_dedup == expected_hash
            )
        ).one()
        assert row.source == "manual"
        assert row.import_batch_id is None


def test_create_transaction_registers_account_as_is():
    """ADR-0006: conti ignoti importati as-is, anche per l'inserimento manuale — senza
    questo, un conto digitato a mano nel form non comparirebbe mai in `/accounts`."""
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)

    resp = client.post(
        "/transactions", json={**VALID_BODY, "category_id": cat_id, "account": "conto-nuovo"}
    )

    assert resp.status_code == 200
    with Session() as session:
        assert session.execute(select(Account).where(Account.name == "conto-nuovo")).scalar_one_or_none() is not None


def test_create_transaction_duplicate_without_allow_returns_409_with_twin():
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)
    body = {**VALID_BODY, "category_id": cat_id}

    first = client.post("/transactions", json=body)
    assert first.status_code == 200
    twin_id = first.json()["id"]

    second = client.post("/transactions", json=body)

    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["transaction"]["id"] == twin_id
    with Session() as session:
        assert session.query(Transaction).count() == 1


def test_create_transaction_first_insert_race_returns_409_not_500():
    """Finding #3 IMPORTANT (review post-T7): il primo insert (hash BASE, ramo
    `twin is None`) non era protetto da IntegrityError. Due richieste quasi
    simultanee (doppio click/retry browser, ADR-0028 p.5 "mai un 500") vedono
    entrambe twin=None e tentano entrambe l'insert con lo stesso hash base; quella
    che committa seconda deve prendere un 409, non un 500.

    Vera concorrenza non e' simulabile con TestClient sincrono/fixture a connessione
    singola (stesso limite dichiarato per i test di retry sotto). Qui si inietta il
    commit "vincente" della richiesta concorrente tramite side_effect su
    get_or_create_account — l'ultimo hook eseguito prima di session.add(txn) nel
    ramo `twin is None` — cosi' il nostro session.commit() incontra per davvero il
    vincolo UNIQUE gia' occupato sulla stessa sessione/connessione."""
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)
    body = {**VALID_BODY, "category_id": cat_id}
    base_hash = compute_hash_dedup(datetime(2026, 1, 5), 12.5, "Alimentari", "principale", "expense")

    def _concurrent_winner(session, account):
        session.add(
            Transaction(
                date=datetime(2026, 1, 5),
                amount=12.5,
                currency="EUR",
                type="expense",
                category_id=cat_id,
                category_raw="Alimentari",
                account="principale",
                comment="arrivata-prima-per-la-race",
                tag=None,
                source="manual",
                import_batch_id=None,
                hash_dedup=base_hash,
            )
        )
        session.commit()

    with patch.object(transactions_router, "get_or_create_account", side_effect=_concurrent_winner):
        resp = client.post("/transactions", json=body)

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["message"]
    assert detail["transaction"]["comment"] == "arrivata-prima-per-la-race"
    with Session() as session:
        # Solo la riga "vincente" iniettata dalla race: il nostro tentativo perdente
        # non deve aver lasciato una seconda riga (ne' spurie da un 500 a meta').
        assert session.query(Transaction).count() == 1


def test_create_transaction_duplicate_with_allow_duplicate_creates_ordinal_1():
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)
    body = {**VALID_BODY, "category_id": cat_id}

    first = client.post("/transactions", json=body)
    assert first.status_code == 200

    second = client.post("/transactions", json={**body, "allow_duplicate": True})

    assert second.status_code == 200
    base_hash = compute_hash_dedup(datetime(2026, 1, 5), 12.5, "Alimentari", "principale", "expense")
    with Session() as session:
        hashes = set(session.execute(select(Transaction.hash_dedup)).scalars())
        assert hashes == {base_hash, f"{base_hash}#1"}


def test_create_transaction_importer_lookup_does_not_match_ordinal_suffix():
    """Criterio T7 #3: l'importer deduplica con `.in_(hashes)` (match esatto) su hash
    calcolati dai dati sorgente — che sono sempre hash BASE, mai suffissati. Una riga
    manuale forzata (`#1`) non deve quindi mai risultare "duplicato" di un futuro
    import con gli stessi campi stabili."""
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)
    body = {**VALID_BODY, "category_id": cat_id}

    client.post("/transactions", json=body)
    client.post("/transactions", json={**body, "allow_duplicate": True})  # crea #1

    reimport_hash = compute_hash_dedup(datetime(2026, 1, 5), 12.5, "Alimentari", "principale", "expense")
    with Session() as session:
        matched = set(
            session.execute(
                select(Transaction.hash_dedup).where(Transaction.hash_dedup.in_([reimport_hash]))
            ).scalars()
        )
    # Il match esatto trova SOLO la riga base, mai la #1, anche se questa condivide
    # tutti i campi stabili con l'hash ricalcolato dall'importer.
    assert matched == {reimport_hash}


def test_create_transaction_natural_ordinal_progression_without_mocking():
    """Finding #4 IMPORTANT (review post-T7): i test sul ramo allow_duplicate fanno
    al massimo UN inserimento forzato reale (sempre #1, il caso banale max_n=0) o
    patchano _next_free_ordinal con un mock; il ciclo che scorre gli hash esistenti
    e calcola max_n = max(...) sui suffissi gia' presenti non viene mai eseguito da
    un test reale. Qui tre POST consecutivi identici, SENZA alcun mock: il primo
    prende l'hash base, il secondo e il terzo devono prendere #1 poi #2 in sequenza
    naturale (letta dal DB reale, non da un valore finto)."""
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)
    body = {**VALID_BODY, "category_id": cat_id}

    first = client.post("/transactions", json=body)
    second = client.post("/transactions", json={**body, "allow_duplicate": True})
    third = client.post("/transactions", json={**body, "allow_duplicate": True})

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200

    base_hash = compute_hash_dedup(datetime(2026, 1, 5), 12.5, "Alimentari", "principale", "expense")
    with Session() as session:
        hashes = set(session.execute(select(Transaction.hash_dedup)).scalars())
        assert hashes == {base_hash, f"{base_hash}#1", f"{base_hash}#2"}


def test_create_transaction_retry_succeeds_on_second_attempt_when_ordinal_stale():
    """Simula l'effetto osservabile di una race fra due richieste concorrenti: la
    prima lettura dell'ordinale libero e' stale (restituisce un valore gia' occupato),
    l'INSERT solleva IntegrityError sul vincolo UNIQUE, e il retry con una nuova
    lettura ha successo. La concorrenza vera non e' simulabile con TestClient
    sincrono/fixture a connessione singola (dichiarato in ADR-0028 p.5) — qui si
    verifica che il MECCANISMO di retry sia corretto dato un conflitto reale."""
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)
    body = {**VALID_BODY, "category_id": cat_id}

    client.post("/transactions", json=body)  # hash base
    client.post("/transactions", json={**body, "allow_duplicate": True})  # occupa #1

    with patch.object(transactions_router, "_next_free_ordinal", side_effect=[1, 2]):
        resp = client.post("/transactions", json={**body, "allow_duplicate": True})

    assert resp.status_code == 200
    base_hash = compute_hash_dedup(datetime(2026, 1, 5), 12.5, "Alimentari", "principale", "expense")
    with Session() as session:
        hashes = set(session.execute(select(Transaction.hash_dedup)).scalars())
        assert hashes == {base_hash, f"{base_hash}#1", f"{base_hash}#2"}


def test_create_transaction_registers_new_account_after_forced_ordinal_retry():
    """Finding #2 IMPORTANT (review post-T7): get_or_create_account era chiamata UNA
    SOLA volta, fuori dal loop di retry. Su un IntegrityError il rollback scartava
    anche la riga Account in sospeso (add+flush, mai commit) di quel tentativo, e il
    tentativo successivo (quello che riesce) non la ripeteva piu' -> il conto non
    veniva mai registrato in `accounts`, violando ADR-0006 silenziosamente.

    Si seminano DIRETTAMENTE (bypassando l'endpoint, quindi senza mai passare da
    get_or_create_account) hash base + #1 per un conto MAI registrato prima, cosi'
    che l'unica strada per vederlo comparire in `accounts` sia il retry stesso.
    Poi si forza una collisione sul primo tentativo (stesso meccanismo di mock gia'
    usato nel test sopra) e si conferma che dopo il retry riuscito la riga esiste."""
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)
    account_name = "conto-mai-registrato-prima"

    base_hash = compute_hash_dedup(datetime(2026, 1, 5), 12.5, "Alimentari", account_name, "expense")
    with Session() as session:
        session.add(
            Transaction(
                date=datetime(2026, 1, 5), amount=12.5, currency="EUR", type="expense",
                category_id=cat_id, category_raw="Alimentari", account=account_name,
                source="manual", import_batch_id=None, hash_dedup=base_hash,
            )
        )
        session.add(
            Transaction(
                date=datetime(2026, 1, 5), amount=12.5, currency="EUR", type="expense",
                category_id=cat_id, category_raw="Alimentari", account=account_name,
                source="manual", import_batch_id=None, hash_dedup=f"{base_hash}#1",
            )
        )
        session.commit()

    with Session() as session:
        # Precondizione: nessuno ha mai chiamato get_or_create_account per questo conto.
        assert (
            session.execute(select(Account).where(Account.name == account_name)).scalar_one_or_none()
            is None
        )

    body = {**VALID_BODY, "category_id": cat_id, "account": account_name, "allow_duplicate": True}
    with patch.object(transactions_router, "_next_free_ordinal", side_effect=[1, 2]):
        resp = client.post("/transactions", json=body)

    assert resp.status_code == 200
    with Session() as session:
        assert (
            session.execute(select(Account).where(Account.name == account_name)).scalar_one_or_none()
            is not None
        )


def test_create_transaction_retry_gives_409_when_ordinal_always_colliding():
    """Costante (finto) sempre occupato -> 409 dopo il numero massimo di tentativi,
    non un loop infinito. Finding #5 (review post-T7): shape del detail uniforme con
    gli altri 409 — sempre {message, transaction} — qui transaction=None perche' non
    c'e' una gemella specifica, e' un esaurimento di tentativi, non un duplicato."""
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)
    body = {**VALID_BODY, "category_id": cat_id}

    client.post("/transactions", json=body)  # hash base
    client.post("/transactions", json={**body, "allow_duplicate": True})  # occupa #1

    with patch.object(transactions_router, "_next_free_ordinal", return_value=1):
        resp = client.post("/transactions", json={**body, "allow_duplicate": True})

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["message"]
    assert detail["transaction"] is None
    with Session() as session:
        # Solo le due righe create prima del patch: nessun inserimento spurio dal loop.
        assert session.query(Transaction).count() == 2


def test_create_transaction_rejects_non_positive_amount():
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)

    resp = client.post("/transactions", json={**VALID_BODY, "category_id": cat_id, "amount": 0})

    assert resp.status_code == 422


def test_create_transaction_rejects_invalid_type():
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)

    resp = client.post("/transactions", json={**VALID_BODY, "category_id": cat_id, "type": "transfer"})

    assert resp.status_code == 422


def test_create_transaction_rejects_date_too_far_in_future():
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)
    future_date = (datetime.utcnow() + timedelta(days=30)).isoformat()

    resp = client.post(
        "/transactions", json={**VALID_BODY, "category_id": cat_id, "date": future_date}
    )

    assert resp.status_code == 422


def test_create_transaction_accepts_naive_and_timezone_aware_dates():
    """Finding #1 CRITICAL (review post-T7): una data ISO con timezone (`Z` o offset
    esplicito) produce un datetime aware; il validator confrontava con un `limit`
    naive (`datetime.utcnow()`), sollevando TypeError — che Pydantic v2 NON converte
    in 422 (solo ValueError/AssertionError) — quindi l'eccezione sfuggiva come 500.
    `Date.toISOString()` in JS produce SEMPRE il formato con `Z`: il form React di
    T10 l'avrebbe mandata sistematicamente. Tre forme, importi diversi per evitare
    collisioni di hash: nessuna delle tre deve dare 500."""
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)

    naive = client.post(
        "/transactions",
        json={**VALID_BODY, "category_id": cat_id, "date": "2026-01-05T10:00:00", "amount": 10.0},
    )
    with_z = client.post(
        "/transactions",
        json={**VALID_BODY, "category_id": cat_id, "date": "2026-01-05T10:00:00Z", "amount": 20.0},
    )
    with_offset = client.post(
        "/transactions",
        json={**VALID_BODY, "category_id": cat_id, "date": "2026-01-05T12:00:00+02:00", "amount": 30.0},
    )

    assert naive.status_code == 200
    assert with_z.status_code == 200
    assert with_offset.status_code == 200


def test_create_transaction_normalizes_offset_date_to_utc_for_hash_and_storage():
    """Finding #1, parte (b): un input con offset che attraversa la mezzanotte UTC
    (23:30 orario -05:00 = 04:30 del giorno DOPO in UTC) deve riflettersi, sia nella
    colonna `date` salvata sia nell'hash_dedup, nel giorno 06 (conversione UTC
    corretta) — non nel giorno 05 che darebbe il troncamento naive dell'orario
    locale (bug pre-fix: compute_hash_dedup formatta solo %Y-%m-%d sul valore che
    il validator restituisce)."""
    client, Session = _build_test_app()
    cat_id = _seed_category(Session)

    resp = client.post(
        "/transactions",
        json={**VALID_BODY, "category_id": cat_id, "date": "2026-01-05T23:30:00-05:00"},
    )

    assert resp.status_code == 200
    expected_utc = datetime(2026, 1, 6, 4, 30, 0)
    expected_hash = compute_hash_dedup(expected_utc, 12.5, "Alimentari", "principale", "expense")
    with Session() as session:
        row = session.execute(
            select(Transaction.date, Transaction.hash_dedup).where(
                Transaction.hash_dedup == expected_hash
            )
        ).one()
        assert row.date == expected_utc
        assert row.hash_dedup == expected_hash
