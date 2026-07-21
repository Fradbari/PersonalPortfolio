"""Test parser master sheet storico (`app.ingestion.master_sheet_parser`, T4).

Fixture minime costruite con `openpyxl.Workbook` in memoria (nessun file su disco),
lette poi con `pd.read_excel` dallo stesso `BytesIO` passato al parser — stesso percorso
usato in produzione (upload multipart -> `io.BytesIO(content)`, `app/routers/imports.py`).
"""
from __future__ import annotations

import io
from datetime import datetime

from openpyxl import Workbook

from app.ingestion.master_sheet_parser import COL_COMMENT, COL_DATE, parse_master_sheet_xlsx


def _build_xlsx(sheet_title: str, rows: list[list]) -> io.BytesIO:
    """Crea un xlsx in memoria con un solo sheet: header fisso (`Data:`, `Spesa Casa`,
    `Commenti puliti`) + le righe passate, una lista per riga nell'ordine delle colonne."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title
    ws.append([COL_DATE, "Spesa Casa", COL_COMMENT])
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


# --- Contratto centrale del bugfix T4: ramo ITALIAN_MONTHS -> sheet_year ------------


def test_italian_month_marker_uses_sheet_year_not_tab_name():
    """Il ramo `ITALIAN_MONTHS` deve datare `current_year` da `sheet_year` (parametro
    esplicito), MAI dal nome del tab Excel. Il tab qui si chiama "2099" apposta: se il
    parser leggesse ancora `settings.import_min_year` o il nome del tab, la riga
    "Entrate" sotto verrebbe datata 2099 invece di sheet_year=2025 -- e' esattamente il
    bug latente descritto nel brief T4."""
    buffer = _build_xlsx(
        sheet_title="2099",
        rows=[
            ["Luglio", None, None],  # marcatore mese italiano: month=7, year=sheet_year
            ["Entrate", 1500.0, "Stipendio"],
        ],
    )

    parsed = parse_master_sheet_xlsx(buffer, sheet_name="2099", sheet_year=2025)

    assert len(parsed["rows"]) == 1
    row = parsed["rows"][0]
    assert row["type"] == "income"
    assert row["date"] == datetime(2025, 7, 31)  # ultimo giorno di luglio 2025, non 2099
    assert row["amount"] == 1500.0
    assert row["category_raw"] == "Stipendio"


def test_datetime_row_dates_from_real_date_not_sheet_year():
    """Le righe-data reali (datetime esplicito) restano indipendenti da `sheet_year`:
    `current_year` segue sempre year/month della data stessa, mai il parametro."""
    buffer = _build_xlsx(
        sheet_title="2026",
        rows=[
            [datetime(2026, 3, 15), 42.5, "nota"],
        ],
    )

    parsed = parse_master_sheet_xlsx(buffer, sheet_name="2026", sheet_year=1900)

    assert len(parsed["rows"]) == 1
    row = parsed["rows"][0]
    assert row["type"] == "expense"
    assert row["date"] == datetime(2026, 3, 15)
    assert row["amount"] == 42.5
    assert row["category_raw"] == "Spesa Casa"
    assert row["comment"] == "nota"


def test_entrate_before_any_marker_is_skipped_with_reason():
    """Riga "Entrate" senza alcuna riga-data/marcatore precedente: mese sconosciuto,
    scartata con motivo esplicito, non blocca il resto del parsing (ADR-0015 punto 5)."""
    buffer = _build_xlsx(
        sheet_title="2026",
        rows=[
            ["Entrate", 1000.0, "Stipendio"],
        ],
    )

    parsed = parse_master_sheet_xlsx(buffer, sheet_name="2026", sheet_year=2026)

    assert parsed["rows"] == []
    assert len(parsed["skipped"]) == 1
    assert "senza mese deducibile" in parsed["skipped"][0]["reason"]
