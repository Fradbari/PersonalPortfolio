"""FastAPI app — scheletro Fase 0. Endpoint feature aggiunti dalle fasi successive."""
from fastapi import FastAPI

from app.config import settings

app = FastAPI(title="Personal Portfolio", version="0.0.1-phase0")


@app.get("/health")
def health():
    """Healthcheck usato da Docker (ADR: one-click)."""
    return {"status": "ok", "phase": "0", "db_path": settings.db_path}


@app.get("/")
def root():
    return {"app": "Personal Portfolio", "docs": "/docs"}
