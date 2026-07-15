"""`/insights` — aggregazioni per la dashboard React (F5, ADR-0019): trend mensile,
breakdown per categoria, saldo cumulato, saldo per conto. Stessa logica delle 4 card
SQL native di Metabase (F3), riscritta via SQLAlchemy. Legge il DB **live**: FastAPI
è già l'unico writer nello stesso processo, WAL garantisce reader concorrenti sicuri
senza bisogno della replica read-only (quella serve solo a isolare Metabase in un
container separato, ADR-0004/ADR-0017)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Transaction

router = APIRouter(tags=["insights"])


def _monthly_trend(session: Session) -> list[dict]:
    rows = session.execute(
        select(
            func.strftime("%Y-%m", Transaction.date).label("ym"),
            Transaction.type,
            func.sum(Transaction.amount),
        )
        .group_by("ym", Transaction.type)
        .order_by("ym")
    ).all()

    by_month: dict[str, dict[str, float]] = {}
    for ym, type_, total in rows:
        by_month.setdefault(ym, {"income": 0.0, "expense": 0.0})[type_] = round(total, 2)

    return [
        {"year_month": ym, "income": v["income"], "expense": v["expense"]}
        for ym, v in sorted(by_month.items())
    ]


def _category_breakdown(session: Session) -> list[dict]:
    rows = session.execute(
        select(Transaction.category_raw, func.sum(Transaction.amount))
        .where(Transaction.type == "expense")
        .group_by(Transaction.category_raw)
        .order_by(func.sum(Transaction.amount).desc())
    ).all()
    return [{"category_raw": cat, "total": round(total, 2)} for cat, total in rows]


def _cumulative_balance(trend: list[dict]) -> list[dict]:
    cumulative = 0.0
    result = []
    for m in trend:
        balance = round(m["income"] - m["expense"], 2)
        cumulative = round(cumulative + balance, 2)
        result.append({"year_month": m["year_month"], "balance": balance, "cumulative_balance": cumulative})
    return result


def _balance_by_account(session: Session) -> list[dict]:
    rows = session.execute(
        select(Transaction.account, Transaction.type, func.sum(Transaction.amount))
        .group_by(Transaction.account, Transaction.type)
    ).all()

    by_account: dict[str, dict[str, float]] = {}
    for account, type_, total in rows:
        by_account.setdefault(account, {"income": 0.0, "expense": 0.0})[type_] = round(total, 2)

    return [
        {"account": acc, "balance": round(v["income"] - v["expense"], 2)}
        for acc, v in sorted(by_account.items())
    ]


@router.get("/insights")
def get_insights(session: Session = Depends(get_session)):
    trend = _monthly_trend(session)
    return {
        "monthly_trend": trend,
        "category_breakdown": _category_breakdown(session),
        "cumulative_balance": _cumulative_balance(trend),
        "balance_by_account": _balance_by_account(session),
    }
