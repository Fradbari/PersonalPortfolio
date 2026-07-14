"""Dedup hash + category/account resolution — condiviso tra My Finance (F1) e
l'adapter master sheet (F2, un-pivot wide->long), ADR-0005/ADR-0006/ADR-0013.
"""
from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, CategoryMap, CategoryPending


def compute_hash_dedup(date: datetime, amount: float, category_raw: str, account_raw: str, type_: str) -> str:
    """sha256 su campi stabili (ADR-0005/ADR-0013). Contratto immutabile:
    NON includere mai campi editabili post-import (`comment`, `tag`)."""
    payload = f"{date:%Y-%m-%d}|{amount:.2f}|{category_raw}|{account_raw}|{type_}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def resolve_category(session: Session, source: str, source_name: str) -> int | None:
    """Risolve `source_name` -> `category_id` canonico via `category_map`.

    Se ignota: get-or-create di una riga in `category_pending` (ignorata se già presente,
    grazie alla unique constraint su (source, source_name)) e ritorna `None` — la
    transazione viene comunque importata (ADR-0006), risolta poi via `/categories/pending`.

    Nota concorrenza: FastAPI è l'unico writer sul DB (ADR-0001) e questo endpoint processa
    le righe sequenzialmente in un'unica request/transazione, quindi non serve gestione di
    race condition tra processi paralleli sulla unique constraint.
    """
    mapping = session.execute(
        select(CategoryMap).where(CategoryMap.source == source, CategoryMap.source_name == source_name)
    ).scalar_one_or_none()
    if mapping is not None:
        return mapping.category_id

    existing_pending = session.execute(
        select(CategoryPending).where(CategoryPending.source == source, CategoryPending.source_name == source_name)
    ).scalar_one_or_none()
    if existing_pending is None:
        session.add(CategoryPending(source=source, source_name=source_name))
        session.flush()

    return None


def get_or_create_account(session: Session, name: str) -> None:
    """Assicura che esista `Account(name=name)` (ADR-0006: conti importati as-is).

    `transactions.account` resta la stringa raw (non è FK verso `accounts`); questa
    tabella serve solo a tracciare i conti visti per rinomina/accorpamento in dashboard.
    """
    existing = session.execute(select(Account).where(Account.name == name)).scalar_one_or_none()
    if existing is None:
        session.add(Account(name=name))
        session.flush()
