"""`POST /import/my-finance` — upload export My Finance `.xlsx` (Fase 1).
`POST /import/historical/dry-run` + `POST /import/historical/commit` — upload master
sheet storico `.xlsx` (Fase 2, ADR-0015).

Flusso comune: parse -> dedup hash batch (ADR-0005) -> category mapper + reconciliation
queue (ADR-0006/ADR-0013) -> conti as-is -> ImportBatch audit -> commit -> replica
read-only atomica per Metabase (ADR-0004, best-effort).

Storico: il dry-run gira su un **DB temporaneo effimero** (SQLite in-memory, schema creato
via `Base.metadata.create_all`, nessuna revision Alembic) — mai tocca `data/portfolio.db`
reale; scartato a fine richiesta. Il commit usa lo stesso DB live di F1 (ADR-0015 punto 6).
"""
from __future__ import annotations

import io
import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base, get_session, refresh_read_only_replica
from app.ingestion.master_sheet_parser import parse_master_sheet_xlsx
from app.ingestion.my_finance_parser import parse_my_finance_xlsx
from app.ingestion.reconciliation import compute_hash_dedup, get_or_create_account, resolve_category
from app.models import CategoryPending, ImportBatch, Transaction

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/import", tags=["import"])

SOURCE = "my_finance"
HISTORICAL_SOURCE = "master_sheet"


@router.post("/my-finance")
def import_my_finance(file: UploadFile, session: Session = Depends(get_session)):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Atteso un file .xlsx (export My Finance).")

    content = file.file.read()
    try:
        rows, skipped_invalid_rows = parse_my_finance_xlsx(io.BytesIO(content))
    except Exception as exc:  # file non è un export My Finance valido (sheet/colonne mancanti, ecc.)
        raise HTTPException(status_code=400, detail=f"Impossibile leggere il file: {exc}") from exc

    hashes = [
        compute_hash_dedup(r["date"], r["amount"], r["category_raw"], r["account_raw"], r["type"])
        for r in rows
    ]

    # Dedup: una sola query batch, non per-riga (ADR-0005).
    existing_hashes: set[str] = set()
    if hashes:
        existing_hashes = set(
            session.execute(select(Transaction.hash_dedup).where(Transaction.hash_dedup.in_(hashes))).scalars()
        )

    # Categorie già in coda pending PRIMA di questo batch: usate per distinguere le
    # pending "nuove" (create in questo batch) da quelle già note da import precedenti.
    pending_before: set[str] = set(
        session.execute(select(CategoryPending.source_name).where(CategoryPending.source == SOURCE)).scalars()
    )

    batch = ImportBatch(source=SOURCE, filename=file.filename, row_count=0)
    session.add(batch)
    session.flush()  # assegna batch.id

    imported = 0
    skipped_duplicates = 0
    pending_categories: list[str] = []
    category_cache: dict[str, int | None] = {}
    known_accounts: set[str] = set()

    for row, row_hash in zip(rows, hashes):
        if row_hash in existing_hashes:
            skipped_duplicates += 1
            continue

        category_raw = row["category_raw"]
        if category_raw in category_cache:
            category_id = category_cache[category_raw]
        else:
            category_id = resolve_category(session, SOURCE, category_raw)
            category_cache[category_raw] = category_id
            if category_id is None and category_raw not in pending_before:
                pending_categories.append(category_raw)
                pending_before.add(category_raw)  # non ricontare nello stesso batch

        account_raw = row["account_raw"]
        if account_raw not in known_accounts:
            get_or_create_account(session, account_raw)
            known_accounts.add(account_raw)

        session.add(
            Transaction(
                date=row["date"],
                amount=row["amount"],
                currency=row["currency"],
                type=row["type"],
                category_id=category_id,
                category_raw=category_raw,
                account=account_raw,
                comment=row["comment"],
                tag=row["tag"],
                source=SOURCE,
                import_batch_id=batch.id,
                hash_dedup=row_hash,
            )
        )
        # Evita che due righe con lo stesso hash nello stesso file (stessi campi stabili,
        # trade-off accettato in ADR-0005) tentino un doppio insert e violino l'unique
        # constraint: la seconda viene trattata come duplicato.
        existing_hashes.add(row_hash)
        imported += 1

    batch.row_count = imported
    session.commit()

    try:
        refresh_read_only_replica()
    except (OSError, sqlite3.Error) as exc:
        logger.warning("Replica read-only non aggiornata (ADR-0004, non bloccante): %s", exc)

    return {
        "import_batch_id": batch.id,
        "imported": imported,
        "skipped_duplicates": skipped_duplicates,
        "skipped_invalid_rows": skipped_invalid_rows,
        "pending_categories": pending_categories,
    }


def _ingest_master_sheet_rows(session: Session, rows: list[dict], batch: ImportBatch | None) -> dict:
    """Pipeline dedup hash (ADR-0005) + category/account reconciliation (ADR-0006/ADR-0013)
    condivisa da dry-run (DB effimero) e commit (DB live) dello storico master sheet.

    Aggiunge le `Transaction` a `session` (per il dry-run `session` è comunque un DB
    temporaneo scartato a fine richiesta, ADR-0015 punto 6). Ritorna statistiche +
    le righe (dict originali, non gli oggetti ORM) effettivamente importate, usate per
    l'aggregazione mensile della quadratura.
    """
    hashes = [
        compute_hash_dedup(r["date"], r["amount"], r["category_raw"], r["account_raw"], r["type"])
        for r in rows
    ]

    # Dedup: una sola query batch, non per-riga (ADR-0005).
    existing_hashes: set[str] = set()
    if hashes:
        existing_hashes = set(
            session.execute(select(Transaction.hash_dedup).where(Transaction.hash_dedup.in_(hashes))).scalars()
        )

    pending_before: set[str] = set(
        session.execute(
            select(CategoryPending.source_name).where(CategoryPending.source == HISTORICAL_SOURCE)
        ).scalars()
    )

    imported = 0
    skipped_duplicates = 0
    pending_categories: list[str] = []
    category_cache: dict[str, int | None] = {}
    known_accounts: set[str] = set()
    imported_rows: list[dict] = []  # per la quadratura mensile (solo righe REALMENTE importate)

    for row, row_hash in zip(rows, hashes):
        if row_hash in existing_hashes:
            skipped_duplicates += 1
            continue

        category_raw = row["category_raw"]
        if category_raw in category_cache:
            category_id = category_cache[category_raw]
        else:
            category_id = resolve_category(session, HISTORICAL_SOURCE, category_raw)
            category_cache[category_raw] = category_id
            if category_id is None and category_raw not in pending_before:
                pending_categories.append(category_raw)
                pending_before.add(category_raw)  # non ricontare nello stesso batch

        account_raw = row["account_raw"]
        if account_raw not in known_accounts:
            get_or_create_account(session, account_raw)
            known_accounts.add(account_raw)

        session.add(
            Transaction(
                date=row["date"],
                amount=row["amount"],
                currency=row["currency"],
                type=row["type"],
                category_id=category_id,
                category_raw=category_raw,
                account=account_raw,
                comment=row["comment"],
                source=HISTORICAL_SOURCE,
                import_batch_id=batch.id if batch is not None else None,
                hash_dedup=row_hash,
            )
        )
        # Evita doppio insert nello stesso file per righe con hash identico (ADR-0005).
        existing_hashes.add(row_hash)
        imported += 1
        imported_rows.append(row)

    if batch is not None:
        batch.row_count = imported

    return {
        "imported": imported,
        "skipped_duplicates": skipped_duplicates,
        "pending_categories": pending_categories,
        "imported_rows": imported_rows,
    }


def _monthly_quadrature(imported_rows: list[dict], monthly_reference: list[dict]) -> list[dict]:
    """Confronta la somma delle spese REALMENTE importate (post-dedup) per mese con la
    colonna `Spese` catturata da ogni riga `Totale %` del foglio (ADR-0015 punto 6)."""
    sums: dict[tuple[int | None, int | None], float] = {}
    for row in imported_rows:
        if row["type"] != "expense":
            continue
        key = (row["date"].year, row["date"].month)
        sums[key] = sums.get(key, 0.0) + row["amount"]

    quadrature: list[dict] = []
    for ref in monthly_reference:
        year, month = ref["year"], ref["month"]
        imported_sum = sums.get((year, month), 0.0)
        sheet_spese = ref["spese_sheet"]
        diff = round(imported_sum - sheet_spese, 2) if sheet_spese is not None else None
        quadrature.append(
            {
                "year": year,
                "month": month,
                "imported_expense_sum": round(imported_sum, 2),
                "sheet_spese": sheet_spese,
                "diff": diff,
            }
        )
    return quadrature


@router.post("/historical/dry-run")
def import_historical_dry_run(file: UploadFile):
    """Dry-run import storico master sheet (R1, ADR-0015 punto 6): parse + pipeline
    dedup/reconciliation contro un **DB temporaneo effimero** (mai `data/portfolio.db`
    reale). Report di validazione manuale prima del commit su DB live."""
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Atteso un file .xlsx (master sheet storico).")

    content = file.file.read()
    try:
        parsed = parse_master_sheet_xlsx(io.BytesIO(content))
    except Exception as exc:  # file/tab non nel formato master sheet atteso
        raise HTTPException(status_code=400, detail=f"Impossibile leggere il file: {exc}") from exc

    temp_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(temp_engine)
    TempSession = sessionmaker(bind=temp_engine, autoflush=False, expire_on_commit=False, future=True)

    try:
        with TempSession() as temp_session:
            stats = _ingest_master_sheet_rows(temp_session, parsed["rows"], batch=None)
            temp_session.commit()
    finally:
        temp_engine.dispose()  # scarta la connessione/engine effimero a fine richiesta

    return {
        "would_import": stats["imported"],
        "skipped_duplicates": stats["skipped_duplicates"],
        "skipped_rows": parsed["skipped"],
        "pending_categories": stats["pending_categories"],
        "monthly_quadrature": _monthly_quadrature(stats["imported_rows"], parsed["monthly_reference"]),
    }


@router.post("/historical/commit")
def import_historical_commit(file: UploadFile, session: Session = Depends(get_session)):
    """Import definitivo storico master sheet su DB live — da eseguire solo dopo
    validazione manuale del report di `/import/historical/dry-run` (processo umano,
    nessun flag di conferma nel codice: il dedup hash protegge da doppio import, ADR-0015
    punto 6)."""
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Atteso un file .xlsx (master sheet storico).")

    content = file.file.read()
    try:
        parsed = parse_master_sheet_xlsx(io.BytesIO(content))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Impossibile leggere il file: {exc}") from exc

    batch = ImportBatch(source=HISTORICAL_SOURCE, filename=file.filename, row_count=0)
    session.add(batch)
    session.flush()  # assegna batch.id

    stats = _ingest_master_sheet_rows(session, parsed["rows"], batch=batch)
    session.commit()

    try:
        refresh_read_only_replica()
    except (OSError, sqlite3.Error) as exc:
        logger.warning("Replica read-only non aggiornata (ADR-0004, non bloccante): %s", exc)

    return {
        "import_batch_id": batch.id,
        "imported": stats["imported"],
        "skipped_duplicates": stats["skipped_duplicates"],
        "skipped_rows": parsed["skipped"],
        "pending_categories": stats["pending_categories"],
        "monthly_quadrature": _monthly_quadrature(stats["imported_rows"], parsed["monthly_reference"]),
    }
