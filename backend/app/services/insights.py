"""Aggregazioni insights (F5, ADR-0019 → F6, ADR-0023 → F13, ADR-0030): trend
mensile, breakdown per categoria, saldo cumulato, saldo per conto, più i sei
pannelli dashboard di F13 in fondo al modulo. Corpo delle prime 4 funzioni
invariato rispetto alle versioni private che stavano in
`app/routers/insights.py` — qui diventano pubbliche, riusabili sia dal router
`GET /insights` sia dal tool registry AI (read-only, ADR-0023), e acquisiscono
filtri opzionali applicati come `WHERE` addizionali solo quando l'argomento non
è `None`. Con tutti i filtri `None` la query generata è semanticamente identica
a quella odierna senza filtri.

Le funzioni F13 (da `resolve_window_start` in poi) alimentano **solo**
`GET /insights/panels` (routers/insights.py): estensione dello stesso service
layer, mai un secondo (ADR-0030 p.2) — `GET /insights` e `ai/tools.py::get_insights`
non le richiamano e restano immutati byte per byte."""
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


# --- F13: pannelli dashboard (`GET /insights/panels`, ADR-0030) ----------------
#
# Contratto congelato in spec §7 (Blocco B, 2026-07-25), CP1b lo verifica su una
# risposta reale prima che il frontend (T14) lo consumi. Tutto qui sotto è nuovo
# per questo endpoint: nessuna delle 4 funzioni sopra viene toccata, nessuna
# funzione qui sotto è richiamata da `GET /insights` o da `ai/tools.py`.


def resolve_window_start(*, months: int, now: datetime) -> datetime:
    """Primo giorno del mese calendario `(months - 1)` mesi prima del mese di
    `now` (incluso): con `months=12` e `now` in luglio, il 1° agosto dell'anno
    precedente — 12 mesi calendario che finiscono a luglio incluso. Pura
    funzione di calendario, nessuna `datetime.utcnow()` qui dentro: il
    chiamante passa `now` esplicitamente, così resta testabile senza mock."""
    total_months = now.year * 12 + (now.month - 1) - (months - 1)
    year, zero_based_month = divmod(total_months, 12)
    return datetime(year, zero_based_month + 1, 1)


def previous_year_month(year_month: str) -> str:
    """Mese calendario immediatamente precedente a `year_month` (`"YYYY-MM"`),
    gestendo lo scavalco d'anno: il precedente di gennaio è dicembre dell'anno
    prima."""
    year, month = (int(part) for part in year_month.split("-"))
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def savings_rate_fraction(income: float, expense: float) -> float:
    """`(income - expense) / income`, arrotondato a 4 decimali; **`0.0` quando
    `income == 0`**, mai `null`/`NaN` — che in una linea Recharts diventerebbe un
    buco silenzioso, non un errore visibile (spec F13 §7). Unica implementazione
    condivisa fra `kpi_summary` e `savings_trend`: stessa formula, stesso
    arrotondamento, nessuna divergenza fra i due punti che la consumano."""
    if income == 0:
        return 0.0
    return round((income - expense) / income, 4)


def kpi_summary(trend: list[dict]) -> dict:
    """Riga di 4 KPI (entrate, uscite, netto, tasso di risparmio — ADR-0030 p.5)
    sulla stessa finestra risolta di tutti gli altri pannelli: somma il `trend`
    già filtrato/finestrato a monte (tipicamente da `monthly_trend`). Pura
    in-memory, come `cumulative_balance`: nessuna query propria. `trend` vuoto
    → tutto zero, mai un `KeyError`."""
    income = round(sum(m["income"] for m in trend), 2)
    expense = round(sum(m["expense"] for m in trend), 2)
    return {
        "income": income,
        "expense": expense,
        "net": round(income - expense, 2),
        "savings_rate": savings_rate_fraction(income, expense),
    }


def cash_flow(trend: list[dict]) -> list[dict]:
    """Cash flow mensile per il pannello barre entrate/uscite + linea netto
    (ADR-0030 p.5): stesso `trend` di `monthly_trend`/`cumulative_balance`, con
    `net` aggiunto punto per punto. Pura in-memory: nessuna query propria, nessun
    mese di riempimento — eredita il non-padding di `monthly_trend` (`GROUP BY`
    non emette mesi vuoti)."""
    return [
        {
            "year_month": m["year_month"],
            "income": m["income"],
            "expense": m["expense"],
            "net": round(m["income"] - m["expense"], 2),
        }
        for m in trend
    ]


def savings_trend(trend: list[dict]) -> list[dict]:
    """Percentuale di risparmio mese su mese (ADR-0030 p.5): stessa formula e
    stesso arrotondamento di `kpi_summary` (via `savings_rate_fraction`, mai divergenti),
    applicata punto per punto sullo stesso `trend` di `cash_flow`/
    `cumulative_balance`."""
    return [
        {"year_month": m["year_month"], "savings_rate": savings_rate_fraction(m["income"], m["expense"])}
        for m in trend
    ]


def category_donut(
    session: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    account: str | None = None,
) -> list[dict]:
    """Spesa per categoria per il pannello donut (ADR-0030 p.5/p.6): sempre e
    solo uscite, riusa `category_breakdown(..., type_="expense")` — stesso
    significato di "categoria" già stabilito dalla dashboard esistente
    (`frontend/src/pages/Dashboard.tsx`, "Spesa per categoria": non esiste una
    vista sulle entrate per categoria altrove nell'app da rispecchiare).
    Aggregazione lato backend: **al massimo 7 elementi**, le prime 6 per `total`
    discendente (`category_breakdown` ordina già così) più un settimo
    `"Altro"` con la somma della coda. Sotto le 7 categorie nessun `"Altro"`
    viene aggiunto: non esiste una coda da sommare, e un `"Altro": 0.0`
    fittizio sarebbe una categoria inventata."""
    breakdown = category_breakdown(
        session, date_from=date_from, date_to=date_to, account=account, type_="expense"
    )
    if len(breakdown) <= 6:
        return breakdown
    tail_total = round(sum(row["total"] for row in breakdown[6:]), 2)
    return breakdown[:6] + [{"category_raw": "Altro", "total": tail_total}]


def month_over_month(
    session: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    account: str | None = None,
) -> dict:
    """Confronto per categoria fra l'ultimo mese calendario con almeno una spesa
    e il mese immediatamente precedente (ADR-0030 p.5). Sempre e solo uscite,
    stesso `category_raw` di `category_donut`/`category_breakdown` (non
    `Category.name` mappata).

    **Ancorato all'ultimo mese con dati reali, non a "oggi"**: anche filtrato
    per `account`/`date_from`/`date_to` così come passati (nessun default da
    `months` qui — a differenza di `kpi`/`cumulative_balance`/`cash_flow`/
    `category_donut`/`savings_trend`, questo pannello non riceve la finestra
    risolta da `panels_summary`). Ancorare a "oggi" renderebbe `current`
    frequentemente vuoto per chi non ha ancora registrato spese nel mese in
    corso, vanificando il confronto; ancorare invece all'ultimo mese con dati
    rende "DB vuoto → entrambi i mesi `null`" un caso solo, non un'eccezione
    innestata sopra una regola diversa.

    Le chiavi di `current`/`previous`/`delta_pct` sono l'**unione** delle
    categorie presenti in almeno uno dei due mesi: una categoria assente da un
    mese vale `0.0` in quel mese (mai una chiave mancante). `delta_pct[cat]` è
    `None` quando `previous[cat] == 0` (divisione impossibile, non zero e non
    infinito) — incluso quando la categoria è semplicemente assente dal mese
    precedente."""
    stmt = select(
        func.strftime("%Y-%m", Transaction.date).label("ym"),
        Transaction.category_raw,
        func.sum(Transaction.amount),
    ).where(Transaction.type == "expense")
    if date_from is not None:
        stmt = stmt.where(Transaction.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Transaction.date <= date_to)
    if account is not None:
        stmt = stmt.where(Transaction.account == account)
    stmt = stmt.group_by("ym", Transaction.category_raw)

    rows = session.execute(stmt).all()
    if not rows:
        return {
            "current_month": None,
            "previous_month": None,
            "current": {},
            "previous": {},
            "delta_pct": {},
        }

    current_month = max(ym for ym, _cat, _total in rows)
    previous_month = previous_year_month(current_month)

    current_raw = {cat: round(total, 2) for ym, cat, total in rows if ym == current_month}
    previous_raw = {cat: round(total, 2) for ym, cat, total in rows if ym == previous_month}

    categories = sorted(set(current_raw) | set(previous_raw))
    current = {cat: current_raw.get(cat, 0.0) for cat in categories}
    previous = {cat: previous_raw.get(cat, 0.0) for cat in categories}
    delta_pct: dict[str, float | None] = {}
    for cat in categories:
        prev_v = previous[cat]
        delta_pct[cat] = None if prev_v == 0 else round((current[cat] - prev_v) / prev_v * 100, 1)

    return {
        "current_month": current_month,
        "previous_month": previous_month,
        "current": current,
        "previous": previous,
        "delta_pct": delta_pct,
    }


def panels_summary(
    session: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    account: str | None = None,
    months: int = 12,
) -> dict:
    """Aggregato per `GET /insights/panels` (F13, ADR-0030): i sei pannelli
    complementari a Metabase, che resta invariata (ADR-0004/ADR-0019 non
    superati). Endpoint e funzione separati da `GET /insights`/`monthly_trend` —
    stesso modulo, nessun secondo service layer (ADR-0030 p.2).

    `date_from`/`date_to`/`account` hanno stessi nomi e semantica di
    `GET /insights` (filtro inclusivo, applicato solo se non `None`). `months`
    **sostituisce `date_from` solo quando il chiamante non lo passa
    esplicitamente**: finestra scorrevole di `months` mesi calendario che
    termina nel mese corrente (`resolve_window_start`). Se `date_from` è dato,
    `months` non ha alcun effetto — stessa relazione "default-solo-se-assente"
    già in uso fra `date_from`/`date_to` in `GET /insights`. `date_to` non
    riceve mai un default da `months`: resta illimitato come in `GET /insights`.
    Questa finestra risolta alimenta **uniformemente** `kpi`, `cumulative_balance`,
    `cash_flow`, `category_donut`, `savings_trend` (un'unica chiamata a
    `monthly_trend` qui sotto, riusata da tre pannelli).

    `month_over_month` è l'eccezione deliberata: riceve `date_from`/`date_to`
    così come passati dal chiamante, **senza** il default da `months` (vedi
    `month_over_month`) — resta ancorato all'ultimo mese con dati reali anche
    quando quel mese cade fuori dalla finestra scorrevole mostrata dagli altri
    cinque pannelli."""
    resolved_date_from = (
        date_from
        if date_from is not None
        else resolve_window_start(months=months, now=datetime.utcnow())
    )

    trend = monthly_trend(session, date_from=resolved_date_from, date_to=date_to, account=account)

    return {
        "kpi": kpi_summary(trend),
        "cumulative_balance": cumulative_balance(trend),
        "cash_flow": cash_flow(trend),
        "category_donut": category_donut(
            session, date_from=resolved_date_from, date_to=date_to, account=account
        ),
        "savings_trend": savings_trend(trend),
        "month_over_month": month_over_month(
            session, date_from=date_from, date_to=date_to, account=account
        ),
    }
