"""Engine SQLite in WAL mode (ADR-0001). FastAPI = unico writer."""
import shutil
import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

Base = declarative_base()

engine = create_engine(
    settings.db_url,
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):
    """WAL abilita reader concorrenti sicuri (necessario per la replica Metabase)."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def refresh_read_only_replica() -> None:
    """Rigenera la replica read-only per Metabase (ADR-0004, ADR-0017).

    Un DB in WAL richiede creare/aprire i file ausiliari `-wal`/`-shm` anche in lettura,
    impossibile su un mount realmente read-only (SQLITE_CANTOPEN). Per questo la copia
    viene convertita a journal_mode=DELETE dopo lo checkpoint, cosi' e' apribile senza
    side file.
    """
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE);")
    shutil.copy2(settings.db_path, settings.replica_path)
    replica_conn = sqlite3.connect(settings.replica_path)
    try:
        replica_conn.execute("PRAGMA journal_mode=DELETE;")
    finally:
        replica_conn.close()
