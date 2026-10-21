"""Test per il riaggancio di `backup_on_startup` nel lifespan di `app/main.py`
a `get_effective` (T5, ADR-0027 p.3: DB > env > default).

Verifica che il comportamento del lifespan (avviare o no il thread di backup
all'avvio) cambi in base al valore scritto nella tabella `settings`, non solo
al default statico di `app.config.settings` -- non un semplice "la funzione
viene chiamata", ma un cambio di comportamento reale osservabile a due
combinazioni di valore DB / default config diverse.

`threading.Thread` e' sostituito con uno stub sincrono per rendere il test
deterministico (nessun sleep/race su un vero thread in background); e'
l'unico stub, coerente con ADR-0018 p.7 (mock solo per dipendenze esterne
non deterministiche -- qui la "dipendenza esterna" e' il thread reale,
DB e business logic (`get_effective`) restano reali).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main as main_module
from app.db import Base
from app.models import Settings, Transaction
from app.services import settings as settings_service
from app.services.search import sqlite_has_fts5


class _SyncThread:
    """Sostituisce `threading.Thread`: esegue il target subito e in modo
    sincrono invece di spawnare un thread reale."""

    def __init__(self, target=None, daemon=None):
        self._target = target

    def start(self):
        if self._target is not None:
            self._target()


def _patch_settings_db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    return _patch_engine(monkeypatch, engine)


def _patch_engine(monkeypatch, engine):
    Session = sessionmaker(bind=engine, future=True)
    # get_effective(session=None) apre una SessionLocal propria: la puntiamo a questo
    # engine di test, stesso pattern di test_settings_service.py.
    monkeypatch.setattr(settings_service, "SessionLocal", Session)
    # Senza questo patch il lifespan toccherebbe l'engine di produzione (/data/portfolio.db).
    monkeypatch.setattr(main_module, "engine", engine)
    return Session


def _run_lifespan_once():
    async def _go():
        async with main_module.lifespan(main_module.app):
            pass

    asyncio.run(_go())


def test_backup_on_startup_db_true_starts_backup_even_if_config_default_false(monkeypatch):
    Session = _patch_settings_db(monkeypatch)
    with Session() as session:
        session.add(Settings(key="backup_on_startup", value="true"))
        session.commit()

    assert main_module.settings.backup_on_startup is False  # default di config invariato

    monkeypatch.setattr(main_module.threading, "Thread", _SyncThread)

    called = {"run_backup": False}

    def fake_run_backup(**_kwargs):
        called["run_backup"] = True
        return {}

    monkeypatch.setattr(main_module.backup, "run_backup", fake_run_backup)

    _run_lifespan_once()

    assert called["run_backup"] is True


def test_backup_on_startup_db_false_skips_backup_even_if_config_default_true(monkeypatch):
    Session = _patch_settings_db(monkeypatch)
    with Session() as session:
        session.add(Settings(key="backup_on_startup", value="false"))
        session.commit()

    monkeypatch.setattr(main_module.settings, "backup_on_startup", True)  # config direbbe True

    monkeypatch.setattr(main_module.threading, "Thread", _SyncThread)

    called = {"run_backup": False}

    def fake_run_backup(**_kwargs):
        called["run_backup"] = True
        return {}

    monkeypatch.setattr(main_module.backup, "run_backup", fake_run_backup)

    _run_lifespan_once()

    assert called["run_backup"] is False


def test_backup_on_startup_skipped_without_failing_boot_when_settings_table_missing(
    monkeypatch, caplog
):
    """Fix T5-review: prima di questo fix, `get_effective("backup_on_startup")` non
    era avvolto in try/except nel lifespan -- una tabella `settings` non ancora
    migrata (o un DB irraggiungibile) faceva fallire l'intero boot dell'app, non solo
    il backup di avvio (violazione di ADR-0018 punto 6: "best-effort, non deve
    bloccare l'avvio"). Qui l'engine di test non ha `Base.metadata.create_all`
    eseguito: nessuna tabella esiste, `get_effective` solleva
    `OperationalError: no such table: settings`. La prova del fix e' duplice: (a) il
    lifespan completa senza sollevare; (b) il thread di backup NON parte e viene
    loggato un warning invece di un errore silenzioso o un crash."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    # NB: nessun Base.metadata.create_all -- simula un DB non ancora migrato.
    _patch_engine(monkeypatch, engine)

    monkeypatch.setattr(main_module.threading, "Thread", _SyncThread)

    called = {"run_backup": False}

    def fake_run_backup(**_kwargs):
        called["run_backup"] = True
        return {}

    monkeypatch.setattr(main_module.backup, "run_backup", fake_run_backup)

    with caplog.at_level(logging.WARNING):
        _run_lifespan_once()  # non deve sollevare: e' proprio questo il fix

    assert called["run_backup"] is False
    assert any(
        record.levelno == logging.WARNING and "backup_on_startup" in record.message
        for record in caplog.records
    )


# --- Guardrail FTS all'avvio (ADR-0029 p.3, ADR-0034 p.5) ----------------------


def test_sqlite_has_fts5_true_in_this_environment():
    assert sqlite_has_fts5() is True


def test_lifespan_raises_when_sqlite_has_no_fts5(monkeypatch):
    _patch_settings_db(monkeypatch)
    monkeypatch.setattr(main_module, "sqlite_has_fts5", lambda: False)

    with pytest.raises(RuntimeError, match="FTS5"):
        _run_lifespan_once()


def test_lifespan_rebuilds_desynced_fts_index(monkeypatch, fts_engine):
    _patch_engine(monkeypatch, fts_engine)
    monkeypatch.setattr(main_module.threading, "Thread", _SyncThread)

    Session = sessionmaker(bind=fts_engine, future=True)
    with Session() as session:
        txn = Transaction(
            date=datetime(2026, 3, 1), amount=42.0, currency="EUR", type="expense",
            category_raw="Alimentari", account="principale", comment="pranzo aziendale",
            tag=None, source="my_finance", hash_dedup="lifespan-rebuild-1",
        )
        session.add(txn)
        session.commit()
        txn_id = txn.id

    # Rimuove la riga dall'indice senza passare dal trigger DELETE (stato post-restore).
    with fts_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO transactions_fts(transactions_fts, rowid, comment, tag, category_raw, account) "
                "VALUES ('delete', :id, 'pranzo aziendale', NULL, 'Alimentari', 'principale')"
            ),
            {"id": txn_id},
        )
    with fts_engine.connect() as conn:
        assert conn.execute(
            text("SELECT rowid FROM transactions_fts WHERE transactions_fts MATCH 'pranzo'")
        ).fetchall() == []

    _run_lifespan_once()

    with fts_engine.begin() as conn:
        conn.execute(text("INSERT INTO transactions_fts(transactions_fts, rank) VALUES('integrity-check', 1)"))
        rows = conn.execute(
            text("SELECT rowid FROM transactions_fts WHERE transactions_fts MATCH 'pranzo'")
        ).fetchall()
    assert [r[0] for r in rows] == [txn_id]


def test_lifespan_without_fts_table_warns_and_does_not_raise(monkeypatch, caplog):
    _patch_settings_db(monkeypatch)  # create_all: nessuna virtual table

    with caplog.at_level(logging.WARNING):
        _run_lifespan_once()

    assert any(
        record.levelno == logging.WARNING and "transactions_fts" in record.message
        for record in caplog.records
    )


def test_lifespan_rebuild_failure_logs_error_and_does_not_raise(monkeypatch, fts_engine, caplog):
    _patch_engine(monkeypatch, fts_engine)

    def boom(_engine):
        raise RuntimeError("rebuild boom")

    monkeypatch.setattr(main_module, "rebuild_fts_index", boom)

    with caplog.at_level(logging.ERROR):
        _run_lifespan_once()  # non deve sollevare

    assert any(
        record.levelno == logging.ERROR and "rebuild" in record.message.lower()
        for record in caplog.records
    )
