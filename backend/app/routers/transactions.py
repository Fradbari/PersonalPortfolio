"""`/transactions` — lista filtrata/paginata, edit campi editabili, delete (F5, ADR-0019).
Filtri avanzati, ricerca full-text e raggruppamento (F12, ADR-0029).

Campi editabili: SOLO `comment`/`tag`/`category_id`. `date`/`amount`/`category_raw`/
`account`/`type`/`hash_dedup` restano immutabili post-import (ADR-0005/ADR-0013)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy import func, literal_column, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.ingestion.reconciliation import compute_hash_dedup, get_or_create_account
from app.models import Category, Transaction
from app.services.search import build_match_expression, fts_available

router = APIRouter(tags=["transactions"])

# Oltre questa soglia una data futura e' probabilmente un errore di battitura
# (es. anno sbagliato) piu' che un inserimento pianificato deliberato — ma non e'
# un rifiuto secco (rettifica ADR-0028, CP1 2026-07-25): l'utente puo' confermare
# comunque con `confirm_future_date: true`, stessa logica del duplicato consapevole.
MAX_FUTURE_DAYS = 1

# Tentativi massimi per trovare un ordinale #n libero prima di arrendersi con 409
# (ADR-0028 p.5, rettifica 2026-07-25: retry su UNIQUE, mai BEGIN IMMEDIATE).
MAX_ORDINAL_ATTEMPTS = 8


def _serialize(t: Transaction) -> dict:
    return {
        "id": t.id,
        "date": t.date.isoformat(),
        "amount": t.amount,
        "currency": t.currency,
        "type": t.type,
        "category_id": t.category_id,
        "category_raw": t.category_raw,
        "account": t.account,
        "comment": t.comment,
        "tag": t.tag,
        "source": t.source,
    }


class CreateTransactionRequest(BaseModel):
    date: datetime
    amount: float
    currency: str = "EUR"
    type: str
    category_id: int
    account: str
    comment: Optional[str] = None
    tag: Optional[str] = None
    allow_duplicate: bool = False
    confirm_future_date: bool = False

    @field_validator("amount")
    @classmethod
    def _amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("amount deve essere maggiore di zero")
        return v

    @field_validator("type")
    @classmethod
    def _type_valid(cls, v: str) -> str:
        if v not in ("expense", "income"):
            raise ValueError("type deve essere 'expense' o 'income'")
        return v

    @field_validator("date")
    @classmethod
    def _normalize_date(cls, v: datetime) -> datetime:
        # Solo normalizzazione qui, MAI un reject: la soglia sul futuro e' un
        # avviso da confermare (endpoint, vedi `confirm_future_date`), non un
        # errore di validazione. Un client che manda una data con timezone (es.
        # `Date.toISOString()` in JS, sempre in questo formato) produce un
        # datetime aware; compute_hash_dedup e la colonna DB si aspettano naive
        # — normalizzare qui garantisce che ogni consumatore veda sempre e solo
        # UTC naive, mai il troncamento silenzioso dell'orario locale.
        if v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v


def _next_free_ordinal(session: Session, base_hash: str) -> int:
    """Prossimo ordinale libero per `<base_hash>#n`. Richiamata a ogni giro del loop
    di retry sottostante: sotto una race genuina fra due richieste concorrenti una
    lettura puo' risultare stale fra questa SELECT e la INSERT dell'altra richiesta —
    per questo il chiamante ricalcola da capo a ogni tentativo invece di riusare il
    valore del giro precedente (best-effort su pysqlite serializzato, copertura di
    concorrenza dichiarata non simulata, spec Blocco B §4)."""
    prefix = f"{base_hash}#"
    existing = session.execute(
        select(Transaction.hash_dedup).where(Transaction.hash_dedup.like(f"{prefix}%"))
    ).scalars().all()
    max_n = 0
    for h in existing:
        suffix = h[len(prefix):]
        if suffix.isdigit():
            max_n = max(max_n, int(suffix))
    return max_n + 1


def _is_hash_dedup_unique_violation(exc: IntegrityError) -> bool:
    msg = str(exc.orig)
    return "UNIQUE constraint failed" in msg and "hash_dedup" in msg


@router.post("/transactions")
def create_transaction(body: CreateTransactionRequest, session: Session = Depends(get_session)):
    # Ordine vincolante (ADR-0028 punto 2): lookup categoria -> 404 PRIMA di derivare
    # category_raw. Invertire produrrebbe category_raw=None su una colonna NOT NULL,
    # cioe' un IntegrityError/500 opaco invece di un 404 che nomina la categoria mancante.
    category = session.get(Category, body.category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Categoria non trovata.")

    # Data oltre soglia: avviso da confermare, non un rifiuto secco (CP1
    # 2026-07-25, rettifica ADR-0028). Stessa meccanica del duplicato sotto —
    # 409 + un flag esplicito per procedere comunque — cosi' il frontend gestisce
    # entrambi i casi con lo stesso pattern "409 -> dialog di conferma -> resubmit".
    # Controllato PRIMA dell'hash/duplicato: e' un avviso sull'input, indipendente
    # dai dati gia' presenti, non serve toccare il DB per saperlo.
    future_limit = datetime.utcnow() + timedelta(days=MAX_FUTURE_DAYS)
    if body.date > future_limit and not body.confirm_future_date:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"La data e' piu' di {MAX_FUTURE_DAYS} giorno/i nel futuro. Confermi l'inserimento?",
                "reason": "future_date",
                "transaction": None,
            },
        )

    category_raw = category.name
    base_hash = compute_hash_dedup(body.date, body.amount, category_raw, body.account, body.type)

    twin = session.execute(
        select(Transaction).where(Transaction.hash_dedup == base_hash)
    ).scalar_one_or_none()

    if twin is not None and not body.allow_duplicate:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Esiste gia' una transazione identica.",
                "reason": "duplicate",
                "transaction": _serialize(twin),
            },
        )

    def _build(hash_dedup: str) -> Transaction:
        return Transaction(
            date=body.date,
            amount=body.amount,
            currency=body.currency,
            type=body.type,
            category_id=body.category_id,
            category_raw=category_raw,
            account=body.account,
            comment=body.comment,
            tag=body.tag,
            source="manual",
            import_batch_id=None,
            hash_dedup=hash_dedup,
        )

    if twin is None:
        # Prima transazione manuale con questi campi stabili: hash BASE, senza
        # suffisso — l'importer deve poter continuare a trovarla con .in_() (ADR-0005).
        # get_or_create_account e' DENTRO questo ramo (non prima, condivisa con il
        # ramo sotto): su un IntegrityError il rollback scarterebbe anche la riga
        # Account rimasta in sospeso (add+flush, mai commit) di questo tentativo.
        txn = _build(base_hash)
        get_or_create_account(session, body.account)
        session.add(txn)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            if not _is_hash_dedup_unique_violation(exc):
                raise
            # Doppio invio quasi simultaneo (ADR-0028 p.5, "mai un 500"): l'altra
            # richiesta ha gia' committato lo stesso hash base fra la nostra
            # lettura di `twin` e questo commit. Risolvi come duplicato, stessa
            # shape del 409 esplicito qui sopra — non un 500.
            gemella = session.execute(
                select(Transaction).where(Transaction.hash_dedup == base_hash)
            ).scalar_one_or_none()
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Esiste gia' una transazione identica.",
                    "reason": "duplicate",
                    "transaction": _serialize(gemella) if gemella is not None else None,
                },
            )
        session.refresh(txn)
        return _serialize(txn)

    # allow_duplicate=True da qui in poi: serve un ordinale #n libero.
    for _ in range(MAX_ORDINAL_ATTEMPTS):
        candidate_hash = f"{base_hash}#{_next_free_ordinal(session, base_hash)}"
        txn = _build(candidate_hash)
        # Idem sopra: ripetuta a ogni tentativo, non prima del loop, altrimenti un
        # rollback su IntegrityError scarterebbe la riga Account in sospeso del
        # tentativo fallito. Idempotente per costruzione (get_or_create_account
        # controlla "esiste gia'?" prima di inserire): ripeterla e' innocuo.
        get_or_create_account(session, body.account)
        session.add(txn)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            if not _is_hash_dedup_unique_violation(exc):
                raise
            continue
        session.refresh(txn)
        return _serialize(txn)

    raise HTTPException(
        status_code=409,
        detail={
            "message": "Impossibile assegnare un ordinale libero dopo piu' tentativi concorrenti.",
            "reason": "ordinal_exhausted",
            "transaction": None,
        },
    )


@router.get("/transactions")
def list_transactions(
    year_month: Optional[str] = Query(default=None, description="Filtro YYYY-MM"),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    category_id: Optional[int] = None,
    account: Optional[str] = None,
    type_: Optional[str] = Query(default=None, alias="type"),
    amount_min: Optional[float] = None,
    amount_max: Optional[float] = None,
    tag: Optional[str] = None,
    q: Optional[str] = Query(default=None, description="Ricerca full-text (FTS5)"),
    group_by: Optional[Literal["category", "month", "account"]] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    conditions = []
    if year_month:
        conditions.append(func.strftime("%Y-%m", Transaction.date) == year_month)
    if date_from is not None:
        conditions.append(Transaction.date >= date_from)
    if date_to is not None:
        conditions.append(Transaction.date <= date_to)
    if category_id is not None:
        conditions.append(Transaction.category_id == category_id)
    if account is not None:
        conditions.append(Transaction.account == account)
    if type_ is not None:
        conditions.append(Transaction.type == type_)
    if amount_min is not None:
        conditions.append(Transaction.amount >= amount_min)
    if amount_max is not None:
        conditions.append(Transaction.amount <= amount_max)
    if tag is not None:
        conditions.append(Transaction.tag == tag)

    match_expr = build_match_expression(q)
    if match_expr is not None:
        # Guard esplicito, mai un 500 opaco: se l'indice manca (DB non ancora
        # migrato a 0005, o test su create_all() che non conosce le virtual table),
        # la ricerca testuale risponde 503, non un errore SQL grezzo.
        if not fts_available(session):
            raise HTTPException(
                status_code=503,
                detail="Ricerca testuale non disponibile: indice FTS5 mancante.",
            )
        fts_match = text("transactions_fts MATCH :match_expr").bindparams(match_expr=match_expr)
        conditions.append(
            Transaction.id.in_(
                select(literal_column("rowid")).select_from(text("transactions_fts")).where(fts_match)
            )
        )

    if group_by is not None:
        # Ramo a short-circuit (rettifica ADR-0029 p.6): solo subtotali, page/page_size
        # ignorati. Con offset/limit applicati un gruppo si spezzerebbe fra due pagine
        # e il subtotale mostrato sarebbe quello della sola pagina, senza alcun errore.
        if group_by == "category":
            key_col = Transaction.category_raw
        elif group_by == "month":
            key_col = func.strftime("%Y-%m", Transaction.date)
        else:
            key_col = Transaction.account

        group_stmt = (
            select(
                key_col.label("key"),
                func.count().label("count"),
                func.sum(Transaction.amount).label("total"),
            )
            .where(*conditions)
            .group_by(key_col)
        )
        groups = session.execute(group_stmt).all()
        return {"groups": [{"key": g.key, "count": g.count, "total": g.total} for g in groups]}

    stmt = select(Transaction).where(*conditions)
    total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    stmt = (
        stmt.order_by(Transaction.date.desc(), Transaction.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = session.execute(stmt).scalars().all()

    return {
        "items": [_serialize(t) for t in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


class UpdateTransactionRequest(BaseModel):
    comment: Optional[str] = None
    tag: Optional[str] = None
    category_id: Optional[int] = None


@router.put("/transactions/{transaction_id}")
def update_transaction(
    transaction_id: int, body: UpdateTransactionRequest, session: Session = Depends(get_session)
):
    transaction = session.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transazione non trovata.")

    fields = body.model_dump(exclude_unset=True)
    if fields.get("category_id") is not None:
        category = session.get(Category, fields["category_id"])
        if category is None:
            raise HTTPException(status_code=404, detail="Categoria non trovata.")

    for field, value in fields.items():
        setattr(transaction, field, value)

    session.commit()
    session.refresh(transaction)
    return _serialize(transaction)


@router.delete("/transactions/{transaction_id}")
def delete_transaction(transaction_id: int, session: Session = Depends(get_session)):
    transaction = session.get(Transaction, transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transazione non trovata.")

    session.delete(transaction)
    session.commit()
    return {"deleted_id": transaction_id}
