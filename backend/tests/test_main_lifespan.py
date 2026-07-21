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

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main as main_module
from app.db import Base
from app.models import Settings
from app.services import settings as settings_service


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
    Session = sessionmaker(bind=engine, future=True)
    # get_effective(session=None) apre una SessionLocal propria: la puntiamo a questo
    # engine di test, stesso pattern di test_settings_service.py.
    monkeypatch.setattr(settings_service, "SessionLocal", Session)
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

    def fake_run_backup():
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

    def fake_run_backup():
        called["run_backup"] = True
        return {}

    monkeypatch.setattr(main_module.backup, "run_backup", fake_run_backup)

    _run_lifespan_once()

    assert called["run_backup"] is False
