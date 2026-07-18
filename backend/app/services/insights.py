"""Aggregazioni insights (F5, ADR-0019 → F6, ADR-0023): trend mensile, breakdown per
categoria, saldo cumulato, saldo per conto. Corpo delle funzioni invariato rispetto
alle versioni private che stavano in `app/routers/insights.py` — qui diventano
pubbliche, riusabili sia dal router `GET /insights` sia dal tool registry AI
(read-only, ADR-0023), e acquisiscono filtri opzionali applicati come `WHERE`
addizionali solo quando l'argomento non è `None`. Con tutti i filtri `None` la
query generata è semanticamente identica a quella odierna senza filtri."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Transaction


def monthly_trend(
    session: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    account: str | None = None,
    type_: str | None = None,
) -> list[dict]:
    """Trend mensile income/expense. `date_from`/`date_to` sono inclusivi agli
    estremi (`>=`/`<=`). Nessun filtro passato = comportamento odierno (tutte le
    transazioni)."""
    stmt = select(
        func.strftime("%Y-%m", Transaction.date).label("ym"),
        Transaction.type,
        func.sum(Transaction.amount),
    )
    if date_from is not None:
        stmt = stmt.where(Transaction.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Transaction.date <= date_to)
    if account is not None:
        stmt = stmt.where(Transaction.account == account)
    if type_ is not None:
        stmt = stmt.where(Transaction.type == type_)
    stmt = stmt.group_by("ym", Transaction.type).order_by("ym")

    rows = session.execute(stmt).all()

    by_month: dict[str, dict[str, float]] = {}
    for ym, t, total in rows:
        by_month.setdefault(ym, {"income": 0.0, "expense": 0.0})[t] = round(total, 2)

    return [
        {"year_month": ym, "income": v["income"], "expense": v["expense"]}
        for ym, v in sorted(by_month.items())
    ]


def category_breakdown(
    session: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    account: str | None = None,
    type_: str | None = "expense",
) -> list[dict]:
    """Somma per categoria raw. `type_` è l'unico filtro con default non-`None`:
    di default vale `"expense"` per preservare il comportamento odierno (la query
    originale hardcodava `where(Transaction.type == "expense")`); passare
    `type_=None` esplicitamente significa "entrambi i tipi", non "nessun filtro
    accidentale". `date_from`/`date_to` inclusivi agli estremi."""
    stmt = select(Transaction.category_raw, func.sum(Transaction.amount))
    if date_from is not None:
        stmt = stmt.where(Transaction.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Transaction.date <= date_to)
    if account is not None:
        stmt = stmt.where(Transaction.account == account)
    if type_ is not None:
        stmt = stmt.where(Transaction.type == type_)
    stmt = stmt.group_by(Transaction.category_raw).order_by(func.sum(Transaction.amount).desc())

    rows = session.execute(stmt).all()
    return [{"category_raw": cat, "total": round(total, 2)} for cat, total in rows]


def cumulative_balance(trend: list[dict]) -> list[dict]:
    """Saldo cumulato mese su mese a partire dal trend. Invariata, puro in-memory:
    nessun filtro qui, si applicano a monte su `monthly_trend`."""
    cumulative = 0.0
    result = []
    for m in trend:
        balance = round(m["income"] - m["expense"], 2)
        cumulative = round(cumulative + balance, 2)
        result.append({"year_month": m["year_month"], "balance": balance, "cumulative_balance": cumulative})
    return result


def balance_by_account(
    session: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    type_: str | None = None,
) -> list[dict]:
    """Saldo netto (income - expense) per conto. `date_from`/`date_to` inclusivi
    agli estremi. Nessun filtro `account`: l'aggregazione è già per conto."""
    stmt = select(Transaction.account, Transaction.type, func.sum(Transaction.amount))
    if date_from is not None:
        stmt = stmt.where(Transaction.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Transaction.date <= date_to)
    if type_ is not None:
        stmt = stmt.where(Transaction.type == type_)
    stmt = stmt.group_by(Transaction.account, Transaction.type)

    rows = session.execute(stmt).all()

    by_account: dict[str, dict[str, float]] = {}
    for account_name, t, total in rows:
        by_account.setdefault(account_name, {"income": 0.0, "expense": 0.0})[t] = round(total, 2)

    return [
        {"account": acc, "balance": round(v["income"] - v["expense"], 2)}
        for acc, v in sorted(by_account.items())
    ]
