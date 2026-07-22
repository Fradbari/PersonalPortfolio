"""FastAPI app — scheletro Fase 0 + ingestion (Fase 1/2) + backup (Fase 4)."""
import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import accounts, ai, backup, categories, imports, insights, settings as settings_router, transactions
from app.services.settings import get_effective

logger = logging.getLogger(__name__)


def _run_startup_backup() -> None:
    try:
        backup.run_backup()
    except Exception as exc:  # best-effort: non deve bloccare l'avvio (ADR-0018 punto 6)
        logger.warning("Backup all'avvio fallito (non bloccante): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # backup_on_startup letto via get_effective (F9, ADR-0027 p.3: DB > env > default)
    # invece che da config.settings direttamente -- letto al boot, coerente con
    # "solo al boot successivo" della whitelist. Nessuna sessione disponibile qui
    # (fuori da una richiesta HTTP): session=None (default di get_effective).
    # get_effective ora e' una query SQL obbligatoria (prima era una lettura in memoria
    # mai fallibile): se il DB non e' ancora migrato o irraggiungibile, l'eccezione va
    # catturata qui, prima dello yield -- altrimenti bloccherebbe l'avvio dell'intera
    # app (incluso /health), non solo il backup di avvio. Stesso spirito best-effort di
    # _run_startup_backup (ADR-0018 punto 6): fallback sicuro = niente backup di avvio.
    try:
        backup_on_startup = get_effective("backup_on_startup")[0]
    except Exception as exc:  # best-effort: non deve bloccare l'avvio (ADR-0018 punto 6)
        logger.warning(
            "Lettura di backup_on_startup fallita all'avvio, backup di avvio saltato "
            "(non bloccante): %s",
            exc,
        )
        backup_on_startup = False

    if backup_on_startup:
        threading.Thread(target=_run_startup_backup, daemon=True).start()
    yield


app = FastAPI(title="Personal Portfolio", version="0.1.0-phase7", lifespan=lifespan)

app.include_router(imports.router)
app.include_router(categories.router)
app.include_router(backup.router)
app.include_router(transactions.router)
app.include_router(accounts.router)
app.include_router(insights.router)
app.include_router(ai.router)
app.include_router(settings_router.router)


@app.get("/health")
def health():
    """Healthcheck usato da Docker (ADR: one-click)."""
    return {"status": "ok", "phase": "7", "db_path": settings.db_path}


FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend_dist")

# Route SPA registrate in frontend/src/App.tsx (ADR-0033: nessuna condivide il
# path esatto con un endpoint API). Tenere allineata a quel file -- un test di
# regressione (T7) verifica questo insieme, non la disciplina. frozenset a
# livello di modulo cosi' esiste anche quando FRONTEND_DIST non e' presente
# (dev locale senza build), per essere importabile dai test in entrambi i casi.
SPA_ROUTES = frozenset(
    {
        "/",
        "/transazioni",
        "/import",
        "/categorie-pending",
        "/conti",
        "/backup-restore",
        "/assistente-ai",
        "/impostazioni",
    }
)


def mount_spa(app: FastAPI, dist_dir: str) -> None:
    """Monta la SPA React compilata: assets statici + favicon + catch-all.

    Estratta dal blocco un tempo inline sotto `if os.path.isdir(FRONTEND_DIST):`
    per essere invocabile anche su un'app di prova nei test (T6b), a comportamento
    di produzione identico.
    """
    # Build Docker con frontend compilato: serve la SPA React su "/" e fallback
    # client-side routing per ogni path non gia' gestito da un router API sopra.
    app.mount("/assets", StaticFiles(directory=os.path.join(dist_dir, "assets")), name="frontend-assets")

    # File statici copiati da frontend/public/ alla root del build Vite (non sotto
    # /assets, che contiene solo il bundle JS/CSS con hash). Registrati PRIMA del
    # catch-all sotto: Starlette fa match per ordine di registrazione, non per
    # specificita' di path, quindi devono precedere "/{full_path:path}" (DEBT-02).
    @app.get("/favicon.svg")
    def favicon():
        return FileResponse(os.path.join(dist_dir, "favicon.svg"))

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        return FileResponse(os.path.join(dist_dir, "index.html"))


if os.path.isdir(FRONTEND_DIST):
    mount_spa(app, FRONTEND_DIST)
else:
    # Dev locale senza build frontend (es. backend lanciato da solo): fallback JSON.
    @app.get("/")
    def root():
        return {"app": "Personal Portfolio", "docs": "/docs"}
