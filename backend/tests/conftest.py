"""Fixture condivise per la suite pytest.

Primo `conftest.py` del progetto (nasce in T3, F12/ADR-0029). Il resto della suite
costruisce lo schema con `Base.metadata.create_all()` su `sqlite://` in-memory — va
benissimo per i test dei router, ma `create_all()` non conosce le virtual table SQLite:
`transactions_fts` e i suoi 3 trigger (migration 0005) non esisterebbero mai in un DB
cosi' creato, e un test che li cercasse otterrebbe un falso positivo (o un falso
negativo) senza che Alembic sia mai girato per davvero. Serve quindi un secondo modo di
costruire un DB di test: applicare le migration reali su un file in `tmp_path`.

Strategia A (spec Blocco B, `docs/superpowers/specs/2026-07-25-f11-f12-f13-detail-spec.md`
§6): un `EnvironmentContext` esplicito che riceve la connessione gia' aperta via
`.configure(connection=..., target_metadata=..., render_as_batch=True)`, bypassando la
lettura di `sqlalchemy.url` da `config.main_option`.

Deliberatamente NON usata: eseguire `backend/alembic/env.py` (via
`ScriptDirectory.run_env()`, o via `alembic.command.upgrade/downgrade`, che internamente
chiama `run_env()`). Il file `env.py` importa `app.db`/`app.config` e, al fondo, esegue
sempre `run_migrations_online()`, che costruisce il **proprio** engine con
`engine_from_config(config.get_section(...))` leggendo `sqlalchemy.url` — cioe' l'URL di
produzione (`settings.db_url`), impostato da `env.py` stesso alla riga 12. Anche
`config.attributes['connection']` NON e' un'alternativa valida per lo stesso motivo:
`run_migrations_online()` non esamina mai `config.attributes`. Imboccare una di queste
due strade farebbe girare la migration sul DB di produzione invece che su `tmp_path`,
**senza alcun errore visibile** (il file esiste, la migration ci scrive sopra "con
successo") — da cui la scelta di non toccare `env.py` per niente e replicare qui solo le
due chiamate che servono (`configure` + `run_migrations`).

LIMITE NOTO, dichiarato invece che solo saputo: `alembic/env.py:8` importa `app.db`
PRIMA ancora di `app.models` (riga 9), e `app.db` costruisce l'engine di produzione **al
momento dell'import** (livello di modulo, `db.py:12`). L'import di `app.models` qui
sotto ha lo stesso identico effetto per transitivita' (`app/models.py` fa
`from app.db import Base`). Questa fixture impedisce ad Alembic di *usare* quell'URL di
produzione (la connessione passata a `configure()` e' sempre e solo quella su
`tmp_path`), ma NON impedisce all'engine di produzione di *nascere* come effetto
collaterale dell'import. Oggi e' innocuo perche' `app.db` non esegue alcun DDL
all'import (solo `create_engine(...)`, lazy per costruzione — nessuna connessione reale
finche' qualcuno non la usa): se un giorno `app.db` eseguisse un PRAGMA o un
`create_all()` a livello di modulo, questa fixture andrebbe rivista. E' anche il motivo
per cui il criterio di accettazione include esplicitamente "`data/portfolio.db` intatto
dopo il run" — e' la rete di sicurezza che renderebbe rumoroso un eventuale regressione.
"""
import sys
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Fix post-review (Finding 5 MINOR): non esiste alcun `pytest.ini`/`pyproject.toml`/
# `setup.cfg`/`tox.ini` in `backend/`, e `tests/` non ha `__init__.py` — pytest
# aggiunge a `sys.path` la directory di `tests/`, non `backend/`. Senza questo
# insert, `import app.db` qui sotto fallisce con `ModuleNotFoundError: No module
# named 'app'` quando pytest e' invocato come comando bare (`pytest ...`).
# Funzionava solo con `python -m pytest` dalla cwd `backend/` (che antepone la cwd
# a `sys.path` per conto proprio) — merito dell'invocazione, non della
# configurazione del progetto.
sys.path.insert(0, str(BACKEND_DIR))

from app.db import Base
import app.models  # noqa: F401 — registra i modelli in Base.metadata (stesso import di alembic/env.py:9)


def _alembic_config() -> Config:
    """Config Alembic con `script_location` assoluto: indipendente dalla cwd da cui
    gira pytest (a differenza di quanto scritto in `alembic.ini`, che usa un path
    relativo pensato per l'invocazione da riga di comando dentro `backend/`)."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def _migrate(connection: Connection, *, revision: str, downgrade: bool) -> None:
    """Nucleo comune di `run_alembic_upgrade`/`run_alembic_downgrade`: costruisce un
    `EnvironmentContext` esplicito e gli fa eseguire le migration fino a `revision`,
    sulla connessione data."""
    cfg = _alembic_config()
    script = ScriptDirectory.from_config(cfg)

    def _fn(rev: Any, _context: Any) -> Any:
        if downgrade:
            return script._downgrade_revs(revision, rev)
        return script._upgrade_revs(revision, rev)

    with EnvironmentContext(cfg, script, fn=_fn) as env_context:
        env_context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            render_as_batch=True,  # coerente con env.py: SQLite ALTER via batch
        )
        with env_context.begin_transaction():
            env_context.run_migrations()


def run_alembic_upgrade(connection: Connection, revision: str = "head") -> None:
    """Equivalente di `alembic upgrade <revision>` sulla connessione data."""
    _migrate(connection, revision=revision, downgrade=False)


def run_alembic_downgrade(connection: Connection, revision: str = "-1") -> None:
    """Equivalente di `alembic downgrade <revision>` sulla connessione data."""
    _migrate(connection, revision=revision, downgrade=True)


@pytest.fixture
def fts_engine(tmp_path: Path):
    """Engine SQLite su `tmp_path` con `alembic upgrade head` gia' applicato.

    A differenza del resto della suite (`Base.metadata.create_all()` su `sqlite://`
    in-memory), qui gira la migration reale: `transactions_fts` e i suoi 3 trigger
    (revision 0005) esistono davvero nel DB restituito. Mai `data/portfolio.db`: il file
    vive in `tmp_path`, cancellato da pytest a fine sessione.

    Fixture volutamente minima (nome chiaro apposta): T4 la estende per i test dei
    filtri avanzati che hanno bisogno dello stesso DB migrato a head.
    """
    db_path = tmp_path / "fts_test.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    with engine.connect() as connection:
        run_alembic_upgrade(connection)
    try:
        yield engine
    finally:
        engine.dispose()
