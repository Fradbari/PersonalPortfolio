"""Parser export My Finance (`.xlsx`) — sheet `Spese`/`Entrate` (ADR-0013).

Sheet `Bonifici` ignorato del tutto (ADR-0007) — non viene nemmeno letto.
Layout foglio (ADR-0013): riga 1 = titolo periodo (non dato, skippata), riga 2 = header
reale, righe successive = dati. Colonne mappate **per nome** (non per indice posizionale),
robusto a riordini futuri delle colonne nell'export.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, BinaryIO

import pandas as pd

# sheet -> transactions.type (ADR-0007: Bonifici non è nella mappa, quindi mai letto)
SHEET_TYPE_MAP: dict[str, str] = {
    "Spese": "expense",
    "Entrate": "income",
}

# Nomi header attesi in riga 2 (ADR-0013). Import canonico = "valuta predefinita";
# le altre due coppie importo/valuta (conto / transazione) sono ignorate in F1.
COL_DATE = "Data e ora"
COL_CATEGORY = "Categoria"
COL_ACCOUNT = "Conto"
COL_AMOUNT = "Importo in valuta predefinita"
COL_CURRENCY = "Valuta predefinita"
COL_TAG = "Tag"
COL_COMMENT = "Commento"

DEFAULT_CURRENCY = "EUR"


def _clean_str(value: Any) -> str | None:
    """Normalizza una cella pandas in stringa pulita, o None se vuota/NaN."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def parse_my_finance_xlsx(file: str | BinaryIO) -> tuple[list[dict], int]:
    """Legge Spese + Entrate da un export My Finance.

    Ritorna `(rows, skipped_invalid_rows)`:
    - `rows`: lista di dict con chiavi `date` (datetime troncato al giorno), `amount` (float),
      `currency` (str, fallback "EUR"), `category_raw` (str), `account_raw` (str),
      `tag` (str|None), `comment` (str|None), `type` ("expense"|"income").
    - `skipped_invalid_rows`: righe scartate perché prive di dati indispensabili
      (`Data e ora` vuota — righe finali completamente vuote, non è un errore, ADR-0013;
      oppure importo/categoria/conto mancanti, difensivo per export malformati).

    `file` può essere un path o un oggetto file-like (es. `io.BytesIO` da upload FastAPI).
    """
    rows: list[dict] = []
    skipped_invalid_rows = 0

    for sheet_name, txn_type in SHEET_TYPE_MAP.items():
        df = pd.read_excel(file, sheet_name=sheet_name, skiprows=1, engine="openpyxl")

        for record in df.to_dict(orient="records"):
            raw_date = record.get(COL_DATE)
            if raw_date is None or pd.isna(raw_date):
                # riga finale completamente vuota nel foglio: scartata, non è un errore.
                skipped_invalid_rows += 1
                continue

            raw_amount = record.get(COL_AMOUNT)
            category_raw = _clean_str(record.get(COL_CATEGORY))
            account_raw = _clean_str(record.get(COL_ACCOUNT))

            if raw_amount is None or pd.isna(raw_amount) or category_raw is None or account_raw is None:
                # riga con dati indispensabili mancanti: non costruibile come Transaction valida.
                skipped_invalid_rows += 1
                continue

            date = pd.Timestamp(raw_date).to_pydatetime()
            date = datetime(date.year, date.month, date.day)  # troncato al giorno (ADR-0005)

            rows.append(
                {
                    "date": date,
                    "amount": float(raw_amount),
                    "currency": _clean_str(record.get(COL_CURRENCY)) or DEFAULT_CURRENCY,
                    "category_raw": category_raw,
                    "account_raw": account_raw,
                    "tag": _clean_str(record.get(COL_TAG)),
                    "comment": _clean_str(record.get(COL_COMMENT)),
                    "type": txn_type,
                }
            )

    return rows, skipped_invalid_rows
