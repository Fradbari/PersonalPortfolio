# F4 — Backup automatico: design spec

Data: 2026-07-14 · Fase: F4 · Riferimenti: ADR-0008, backup-agent.md, ARCHITECTURE.md §3 Fase 4

## Contesto

F3 (Metabase su replica read-only) completata e verificata. Prossima fase: backup
automatico — pulsante manuale sempre disponibile, job opzionale all'avvio
(`BACKUP_ON_STARTUP`), dump SQLite + export `.xlsx` leggibile verso locale e Google
Drive (Service Account), retention/rotazione, restore documentato e testato.

Variabili già scaffoldate in F0 (`.env.example`, `config.py`): `BACKUP_ON_STARTUP`,
`GOOGLE_SA_KEY_PATH`, `GDRIVE_BACKUP_FOLDER_ID`, `BACKUP_RETENTION`. Volume `/backups`
già montato in `docker-compose.yml`, già gitignored con `.gitkeep`.

## Decisioni (confermate dall'utente)

1. **Restore**: endpoint applicativo (`POST /backup/restore`) con conferma esplicita
   (`confirm: true`), non solo procedura manuale — operazione distruttiva sul DB live.
2. **Drive fallback**: best-effort, stesso pattern di `refresh_read_only_replica()`
   (ADR-0004). Il backup locale riesce sempre; un fallimento Drive (rete, permessi) è
   loggato e riportato nella risposta, ma non fa fallire l'intera richiesta.
3. **Service Account opzionale**: se `GOOGLE_SA_KEY_PATH` non esiste a runtime, l'app
   non si blocca — solo l'upload Drive viene skippato (log warning), coerente con
   deploy locale/single-dev (ADR-0009).
4. **Test automatici**: nuova suite pytest (`backend/tests/test_backup.py`), prima
   suite pytest committata nel repo (F1-F3 erano verificate manualmente via
   `TestClient` ad-hoc). Giustificato dalla natura distruttiva del restore su dati
   finanziari reali.

## Architettura

Nuovo modulo `backend/app/backup.py` (funzioni pure, testabili in isolamento) +
`backend/app/routers/backup.py` (endpoint HTTP, stesso stile di `routers/imports.py`).
**Nessuna modifica di schema DB** — nessuna Alembic revision necessaria per F4.

### Dump SQLite

`sqlite3.Connection.backup()` (online backup API) invece di `shutil.copy2`. Motivo
(da ricerca best practice): sicura con DB live in WAL, nessun bisogno del workaround
checkpoint di ADR-0017 (quello resta specifico e invariato per la replica Metabase —
non toccato da questo lavoro). Output: file `.db` plain, autonomo, apribile senza
side-file `-wal`/`-shm`.

### Export xlsx "in chiaro"

Un sheet flat, tutte le transazioni (expense + income), colonne leggibili (Data,
Importo, Valuta, Tipo, Categoria, Conto, Commento, Tag, Fonte), generato con
pandas/openpyxl (già in stack). Soddisfa N-NF3 (no vendor lock-in): i dati restano
apribili senza l'app.

### Naming

`portfolio_backup_YYYYMMDD_HHMMSS.db` + `.xlsx` con lo stesso timestamp, scritti in
`/backups`.

### Drive upload

`google-api-python-client` + `google-auth` (nuove dipendenze). Service account da
`settings.google_sa_key_path`, target `settings.gdrive_backup_folder_id`.
`MediaFileUpload(resumable=True)`. Comportamento di fallback come da decisione 2/3
sopra.

### Retention

`BACKUP_RETENTION` = N coppie `.db`+`.xlsx` mantenute. Rotazione cancella le più
vecchie sia in `/backups` locale sia su Drive, stesso criterio non-bloccante (un
fallimento nella cancellazione Drive non blocca la rotazione locale).

### Restore

`POST /backup/restore`, body `{filename, confirm: true}`. Richiede `confirm=true`
esplicito. Legge solo da `/backups` locale (Drive è ridondanza off-site, non sorgente
di restore — la retention locale copre lo stesso set di file). Procedura:
`engine.dispose()` → overwrite `data/portfolio.db` con il file di backup scelto →
rimozione side-file WAL residui del DB precedente → riapertura → `refresh_read_only_replica()`
per risincronizzare Metabase (ADR-0004).

### Startup job

Hook FastAPI (`lifespan`): se `settings.backup_on_startup` → esegue un backup
all'avvio, best-effort (log su fallimento, non blocca l'avvio dell'app).

## Endpoint

- `POST /backup` — dump + xlsx + locale + drive + retention ora. Risposta:
  path locali, esito drive (bool + eventuale errore), file rimossi da retention.
- `GET /backup` — lista backup locali disponibili (per scegliere cosa restorare).
- `POST /backup/restore` — vedi sopra.

## Test

`backend/tests/test_backup.py` (nuove dipendenze: `pytest`, `httpx` per
`fastapi.testclient.TestClient`). Scenario principale: seed transazioni → backup →
svuota/corrompi `transactions` → restore → verifica conteggi/somme tornano uguali al
pre-backup. Service Account assente nei test → percorso Drive skippato per
costruzione (nessun mock di rete necessario), coerente con la decisione 3.

## Documentazione da aggiornare a fine implementazione

- `docs/DECISIONS.md` — nuovo ADR-0018 (online backup API, Drive service account
  opzionale, retention, restore con conferma).
- `docs/SECURITY.md` — come condividere la cartella Drive con l'email della service
  account (passo umano, non codice).
- `docs/ARCHITECTURE.md` — checklist F4 verificata, riga stato avanzamento, riga
  "Fase corrente" → F5, prompt di ripresa sviluppo.
- `CLAUDE.md` — riga "Fase corrente" → F5.

## Fuori scope (YAGNI)

- Tabella `settings` in DB per toggle runtime del backup automatico: `BACKUP_ON_STARTUP`
  via env var è sufficiente finché non esiste una UI (F5) per modificarlo a runtime.
- Restore da Drive: la retention locale mantiene lo stesso set di file di Drive: non
  serve un percorso di download separato per il flusso normale.
- Cifratura del dump/xlsx: fuori scope, esposizione solo rete locale (ADR-0009).
