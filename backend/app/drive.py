"""Upload/retention Google Drive via Service Account (ADR-0008/ADR-0018).
Best-effort: nessuna Service Account montata -> get_drive_service ritorna None,
mai un'eccezione che blocchi il backup locale."""
from __future__ import annotations

import os

import httplib2
from google.oauth2 import service_account
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app.backup import BACKUP_PREFIX

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
DRIVE_TIMEOUT_SECONDS = 30


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
