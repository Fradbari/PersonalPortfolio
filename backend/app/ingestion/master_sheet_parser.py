"""Adapter master sheet storico: un-pivot wide -> long (ADR-0012/ADR-0015).

Layout reale (ispezionato `Spese - V.2.xlsx`, tab `2026`): **riga 1 = header reale**
(a differenza di My Finance/ADR-0013 dove riga 1 è un titolo da skippare) — colonne
categoria in un intervallo dinamico tra `Data:` (esclusa) e `Commenti puliti` (esclusa).
Tre tipi di riga distinti dal valore posizionale della colonna `Data:` (per riga):

- `datetime` -> riga spesa: una `Transaction` per ogni colonna categoria non-nulla/non-zero
  (`comment` = valore condiviso di `Commenti puliti`, applicato a tutte le transazioni
  generate dalla riga).
- stringa letterale `"Entrate"` -> riga reddito: una `Transaction`, `amount` = colonna 2
  per **posizione** (NON significa la categoria del suo header), `category_raw` = valore
  di `Commenti puliti`, `date` = ultimo giorno del mese corrente tracciato (nessun giorno
  preciso disponibile nel foglio per le entrate, convenzione concordata con l'utente).
- stringa letterale `"Totale %"` -> mai una transazione: riferimento mensile per la
  quadratura del dry-run (`Totale cumulato:`, `Spese`, `Differenza:`, `Accumulo totale`,
  `Trattenuta globali in busta paga `). Colonne percentuale (incluso `#DIV/0!`) ignorate.
- stringa = nome mese italiano letterale (`Gennaio`..`Dicembre`) -> marcatore esplicito
  (presente solo per i blocchi Luglio-Dicembre), aggiorna il mese/anno tracciato ma non
  produce transazioni.
- vuota/NaN -> riga vuota (righe di separazione tra blocchi mensili), scartata.

Tracciamento mese corrente (per datare le righe "Entrate" e associare le righe "Totale %"
al mese giusto): aggiornato da ogni riga-data reale incontrata (year/month della data
stessa) oppure da un marcatore di mese italiano letterale (year sempre
`sheet_year` per questo tab). Una riga "Entrate" incontrata prima di
qualunque riga-data/marcatore (mese sconosciuto) viene scartata con motivo esplicito nel
report — non blocca il resto del parsing (ADR-0015 punto 5).

Conto sempre `"principale"` (ADR-0012). Currency sempre `"EUR"` (nessuna colonna valuta in
questo foglio, a differenza di My Finance/ADR-0013).
"""
from __future__ import annotations

import calendar
from datetime import datetime
from typing import Any, BinaryIO

import pandas as pd

# Nomi colonna attesi in riga 1 (header reale, ADR-0015).
COL_DATE = "Data:"
COL_COMMENT = "Commenti puliti"
COL_TOTALE_CUMULATO = "Totale cumulato:"
COL_SPESE = "Spese"
COL_DIFFERENZA = "Differenza:"
COL_ACCUMULO_TOTALE = "Accumulo totale"
COL_TRATTENUTA = "Trattenuta globali in busta paga "

MARKER_ENTRATE = "Entrate"
MARKER_TOTALE_PCT = "Totale %"

ITALIAN_MONTHS: dict[str, int] = {
    "Gennaio": 1,
    "Febbraio": 2,
    "Marzo": 3,
    "Aprile": 4,
    "Maggio": 5,
    "Giugno": 6,
    "Luglio": 7,
    "Agosto": 8,
    "Settembre": 9,
    "Ottobre": 10,
    "Novembre": 11,
    "Dicembre": 12,
}

DEFAULT_ACCOUNT = "principale"
DEFAULT_CURRENCY = "EUR"


def _clean_str(value: Any) -> str | None:
    """Normalizza una cella pandas in stringa pulita, o None se vuota/NaN."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value))


def _last_day_of_month(year: int, month: int) -> datetime:
    day = calendar.monthrange(year, month)[1]
    return datetime(year, month, day)


def _category_columns(columns: list[str]) -> list[str]:
    """Intervallo dinamico (per nome, non indice fisso) tra `Data:` e `Commenti puliti`,
    entrambi esclusi (ADR-0015 punto 1)."""
    start = columns.index(COL_DATE) + 1
    end = columns.index(COL_COMMENT)
    return columns[start:end]


def _safe_float(value: Any) -> float | None:
    if _is_blank(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_master_sheet_xlsx(file: str | BinaryIO, sheet_name: str, sheet_year: int) -> dict:
    """Legge il tab `sheet_name` (parametro obbligatorio `sheet_year: int`, ADR-0012) del
    master sheet storico e produce righe pronte per la stessa pipeline hash/reconciliation
    di F1 (`app.ingestion.reconciliation`).

    Ritorna un dict:
    - `rows`: lista di dict con chiavi `date`, `amount`, `currency` ("EUR"), `category_raw`,
      `account_raw` ("principale"), `comment`, `type` ("expense"|"income") — stesso
      contratto di `parse_my_finance_xlsx`.
    - `skipped`: lista di `{row_number, reason}` (riga vuota, marcatore mese, riga
      `Totale %`, riga `Entrate` senza mese deducibile, valore non numerico inatteso, ecc.).
      `row_number` = numero riga Excel 1-based (riga 1 = header).
    - `monthly_reference`: lista di `{year, month, spese_sheet, differenza,
      totale_cumulato, accumulo_totale, trattenuta}`, una per ogni riga `Totale %`
      incontrata, associata al mese tracciato in quel punto della scansione.
    """
    sheet = sheet_name
    df = pd.read_excel(file, sheet_name=sheet, engine="openpyxl")

    columns = list(df.columns)
    category_cols = _category_columns(columns)
    # Righe "Entrate": importo sempre nella prima colonna categoria per POSIZIONE
    # (ADR-0015 punto 3) — non significa che la categoria reddito sia quella del suo header.
    income_amount_col = category_cols[0]

    rows: list[dict] = []
    skipped: list[dict] = []
    monthly_reference: list[dict] = []

    current_year: int | None = None
    current_month: int | None = None

    for pandas_idx, record in enumerate(df.to_dict(orient="records")):
        row_number = pandas_idx + 2  # riga 1 = header
        marker = record.get(COL_DATE)

        if _is_blank(marker):
            skipped.append({"row_number": row_number, "reason": "riga vuota"})
            continue

        if isinstance(marker, str) and marker in ITALIAN_MONTHS:
            current_year = sheet_year
            current_month = ITALIAN_MONTHS[marker]
            skipped.append({"row_number": row_number, "reason": f"marcatore mese ({marker})"})
            continue

        if isinstance(marker, str) and marker == MARKER_TOTALE_PCT:
            monthly_reference.append(
                {
                    "year": current_year,
                    "month": current_month,
                    "spese_sheet": _safe_float(record.get(COL_SPESE)),
                    "differenza": _safe_float(record.get(COL_DIFFERENZA)),
                    "totale_cumulato": _safe_float(record.get(COL_TOTALE_CUMULATO)),
                    "accumulo_totale": _safe_float(record.get(COL_ACCUMULO_TOTALE)),
                    "trattenuta": _safe_float(record.get(COL_TRATTENUTA)),
                }
            )
            skipped.append(
                {"row_number": row_number, "reason": "riga aggregata 'Totale %' (riferimento mensile, non transazione)"}
            )
            continue

        if isinstance(marker, str) and marker == MARKER_ENTRATE:
            if current_year is None or current_month is None:
                skipped.append(
                    {"row_number": row_number, "reason": "riga 'Entrate' senza mese deducibile (nessuna riga-data/marcatore precedente)"}
                )
                continue

            raw_amount = record.get(income_amount_col)
            if _is_blank(raw_amount) or not isinstance(raw_amount, (int, float)):
                skipped.append(
                    {"row_number": row_number, "reason": f"riga 'Entrate' con importo non numerico/mancante: {raw_amount!r}"}
                )
                continue

            category_raw = _clean_str(record.get(COL_COMMENT))
            if category_raw is None:
                skipped.append({"row_number": row_number, "reason": "riga 'Entrate' senza categoria (Commenti puliti vuoto)"})
                continue

            rows.append(
                {
                    "date": _last_day_of_month(current_year, current_month),
                    "amount": float(raw_amount),
                    "currency": DEFAULT_CURRENCY,
                    "category_raw": category_raw,
                    "account_raw": DEFAULT_ACCOUNT,
                    "comment": None,
                    "type": "income",
                }
            )
            continue

        if isinstance(marker, datetime):
            date = datetime(marker.year, marker.month, marker.day)  # troncato al giorno (ADR-0005)
            current_year, current_month = date.year, date.month

            comment = _clean_str(record.get(COL_COMMENT))
            any_category = False
            for cat_col in category_cols:
                raw_value = record.get(cat_col)
                if _is_blank(raw_value):
                    continue
                if not isinstance(raw_value, (int, float)):
                    # difensivo: non atteso su righe spesa reali (visto solo su righe
                    # 'Totale %', già gestite sopra e mai arrivano qui).
                    skipped.append(
                        {
                            "row_number": row_number,
                            "reason": f"valore non numerico inatteso in colonna '{cat_col}': {raw_value!r}",
                        }
                    )
                    continue
                if raw_value == 0:
                    # colonna categoria non valorizzata (zero): esclusa (ADR-0015 punto 2).
                    continue
                any_category = True
                rows.append(
                    {
                        "date": date,
                        "amount": float(raw_value),
                        "currency": DEFAULT_CURRENCY,
                        "category_raw": cat_col,
                        "account_raw": DEFAULT_ACCOUNT,
                        "comment": comment,
                        "type": "expense",
                    }
                )
            if not any_category:
                skipped.append({"row_number": row_number, "reason": "riga data senza alcuna categoria valorizzata"})
            continue

        # Difensivo: valore in colonna 'Data:' non riconosciuto (non atteso sui dati reali
        # ispezionati in ADR-0015) — segnalato invece di ignorato silenziosamente.
        skipped.append({"row_number": row_number, "reason": f"valore non riconosciuto in colonna 'Data:': {marker!r}"})

    return {"rows": rows, "skipped": skipped, "monthly_reference": monthly_reference}
