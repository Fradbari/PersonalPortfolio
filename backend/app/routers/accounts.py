"""`/accounts` — lista conti + rename `display_name` (N-F6, F5, ADR-0019).

`Account.name` = valore raw as-is dalla fonte (ADR-0006), mai editabile qui."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Account

router = APIRouter(tags=["accounts"])


@router.get("/accounts")
def list_accounts(session: Session = Depends(get_session)):
    accounts = session.execute(select(Account).order_by(Account.id)).scalars().all()
    return [{"id": a.id, "name": a.name, "display_name": a.display_name} for a in accounts]


class UpdateAccountRequest(BaseModel):
    display_name: str


@router.patch("/accounts/{account_id}")
def update_account(account_id: int, body: UpdateAccountRequest, session: Session = Depends(get_session)):
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Conto non trovato.")

    display_name = body.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=422, detail="display_name non può essere vuoto.")

    account.display_name = display_name
    session.commit()
    session.refresh(account)
    return {"id": account.id, "name": account.name, "display_name": account.display_name}
