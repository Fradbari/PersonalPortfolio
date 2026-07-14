"""FastAPI app — scheletro Fase 0 + endpoint ingestion Fase 1."""
from fastapi import FastAPI

from app.config import settings
from app.routers import categories, imports

app = FastAPI(title="Personal Portfolio", version="0.1.0-phase1")

app.include_router(imports.router)
app.include_router(categories.router)


@app.get("/health")
def health():
    """Healthcheck usato da Docker (ADR: one-click)."""
    return {"status": "ok", "phase": "1", "db_path": settings.db_path}


@app.get("/")
def root():
    return {"app": "Personal Portfolio", "docs": "/docs"}
