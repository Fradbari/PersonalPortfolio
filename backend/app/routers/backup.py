"""`POST /backup` — backup manuale (dump + xlsx + locale + Drive best-effort + retention).
`GET /backup` — lista backup locali disponibili.
`POST /backup/restore` — restore da backup locale (operazione distruttiva, richiede
conferma esplicita). ADR-0018."""
from __future__ import annotations

import dataclasses
import logging
import os
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.backup import (
    BACKUP_PREFIX,
    apply_local_retention,
    create_backup,
    list_local_backups,
    restore_from_backup,
    upgrade_schema_to_head,
)
from app.config import settings
from app.db import engine, refresh_read_only_replica
from app.drive import (
    apply_drive_retention,
    classify_drive_error,
    get_drive_service,
    outcome_message,
    redact,
    run_gdrive_probe,
    upload_file,
)
from app.services.search import rebuild_fts_index
from app.services.settings import get_effective

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backup", tags=["backup"])

# Serializza i restore (ADR-0034 p.6): due restore paralleli sono gia' distruttivi oggi
# (`engine.dispose()` + `shutil.copy2` senza protezione). Il lock avvolge tutti e quattro
# i blocchi nella loro interezza, non i singoli step.
_restore_lock = threading.Lock()

# Un solo probe Drive alla volta (ADR-0031): scrive davvero sul Drive dell'utente.
_probe_lock = threading.Lock()


# Ultimo esito backup del processo corrente (solo in memoria, T7b). Scritto da
# `run_backup` su successo ed errore; letto da `GET /backup/last` come copia.
# Contiene solo testi da `outcome_message` o fissi: mai `str(exc)` (CLAUDE.md regola 7).
_last_backup: dict | None = None
_last_backup_lock = threading.Lock()

_LOCAL_FAILURE_MESSAGE = "Backup locale fallito: controlla il log del backend."
_POST_LOCAL_FAILURE_MESSAGE = (
    "Copia locale creata, ma la fase successiva (impostazioni o retention) è fallita: "
    "controlla il log del backend."
)


_RETENTION_FAILURE_PREFIX = (
    "Backup caricato su Drive, ma la rotazione dei vecchi backup su Drive è fallita. "
)


def _record_last_backup(
    trigger: str,
    *,
    local_ok: bool,
    drive_uploaded: bool,
    drive_outcome: str | None,
    message: str | None,
) -> None:
    global _last_backup
    entry = {
        # UTC con offset esplicito: il browser lo converte nell'ora locale dell'utente.
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "trigger": trigger,
        "local_ok": local_ok,
        "drive_uploaded": drive_uploaded,
        "drive_outcome": drive_outcome,
        "message": message,
    }
    with _last_backup_lock:
        _last_backup = entry


def run_backup(trigger: str = "manual") -> dict:
    """Punto unico riusato dall'endpoint manuale e dal job opzionale all'avvio
    (ADR-0018 punto 6). `trigger` ("manual" | "startup") finisce solo nello stato
    "ultimo esito" (`GET /backup/last`).

    `backup_retention` e' letto via `get_effective` (F9, ADR-0027 p.3: DB > env >
    default) invece che da `config.settings` direttamente. Nessuna sessione e'
    disponibile qui: `run_backup()` e' chiamato sia dall'endpoint `POST /backup`
    sia dal thread di avvio (`main.py`, nessuna richiesta HTTP in corso) -> si
    lascia `get_effective` aprire/chiudere una propria `SessionLocal`
    (`session=None`, il default della funzione)."""
    try:
        result = create_backup(engine, settings.db_path, settings.backup_dir)
    except Exception:
        _record_last_backup(
            trigger, local_ok=False, drive_uploaded=False, drive_outcome=None,
            message=redact(_LOCAL_FAILURE_MESSAGE),
        )
        raise

    drive: dict = {"uploaded": False, "outcome": None, "error": None}
    try:
        payload = _drive_and_retention(result, drive)
    except Exception:
        # Copia locale gia' creata: l'esito resta registrato anche se la lettura di
        # backup_retention o la retention locale falliscono dopo.
        _record_last_backup(
            trigger, local_ok=True, drive_uploaded=drive["uploaded"],
            drive_outcome=drive["outcome"], message=redact(_POST_LOCAL_FAILURE_MESSAGE),
        )
        raise

    _record_last_backup(
        trigger, local_ok=True, drive_uploaded=drive["uploaded"],
        drive_outcome=drive["outcome"], message=drive["error"],
    )
    return payload


def _drive_and_retention(result, drive: dict) -> dict:
    backup_retention, _source = get_effective("backup_retention")

    drive_deleted: list[str] = []
    # Stage reale dell'operazione Drive in corso (stessi nomi di drive.py: classify_drive_error
    # tratta il 404 come cartella mancante solo in "cleanup"/"write").
    stage = "config"
    try:
        # Ordine dei controlli (coerente con run_gdrive_probe): prima la SA, poi il
        # folder id. Con folder id vuoto nessun upload (fix G2, rettifica ADR-0031):
        # senza `parents` il file finirebbe nella radice del Drive della SA.
        # get_drive_service() e' dentro il try: una Service Account key presente
        # ma malformata/corrotta solleva un'eccezione da from_service_account_file()
        # (non solo "file assente" - quello ritorna None senza eccezione) e deve
        # restare best-effort come il resto del blocco Drive (ADR-0004/ADR-0018).
        # Costruisce solo il client, nessuna chiamata di rete.
        service = get_drive_service(settings.google_sa_key_path)
        if service is None:
            drive["outcome"] = "sa_missing"
            drive["error"] = "Service Account non montata: upload Drive skippato."
        elif not settings.gdrive_backup_folder_id:
            drive["outcome"] = "folder_id_missing"
            drive["error"] = outcome_message("folder_id_missing")
        else:
            stage = "write"
            upload_file(service, result.db_path, settings.gdrive_backup_folder_id)
            upload_file(service, result.xlsx_path, settings.gdrive_backup_folder_id)
            drive["uploaded"] = True
            stage = "cleanup"  # rotazione: list + delete, come la pulizia orfani del probe
            drive_deleted = apply_drive_retention(service, settings.gdrive_backup_folder_id, backup_retention)
    except Exception as exc:  # SA malformata/rete/permessi Drive: best-effort (ADR-0004/ADR-0018)
        if stage == "config" and isinstance(exc, (ValueError, KeyError, TypeError)):
            outcome, status = "sa_invalid", None  # come run_gdrive_probe: chiave non parsabile
        else:
            outcome, status, _reason = classify_drive_error(exc, stage)
        drive["outcome"] = outcome
        message = outcome_message(outcome)
        if drive["uploaded"]:
            # Upload riuscito, fallita solo la rotazione: il messaggio non deve contraddire "caricato".
            message = redact(_RETENTION_FAILURE_PREFIX + message)
        drive["error"] = message
        logger.warning(redact(
            f"Backup Drive fallito (non bloccante): stage={stage} {outcome} {type(exc).__name__} status={status}"
        ))

    local_deleted = apply_local_retention(settings.backup_dir, backup_retention)

    return {
        "db_path": result.db_path,
        "xlsx_path": result.xlsx_path,
        "row_count": result.row_count,
        "drive_uploaded": drive["uploaded"],
        "drive_error": drive["error"],
        "local_deleted": local_deleted,
        "drive_deleted": drive_deleted,
    }


@router.post("")
def backup_now():
    return run_backup()


@router.get("/last")
def last_backup():
    with _last_backup_lock:
        last = dict(_last_backup) if _last_backup is not None else None
    return {"last": last}


@router.post("/gdrive-test")
def gdrive_test():
    if not _probe_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Test di connessione già in corso.")
    try:
        result = run_gdrive_probe(settings.google_sa_key_path, settings.gdrive_backup_folder_id)
    finally:
        _probe_lock.release()
    return dataclasses.asdict(result)


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

    # Ordine obbligato ADR-0034 p.1: copia -> upgrade -> rebuild FTS -> refresh replica.
    # Quattro blocchi try/except distinti (p.5): un except condiviso darebbe lo stesso
    # messaggio a guasti con rimedio diverso. Tutti dentro un solo _restore_lock (p.6).
    with _restore_lock:
        try:
            restore_from_backup(engine, backup_db_path, settings.db_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            migrations_applied = upgrade_schema_to_head()
        except Exception as exc:  # file gia' sovrascritto: schema potenzialmente incoerente
            logger.error("Migration fallita dopo restore di %s: %s", filename, exc)
            raise HTTPException(
                status_code=500,
                detail=(
                    "Restore completato ma migration fallita: il DB potrebbe essere "
                    "incoerente. Ripetere il restore da un backup valido."
                ),
            ) from exc

        try:
            rebuild_fts_index(engine)
        except Exception as exc:  # schema integro, manca solo l'indice testuale
            logger.error("Rebuild indice FTS fallito dopo restore di %s: %s", filename, exc)
            raise HTTPException(
                status_code=500,
                detail=(
                    "Restore e migration OK, ma rebuild indice FTS fallito: la ricerca "
                    "testuale non funzionera'. Riavviare il backend per un rebuild automatico."
                ),
            ) from exc

        try:
            refresh_read_only_replica()
        except Exception as exc:  # replica Metabase: best-effort (ADR-0004)
            logger.warning("Replica read-only non aggiornata dopo restore (non bloccante): %s", exc)

    body: dict = {"restored_from": filename, "migrations_applied": migrations_applied}
    if migrations_applied > 0:
        body["schema_note"] = (
            f"{migrations_applied} migration(s) applied: alcune tabelle potrebbero essere "
            "vuote se il backup precede tali fasi."
        )
    return body
