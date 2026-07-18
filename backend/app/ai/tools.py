"""Tool registry read-only per il layer AI (F6, ADR-0023 p.4).

Quattro tool, tutti letture, tutti wrapper su query/service gia' esistenti — zero
SQL nuovo, salvo il filtro composito di `list_transactions` che riusa lo stesso
pattern di `routers/transactions.py:47-58` (where condizionali) su un set di filtri
diverso (data/categoria/conto/importo/tipo, pensato per una domanda in linguaggio
naturale, non per la UI paginata).

Guardrail non negoziabile: **nessuna funzione qui esegue una scrittura**. Il
modello non deve mai poter raggiungere `INSERT`/`UPDATE`/`DELETE` su
`transactions`/`accounts`/`category_pending` (ADR-0023 p.4). Se in futuro serve
un tool di scrittura: e' un'altra fase, con ADR proprio e approvazione umana per
ogni modifica — non aggiungerlo qui.

`TOOLS` e' il registry eseguibile: ogni funzione accetta `session` come primo
argomento posizionale e il resto come keyword-only, con nomi che combaciano
**esattamente** con le chiavi dei parametri dichiarati da `tool_declarations()`
(incluso `type`, che qui ombreggia deliberatamente il builtin `type()` — non
serve all'interno di queste funzioni — per evitare all'adapter [Task 3] un
livello di traduzione tra lo schema JSON e i kwarg Python)."""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Account, Category, Transaction
from app.services import insights as insights_service

MAX_TOOL_ROWS = 200  # allineato al page_size massimo gia' ammesso da transactions.py:43


def _serialize_transaction(t: Transaction) -> dict:
    # Stessa forma di `_serialize()` in routers/transactions.py:20-33. Duplicata
    # (non importata) per non far dipendere il layer AI da un simbolo privato di
    # un router — comment/tag inclusi di proposito (ADR-0023 p.9).
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


def list_transactions(
    session: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    category: str | None = None,
    account: str | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    type: str | None = None,  # noqa: A002 - nome allineato allo schema tool, vedi docstring modulo
) -> dict:
    """Transazioni grezze filtrabili. Risultato mai piu' di `MAX_TOOL_ROWS` righe:
    se il totale supera il cap, `truncated=True` e `note` spiega al modello che sta
    vedendo un sottoinsieme (mai un troncamento silenzioso, ADR-0023 p.7)."""
    stmt = select(Transaction)
    if date_from is not None:
        stmt = stmt.where(Transaction.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Transaction.date <= date_to)
    if category is not None:
        stmt = stmt.where(Transaction.category_raw == category)
    if account is not None:
        stmt = stmt.where(Transaction.account == account)
    if amount_min is not None:
        stmt = stmt.where(Transaction.amount >= amount_min)
    if amount_max is not None:
        stmt = stmt.where(Transaction.amount <= amount_max)
    if type is not None:
        stmt = stmt.where(Transaction.type == type)

    total_matching = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    stmt = stmt.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(MAX_TOOL_ROWS)
    rows = session.execute(stmt).scalars().all()
    truncated = total_matching > MAX_TOOL_ROWS

    result: dict = {
        "rows": [_serialize_transaction(t) for t in rows],
        "returned": len(rows),
        "total_matching": total_matching,
        "truncated": truncated,
    }
    if truncated:
        result["note"] = (
            f"risultato troncato a {MAX_TOOL_ROWS} righe su {total_matching}: restringi i filtri"
        )
    else:
        result["note"] = None
    return result


def get_insights(
    session: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    account: str | None = None,
    type: str | None = None,  # noqa: A002 - vedi docstring modulo
) -> dict:
    """Aggregazioni (trend mensile, breakdown categoria, saldo cumulato, saldo per
    conto) via `app.services.insights` — stessi filtri e stessa logica di
    `GET /insights` (routers/insights.py). Preferire questo tool a `list_transactions`
    quando la domanda e' su totali/andamenti: l'aggregazione la fa il DB, non il
    modello (i modelli sbagliano l'aritmetica)."""
    trend = insights_service.monthly_trend(
        session, date_from=date_from, date_to=date_to, account=account, type_=type
    )
    return {
        "monthly_trend": trend,
        "category_breakdown": insights_service.category_breakdown(
            session,
            date_from=date_from,
            date_to=date_to,
            account=account,
            type_=type if type is not None else "expense",
        ),
        "cumulative_balance": insights_service.cumulative_balance(trend),
        "balance_by_account": insights_service.balance_by_account(
            session, date_from=date_from, date_to=date_to, type_=type
        ),
    }


def get_accounts(session: Session) -> list[dict]:
    """Lista conti (id, nome as-is dalla fonte, display_name). Wrapper diretto su
    `routers/accounts.py:17`, nessun filtro."""
    accounts = session.execute(select(Account).order_by(Account.id)).scalars().all()
    return [{"id": a.id, "name": a.name, "display_name": a.display_name} for a in accounts]


def get_categories(session: Session) -> list[dict]:
    """Lista categorie canoniche (id, nome). Wrapper diretto su
    `routers/categories.py:33`, nessun filtro."""
    categories = session.execute(select(Category).order_by(Category.id)).scalars().all()
    return [{"id": c.id, "name": c.name} for c in categories]


TOOLS: dict[str, Callable[..., dict | list[dict]]] = {
    "list_transactions": list_transactions,
    "get_insights": get_insights,
    "get_accounts": get_accounts,
    "get_categories": get_categories,
}


def tool_declarations() -> list[dict]:
    """Schema JSON delle funzioni, in forma neutra rispetto al provider (nessun
    formato Gemini/OpenAI qui: la traduzione avviene nell'adapter, Task 3). Una
    dichiarazione per ogni tool eseguibile in `TOOLS`, nessun orfano in nessuna
    delle due direzioni (verificato in test)."""
    return [
        {
            "name": "list_transactions",
            "description": (
                "Restituisce le transazioni grezze filtrabili per data, categoria, conto, "
                "importo e tipo (expense|income), incluse le note libere comment/tag. "
                "Risultato troncato a un numero massimo di righe: controlla sempre il campo "
                "'truncated' e, se True, restringi i filtri invece di rispondere su dati parziali."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {
                        "type": "string",
                        "format": "date",
                        "description": "Data minima (inclusiva), formato ISO YYYY-MM-DD.",
                    },
                    "date_to": {
                        "type": "string",
                        "format": "date",
                        "description": "Data massima (inclusiva), formato ISO YYYY-MM-DD.",
                    },
                    "category": {
                        "type": "string",
                        "description": "Nome categoria as-is dalla fonte (vedi get_categories).",
                    },
                    "account": {
                        "type": "string",
                        "description": "Nome conto as-is dalla fonte (vedi get_accounts).",
                    },
                    "amount_min": {"type": "number", "description": "Importo minimo (inclusivo)."},
                    "amount_max": {"type": "number", "description": "Importo massimo (inclusivo)."},
                    "type": {
                        "type": "string",
                        "enum": ["expense", "income"],
                        "description": "Tipo transazione.",
                    },
                },
                "required": [],
            },
        },
        {
            "name": "get_insights",
            "description": (
                "Aggregazioni gia' calcolate dal database: trend mensile entrate/uscite, "
                "breakdown per categoria, saldo cumulato, saldo per conto. Da preferire a "
                "list_transactions quando la domanda riguarda totali o andamenti: l'aritmetica "
                "la fa il database, non il modello."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {
                        "type": "string",
                        "format": "date",
                        "description": "Data minima (inclusiva), formato ISO YYYY-MM-DD.",
                    },
                    "date_to": {
                        "type": "string",
                        "format": "date",
                        "description": "Data massima (inclusiva), formato ISO YYYY-MM-DD.",
                    },
                    "account": {
                        "type": "string",
                        "description": "Nome conto as-is dalla fonte (vedi get_accounts).",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["expense", "income"],
                        "description": "Tipo transazione.",
                    },
                },
                "required": [],
            },
        },
        {
            "name": "get_accounts",
            "description": "Lista dei conti disponibili (id, nome, display_name), nessun filtro.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "get_categories",
            "description": "Lista delle categorie canoniche disponibili (id, nome), nessun filtro.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    ]
