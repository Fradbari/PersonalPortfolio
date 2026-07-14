"""`/categories*` — categorie canoniche + coda di riconciliazione (ADR-0006/ADR-0013)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Category, CategoryMap, CategoryPending, Transaction

router = APIRouter(tags=["categories"])


class ResolvePendingRequest(BaseModel):
    category_name: str


@router.get("/categories/pending")
def list_pending(session: Session = Depends(get_session)):
    pending = session.execute(select(CategoryPending).order_by(CategoryPending.id)).scalars().all()
    return [
        {
            "id": p.id,
            "source": p.source,
            "source_name": p.source_name,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in pending
    ]


@router.get("/categories")
def list_categories(session: Session = Depends(get_session)):
    categories = session.execute(select(Category).order_by(Category.id)).scalars().all()
    return [{"id": c.id, "name": c.name} for c in categories]


@router.post("/categories/pending/{pending_id}/resolve")
def resolve_pending(pending_id: int, body: ResolvePendingRequest, session: Session = Depends(get_session)):
    pending = session.get(CategoryPending, pending_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="Categoria pending non trovata.")

    category_name = body.category_name.strip()
    if not category_name:
        raise HTTPException(status_code=422, detail="category_name non può essere vuoto.")

    category = session.execute(select(Category).where(Category.name == category_name)).scalar_one_or_none()
    if category is None:
        category = Category(name=category_name)
        session.add(category)
        session.flush()  # assegna category.id

    mapping = session.execute(
        select(CategoryMap).where(
            CategoryMap.source == pending.source, CategoryMap.source_name == pending.source_name
        )
    ).scalar_one_or_none()
    if mapping is None:
        session.add(CategoryMap(source=pending.source, source_name=pending.source_name, category_id=category.id))
    else:
        # Difensivo: non dovrebbe accadere (pending esiste solo finché non mappata),
        # ma se una mappa esiste già onoriamo quella invece di duplicare la unique constraint.
        category = session.get(Category, mapping.category_id)

    result = session.execute(
        update(Transaction)
        .where(
            Transaction.category_raw == pending.source_name,
            Transaction.source == pending.source,
            Transaction.category_id.is_(None),
        )
        .values(category_id=category.id)
    )
    backfilled_count = result.rowcount

    session.delete(pending)
    session.commit()

    return {"category_id": category.id, "backfilled_count": backfilled_count}
