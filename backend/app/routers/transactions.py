"""`/transactions` — lista filtrata/paginata, edit campi editabili, delete (F5, ADR-0019).
Filtri avanzati, ricerca full-text e raggruppamento (F12, ADR-0029).

Campi editabili: SOLO `comment`/`tag`/`category_id`. `date`/`amount`/`category_raw`/
`account`/`type`/`hash_dedup` restano immutabili post-import (ADR-0005/ADR-0013)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, literal_column, select, text
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Category, Transaction
from app.services.search import build_match_expression, fts_available

router = APIRouter(tags=["transactions"])


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
