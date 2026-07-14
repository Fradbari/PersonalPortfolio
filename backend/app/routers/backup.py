"""`POST /backup` — backup manuale (dump + xlsx + locale + Drive best-effort + retention).
`GET /backup` — lista backup locali disponibili.
`POST /backup/restore` — restore da backup locale (operazione distruttiva, richiede
conferma esplicita). ADR-0018."""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.backup import BACKUP_PREFIX, apply_local_retention, create_backup, list_local_backups, restore_from_backup
from app.config import settings
from app.db import engine, refresh_read_only_replica
from app.drive import apply_drive_retention, get_drive_service, upload_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backup", tags=["backup"])


def run_backup() -> dict:
    """Punto unico riusato dall'endpoint manuale e dal job opzionale all'avvio
    (ADR-0018 punto 6)."""
    result = create_backup(engine, settings.db_path, settings.backup_dir)

    drive_uploaded = False
    drive_error: str | None = None
    drive_deleted: list[str] = []
    try:
        # get_drive_service() e' dentro il try: una Service Account key presente
        # ma malformata/corrotta solleva un'eccezione da from_service_account_file()
        # (non solo "file assente" - quello ritorna None senza eccezione) e deve
        # restare best-effort come il resto del blocco Drive (ADR-0004/ADR-0018).
        service = get_drive_service(settings.google_sa_key_path)
        if service is None:
            drive_error = "Service Account non montata: upload Drive skippato."
        else:
            upload_file(service, result.db_path, settings.gdrive_backup_folder_id)
            upload_file(service, result.xlsx_path, settings.gdrive_backup_folder_id)
            drive_uploaded = True
            drive_deleted = apply_drive_retention(service, settings.gdrive_backup_folder_id, settings.backup_retention)
    except Exception as exc:  # SA malformata/rete/permessi Drive: best-effort (ADR-0004/ADR-0018)
        drive_error = str(exc)
        logger.warning("Backup Drive fallito (non bloccante): %s", exc)

    local_deleted = apply_local_retention(settings.backup_dir, settings.backup_retention)

    return {
        "db_path": result.db_path,
        "xlsx_path": result.xlsx_path,
        "row_count": result.row_count,
        "drive_uploaded": drive_uploaded,
        "drive_error": drive_error,
        "local_deleted": local_deleted,
        "drive_deleted": drive_deleted,
    }


@router.post("")
def backup_now():
    return run_backup()


@router.get("")
def list_backups():
    return {"backups": list_local_backups(settings.backup_dir)}


class RestoreRequest(BaseModel):
    filename: str
    confirm: bool = False


@router.post("/restore")
def restore(payload: RestoreRequest):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Restore richiede 'confirm: true' (operazione distruttiva, ADR-0018).")

    # os.path.basename() PRIMA della validazione: neutralizza qualunque componente di
    # path (".." o separatori) in payload.filename prima che partecipi al pattern-check
    # e al join, cosi' il file risolto non puo' mai uscire da settings.backup_dir
    # (path traversal, trovato in review Task 4).
    filename = os.path.basename(payload.filename)
    if not filename.startswith(BACKUP_PREFIX) or not filename.endswith(".db"):
        raise HTTPException(status_code=400, detail="filename atteso: portfolio_backup_YYYYMMDD_HHMMSS.db")

    backup_dir_abs = os.path.abspath(settings.backup_dir)
    backup_db_path = os.path.abspath(os.path.join(backup_dir_abs, filename))
    if os.path.dirname(backup_db_path) != backup_dir_abs:
        raise HTTPException(status_code=400, detail="filename atteso: portfolio_backup_YYYYMMDD_HHMMSS.db")

    try:
        restore_from_backup(engine, backup_db_path, settings.db_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        refresh_read_only_replica()
    except Exception as exc:  # replica Metabase: best-effort (ADR-0004)
        logger.warning("Replica read-only non aggiornata dopo restore (non bloccante): %s", exc)

    return {"restored_from": filename}
