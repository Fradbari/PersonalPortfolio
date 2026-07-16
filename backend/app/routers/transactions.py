"""`/transactions` — lista filtrata/paginata, edit campi editabili, delete (F5, ADR-0019).

Campi editabili: SOLO `comment`/`tag`/`category_id`. `date`/`amount`/`category_raw`/
`account`/`type`/`hash_dedup` restano immutabili post-import (ADR-0005/ADR-0013)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Category, Transaction

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
    category_id: Optional[int] = None,
    account: Optional[str] = None,
    type_: Optional[str] = Query(default=None, alias="type"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    stmt = select(Transaction)
    if year_month:
        stmt = stmt.where(func.strftime("%Y-%m", Transaction.date) == year_month)
    if category_id is not None:
        stmt = stmt.where(Transaction.category_id == category_id)
    if account is not None:
        stmt = stmt.where(Transaction.account == account)
    if type_ is not None:
        stmt = stmt.where(Transaction.type == type_)

    total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    stmt = stmt.order_by(Transaction.date.desc()).offset((page - 1) * page_size).limit(page_size)
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
