"""FastAPI app — scheletro Fase 0 + ingestion (Fase 1/2) + backup (Fase 4)."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.routers import backup, categories, imports

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.backup_on_startup:
        try:
            backup.run_backup()
        except Exception as exc:  # best-effort: non deve bloccare l'avvio (ADR-0018 punto 6)
            logger.warning("Backup all'avvio fallito (non bloccante): %s", exc)
    yield


app = FastAPI(title="Personal Portfolio", version="0.1.0-phase4", lifespan=lifespan)

app.include_router(imports.router)
app.include_router(categories.router)
app.include_router(backup.router)


@app.get("/health")
def health():
    """Healthcheck usato da Docker (ADR: one-click)."""
    return {"status": "ok", "phase": "4", "db_path": settings.db_path}


@app.get("/")
def root():
    return {"app": "Personal Portfolio", "docs": "/docs"}
