#!/usr/bin/env python3
"""Setup una tantum delle credenziali OAuth utente per il backup su Google Drive (ADR-0035).

Da eseguire SUL PROPRIO PC (non nel container): apre il browser per il consenso, salva un file
di credenziali "authorized user" (con refresh token) e, a richiesta, crea la cartella di
destinazione dei backup stampandone l'id.

Tutto arriva dagli argomenti: lo script non legge variabili d'ambiente o file di configurazione
e non ha path di default. Non stampa mai token, secret o path completi.
"""

import argparse
import os
import sys

# Scope minimo (ADR-0035 p.2): l'app vede solo i file che crea.
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


def build_flow(client_secrets_path, scopes):
    """Costruisce il flow OAuth loopback (PKCE attivo). Import lazy: la libreria e' solo host."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    return InstalledAppFlow.from_client_secrets_file(client_secrets_path, scopes=scopes)


def build_drive_service(creds):
    """Client Drive v3 con le credenziali appena ottenute. Import lazy."""
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _parser():
    parser = argparse.ArgumentParser(
        prog="gdrive_oauth_setup.py",
        description=(
            "Ottiene le credenziali OAuth utente (scope drive.file) per il backup su Drive "
            "e le salva in un file da montare nel container in sola lettura."
        ),
        epilog=(
            "Il file di --out viene creato con permessi 0600. Su Windows i permessi POSIX sono "
            "solo indicativi: proteggere il file con le ACL della cartella."
        ),
    )
    parser.add_argument(
        "--client-secrets",
        required=True,
        metavar="PATH",
        help="JSON del client OAuth di tipo 'Desktop app' scaricato dalla console Google.",
    )
    parser.add_argument(
        "--out",
        required=True,
        metavar="PATH",
        help="File di credenziali da generare (contiene il refresh token).",
    )
    parser.add_argument(
        "--create-folder",
        metavar="NOME",
        help="Crea nel My Drive una cartella con questo nome e ne stampa l'id.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Consente di sovrascrivere --out se esiste gia' (senza, il comando rifiuta).",
    )
    return parser


def _error(message):
    print(f"Errore: {message}", file=sys.stderr)
    return 1


def _write_credentials(out_path, content, force):
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if force else os.O_EXCL)
    fd = os.open(out_path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)


def _create_folder(creds, name):
    service = build_drive_service(creds)
    folder = (
        service.files()
        .create(body={"name": name, "mimeType": FOLDER_MIME_TYPE}, fields="id")
        .execute()
    )
    return folder["id"]


def main(argv=None):
    args = _parser().parse_args(argv)

    # Rifiuto prima del consenso: niente browser inutile se il file esiste.
    if os.path.exists(args.out) and not args.force:
        return _error(
            "il file di output esiste gia': usare --force per sovrascriverlo "
            "oppure scegliere un altro --out."
        )

    try:
        flow = build_flow(args.client_secrets, DRIVE_SCOPES)
        creds = flow.run_local_server(
            host="127.0.0.1", port=0, access_type="offline", prompt="consent"
        )
    except Exception as exc:  # dettagli omessi di proposito: potrebbero contenere path o secret
        return _error(f"autorizzazione non riuscita ({type(exc).__name__}).")

    if not creds.refresh_token:
        return _error(
            "Google non ha restituito un refresh token: nessun file scritto. "
            "Revocare l'accesso dell'app dall'account Google e rieseguire lo script."
        )

    try:
        _write_credentials(args.out, creds.to_json(), args.force)
    except FileExistsError:
        return _error("il file di output esiste gia': usare --force per sovrascriverlo.")
    except OSError as exc:
        return _error(f"scrittura del file di output non riuscita ({type(exc).__name__}).")

    print(f"Credenziali salvate in '{os.path.basename(args.out)}'.")

    if args.create_folder:
        try:
            folder_id = _create_folder(creds, args.create_folder)
        except Exception as exc:
            return _error(
                f"creazione cartella non riuscita ({type(exc).__name__}); "
                "le credenziali sono state salvate comunque."
            )
        print(f"Cartella creata. ID: {folder_id}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
