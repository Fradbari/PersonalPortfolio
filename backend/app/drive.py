"""Upload/retention Google Drive via Service Account (ADR-0008/ADR-0018).
Best-effort: nessuna Service Account montata -> get_drive_service ritorna None,
mai un'eccezione che blocchi il backup locale."""
from __future__ import annotations

import logging
import os
import shutil
import socket
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime

import httplib2
from google.auth.exceptions import RefreshError
from google.oauth2 import service_account
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from app.backup import BACKUP_PREFIX
from app.config import settings

logger = logging.getLogger(__name__)

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
DRIVE_TIMEOUT_SECONDS = 30
PROBE_PREFIX = "portfolio_gdrive_probe_"
_QUOTA_REASONS = {"storageQuotaExceeded", "quotaExceeded", "rateLimitExceeded", "userRateLimitExceeded"}
_SECURITY_REF = "Vedi docs/SECURITY.md, sezione «Backup su Google Drive»."
_MESSAGES = {
    "ok": "Connessione riuscita: scrittura, lettura e cancellazione sulla cartella Drive configurata.",
    "sa_missing": "Service Account non montata: verifica GOOGLE_SA_KEY_PATH e il file montato. " + _SECURITY_REF,
    "sa_invalid": "Il file della Service Account non è una chiave valida: rigenera la chiave JSON. " + _SECURITY_REF,
    "folder_id_missing": "GDRIVE_BACKUP_FOLDER_ID non configurato: nessuna scrittura eseguita. " + _SECURITY_REF,
    "sa_auth_failed": "Autenticazione della Service Account rifiutata: chiave revocata o disabilitata, generane una nuova. " + _SECURITY_REF,
    "folder_not_found": "Cartella non trovata o non condivisa con la Service Account. " + _SECURITY_REF,
    "permission_denied": "Permesso insufficiente: condividi la cartella con la Service Account come Editor. " + _SECURITY_REF,
    "quota_exceeded": (
        "Quota esaurita o Service Account senza quota di storage propria: i file creati da una SA in un "
        "Drive personale vengono rifiutati. Rimedio: Shared Drive (Google Workspace) oppure OAuth utente. "
        + _SECURITY_REF
    ),
    "timeout": "Timeout nella comunicazione con Google Drive: riprova. " + _SECURITY_REF,
    "network_error": "Errore di rete verso Google Drive: controlla la connessione. " + _SECURITY_REF,
    "unexpected": "Errore imprevisto durante il test su Google Drive. " + _SECURITY_REF,
}


@dataclass
class ProbeResult:
    ok: bool
    outcome: str
    stage: str | None
    message: str
    google_status: int | None
    google_reason: str | None
    probe_written: bool
    probe_deleted: bool
    orphans_removed: int
    elapsed_ms: int


class _ContentMismatch(Exception):
    pass


def redact(text: str) -> str:
    """Sostituzione letterale dei valori sensibili noti (ADR-0031 p.3); i valori vuoti si saltano."""
    secrets = {
        "gdrive_backup_folder_id": settings.gdrive_backup_folder_id,
        "google_sa_key_path": settings.google_sa_key_path,
        "ai_api_key": settings.ai_api_key,
    }
    for name, value in sorted(secrets.items(), key=lambda kv: len(kv[1] or ""), reverse=True):
        if value:
            text = text.replace(value, f"<{name}>")
    return text


def classify_drive_error(exc: Exception, stage: str) -> tuple[str, int | None, str | None]:
    """(outcome, google_status, google_reason) da tipo e campi strutturati, mai dal testo."""
    if isinstance(exc, HttpError):
        status = int(exc.resp.status)
        reason = None
        details = getattr(exc, "error_details", None)
        if isinstance(details, list) and details and isinstance(details[0], dict):
            raw = details[0].get("reason")
            reason = redact(raw) if isinstance(raw, str) else None
        if status == 404 and stage in ("cleanup", "write"):
            return "folder_not_found", status, reason
        if status == 401:
            return "sa_auth_failed", status, reason
        if status in (403, 429) and reason in _QUOTA_REASONS:
            return "quota_exceeded", status, reason
        if status == 403:
            return "permission_denied", status, reason
        return "unexpected", status, reason
    if isinstance(exc, RefreshError):
        return "sa_auth_failed", None, None
    if isinstance(exc, TimeoutError):
        return "timeout", None, None
    if isinstance(exc, (httplib2.ServerNotFoundError, ConnectionError, socket.gaierror)):
        return "network_error", None, None
    return "unexpected", None, None


def outcome_message(outcome: str) -> str:
    return redact(_MESSAGES[outcome])


def _log_failure(stage: str, exc: Exception, status: int | None, reason: str | None) -> None:
    logger.warning(redact(f"Probe Drive fallito in {stage}: {type(exc).__name__} status={status} reason={reason}"))


def run_gdrive_probe(sa_key_path: str, folder_id: str) -> ProbeResult:
    started = time.monotonic()
    state = {"written": False, "deleted": False, "orphans": 0}

    def result(outcome, stage=None, status=None, reason=None) -> ProbeResult:
        return ProbeResult(
            ok=outcome == "ok",
            outcome=outcome,
            stage=stage,
            message=redact(_MESSAGES[outcome]),
            google_status=status,
            google_reason=reason,
            probe_written=state["written"],
            probe_deleted=state["deleted"],
            orphans_removed=state["orphans"],
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    if not sa_key_path or not os.path.exists(sa_key_path):
        return result("sa_missing", "config")
    try:
        service = get_drive_service(sa_key_path)
    except (ValueError, KeyError, TypeError):
        return result("sa_invalid", "config")
    except Exception as exc:
        _log_failure("config", exc, None, None)
        return result("unexpected", "config")
    if service is None:
        return result("sa_missing", "config")
    if not folder_id:
        return result("folder_id_missing", "config")

    stage = "cleanup"
    error: tuple[str, str, int | None, str | None] | None = None
    file_id: str | None = None
    try:
        safe_folder = folder_id.replace("'", "\\'")
        query = f"name contains '{PROBE_PREFIX}' and '{safe_folder}' in parents"
        orphans = service.files().list(q=query, fields="files(id, name)").execute().get("files", [])
        for orphan in orphans:
            if orphan["name"].startswith(PROBE_PREFIX):
                delete_file(service, orphan["id"])
                state["orphans"] += 1

        stage = "write"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        payload = f"portfolio gdrive probe {stamp}".encode()
        tmp = tempfile.mkdtemp()
        try:
            local_path = os.path.join(tmp, f"{PROBE_PREFIX}{stamp}.probe")
            with open(local_path, "wb") as fh:
                fh.write(payload)
            file_id = upload_file(service, local_path, folder_id)
        finally:
            # ignore_errors: su Windows MediaFileUpload puo' tenere aperto il file dopo un errore
            shutil.rmtree(tmp, ignore_errors=True)
        state["written"] = True

        stage = "read"
        downloaded = service.files().get_media(fileId=file_id).execute()
        if downloaded != payload:
            raise _ContentMismatch()
    except Exception as exc:
        outcome, status, reason = classify_drive_error(exc, stage)
        _log_failure(stage, exc, status, reason)
        error = (outcome, stage, status, reason)
    finally:
        if file_id is not None:
            try:
                delete_file(service, file_id)
                state["deleted"] = True
            except Exception as exc:
                outcome, status, reason = classify_drive_error(exc, "delete")
                _log_failure("delete", exc, status, reason)
                if error is None:
                    error = (outcome, "delete", status, reason)

    if error is not None:
        return result(*error)
    return result("ok")


def get_drive_service(sa_key_path: str):
    """None se la Service Account non e' montata a runtime (degradazione graceful,
    ADR-0018 punto 3)."""
    if not sa_key_path or not os.path.exists(sa_key_path):
        return None
    credentials = service_account.Credentials.from_service_account_file(sa_key_path, scopes=DRIVE_SCOPES)
    authorized_http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=DRIVE_TIMEOUT_SECONDS))
    return build("drive", "v3", http=authorized_http, cache_discovery=False)


def upload_file(service, file_path: str, folder_id: str) -> str:
    """Ritorna l'id del file caricato su Drive."""
    metadata: dict = {"name": os.path.basename(file_path)}
    if folder_id:
        metadata["parents"] = [folder_id]
    media = MediaFileUpload(file_path, resumable=True)
    uploaded = service.files().create(body=metadata, media_body=media, fields="id").execute()
    return uploaded["id"]


def list_backup_files(service, folder_id: str) -> list[dict]:
    """Lista {id, name} dei file di backup nella cartella Drive, piu' recenti (per nome) prima."""
    query = f"name contains '{BACKUP_PREFIX}'"
    if folder_id:
        query += f" and '{folder_id}' in parents"
    response = service.files().list(q=query, fields="files(id, name)", orderBy="name desc").execute()
    return response.get("files", [])


def delete_file(service, file_id: str) -> None:
    service.files().delete(fileId=file_id).execute()


def apply_drive_retention(service, folder_id: str, retention: int) -> list[str]:
    """Cancella su Drive le coppie piu' vecchie oltre le `retention` piu' recenti
    (stesso criterio di apply_local_retention, ADR-0018 punto 4)."""
    files = [f for f in list_backup_files(service, folder_id) if f["name"].startswith(BACKUP_PREFIX)]
    timestamps = sorted(
        {os.path.splitext(f["name"])[0][len(BACKUP_PREFIX):] for f in files}, reverse=True
    )
    stale_timestamps = set(timestamps[retention:])
    deleted: list[str] = []
    for f in files:
        ts = os.path.splitext(f["name"])[0][len(BACKUP_PREFIX):]
        if ts in stale_timestamps:
            delete_file(service, f["id"])
            deleted.append(f["name"])
    return deleted
