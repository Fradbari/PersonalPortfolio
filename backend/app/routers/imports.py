"""`POST /import/my-finance` — upload export My Finance `.xlsx` (Fase 1).

Flusso: parse (Spese+Entrate, Bonifici ignorato ADR-0007) -> dedup hash batch (ADR-0005)
-> category mapper + reconciliation queue (ADR-0006/ADR-0013) -> conti as-is -> ImportBatch
audit -> commit -> replica read-only atomica per Metabase (ADR-0004, best-effort).
"""
from __future__ import annotations

import io
import logging
import shutil

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.ingestion.my_finance_parser import parse_my_finance_xlsx
from app.ingestion.reconciliation import compute_hash_dedup, get_or_create_account, resolve_category
from app.models import CategoryPending, ImportBatch, Transaction

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/import", tags=["import"])

SOURCE = "my_finance"


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
        shutil.copy2(settings.db_path, settings.replica_path)
    except OSError as exc:
        logger.warning("Replica read-only non aggiornata (ADR-0004, non bloccante): %s", exc)

    return {
        "import_batch_id": batch.id,
        "imported": imported,
        "skipped_duplicates": skipped_duplicates,
        "skipped_invalid_rows": skipped_invalid_rows,
        "pending_categories": pending_categories,
    }
