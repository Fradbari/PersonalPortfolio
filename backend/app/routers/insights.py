"""`/insights` — aggregazioni per la dashboard React (F5, ADR-0019): trend mensile,
breakdown per categoria, saldo cumulato, saldo per conto. Stessa logica delle 4 card
SQL native di Metabase (F3), riscritta via SQLAlchemy. Legge il DB **live**: FastAPI
è già l'unico writer nello stesso processo, WAL garantisce reader concorrenti sicuri
senza bisogno della replica read-only (quella serve solo a isolare Metabase in un
container separato, ADR-0004/ADR-0017).

Le aggregazioni vere e proprie vivono in `app/services/insights.py` (F6, ADR-0023):
qui il router resta un wrapper sottile che espone gli stessi filtri opzionali come
query param HTTP, riusando la logica già scritta per il tool registry AI."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.services import insights as insights_service

router = APIRouter(tags=["insights"])


@router.get("/insights")
def get_insights(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    account: str | None = None,
    type_: str | None = None,
    session: Session = Depends(get_session),
):
    trend = insights_service.monthly_trend(
        session, date_from=date_from, date_to=date_to, account=account, type_=type_
    )
    return {
        "monthly_trend": trend,
        "category_breakdown": insights_service.category_breakdown(
            session,
            date_from=date_from,
            date_to=date_to,
            account=account,
            type_=type_ if type_ is not None else "expense",
        ),
        "cumulative_balance": insights_service.cumulative_balance(trend),
        "balance_by_account": insights_service.balance_by_account(
            session, date_from=date_from, date_to=date_to, type_=type_
        ),
    }


@router.get("/insights/panels")
def get_insights_panels(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    account: str | None = None,
    months: int = Query(default=12, ge=1, le=600),
    session: Session = Depends(get_session),
):
    """Sei pannelli dashboard complementari a Metabase (F13, ADR-0030): saldo
    cumulato, cash flow mensile, spese per categoria (donut), trend risparmio,
    confronto mese su mese, KPI. Endpoint **separato** da `GET /insights`
    sopra — stesso file per coesione dei router, contratto e parametri
    indipendenti (niente `type_`: i pannelli mostrano entrate e uscite insieme
    per costruzione, non è una decisione di questo endpoint). Wrapper sottile:
    tutta l'aggregazione vive in `insights_service.panels_summary`."""
    return insights_service.panels_summary(
        session, date_from=date_from, date_to=date_to, account=account, months=months
    )
