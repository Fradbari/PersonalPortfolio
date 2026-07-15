"""FastAPI app — scheletro Fase 0 + ingestion (Fase 1/2) + backup (Fase 4)."""
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.routers import accounts, backup, categories, imports, insights, transactions

logger = logging.getLogger(__name__)


def _run_startup_backup() -> None:
    try:
        backup.run_backup()
    except Exception as exc:  # best-effort: non deve bloccare l'avvio (ADR-0018 punto 6)
        logger.warning("Backup all'avvio fallito (non bloccante): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.backup_on_startup:
        threading.Thread(target=_run_startup_backup, daemon=True).start()
    yield


app = FastAPI(title="Personal Portfolio", version="0.1.0-phase4", lifespan=lifespan)

app.include_router(imports.router)
app.include_router(categories.router)
app.include_router(backup.router)
app.include_router(transactions.router)
app.include_router(accounts.router)
app.include_router(insights.router)


@app.get("/health")
def health():
    """Healthcheck usato da Docker (ADR: one-click)."""
    return {"status": "ok", "phase": "4", "db_path": settings.db_path}


@app.get("/")
def root():
    return {"app": "Personal Portfolio", "docs": "/docs"}
