# Backend

Backend FastAPI (Python 3.12): unico writer sul DB SQLite del Personal Portfolio.

## Struttura cartelle

```
app/
  main.py            entrypoint FastAPI, monta i router e il backup di avvio
  db.py               connessione e sessione SQLite (WAL mode)
  models.py            modelli SQLAlchemy
  config.py            settings (pydantic-settings)
  backup.py            orchestrazione backup (dump SQLite + export .xlsx)
  drive.py              integrazione Google Drive (OAuth utente, ADR-0035)
  routers/              endpoint FastAPI (accounts, ai, backup, categories, imports, insights, settings, transactions)
  services/              logica di dominio (es. insights.py)
  ai/                     provider AI (Gemini), tool registry read-only
  ingestion/               parser My Finance e master sheet, riconciliazione/dedup
alembic/                    migrazioni schema DB
tests/                       test pytest
Dockerfile
requirements.txt
requirements-dev.txt
```

## Comandi

Avvio locale (senza Docker):
```bash
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Migrazioni Alembic:
```bash
alembic upgrade head
alembic revision -m "descrizione"   # ogni schema change
```

Test:
```bash
pytest
```

## Regole non negoziabili

- **FastAPI unico writer** su SQLite; Metabase legge solo la replica (ADR-0004).
- **Nessuna modifica di schema senza `alembic revision`** (ADR-0003). Numero e `down_revision` si
  fissano **al merge**, non alla scrittura: `alembic heads` deve restituire **una sola** riga.
- **Hash dedup** solo su campi stabili, mai editabili (ADR-0005). Unica eccezione tracciata: il
  suffisso `#n` delle ripetizioni manuali volute (ADR-0028) — l'importer confronta sempre l'hash
  base, mai il suffisso.
- **Nessun secret o identificatore di risorsa privata in una risposta HTTP** (ADR-0027): whitelist
  esplicita su `/settings`, blacklist permanente per `AI_API_KEY`, `GOOGLE_OAUTH_TOKEN_PATH`,
  `GDRIVE_BACKUP_FOLDER_ID`. `GOOGLE_API_KEY` non esiste in questo progetto.
- **Nessun tool di scrittura esposto al modello AI** (ADR-0023/0032): la persistenza delle
  conversazioni è scritta dal router, mai da un tool.

## Roadmap F8-F14: stato

Pianificato il 2026-07-21 (spec
[../docs/superpowers/specs/2026-07-21-f8-f14-roadmap-design.md](../docs/superpowers/specs/2026-07-21-f8-f14-roadmap-design.md),
ADR-0026 → ADR-0034). F8-F9 e F11-F13 implementate; F10 e F14 (Blocco C) implementate e mergiate (`55e2b79`); T10 e review finale
chiusi e mergiati (`c18a86c`).

**Endpoint**

| Endpoint | Fase | Nota |
|---|---|---|
| `GET` / `PUT /settings` | F9 (fatto) | solo chiavi in whitelist; i secret escono come `{configured: bool}`, mai come valore |
| `POST /transactions` | F11 (fatto) | inserimento manuale: `source='manual'`, `import_batch_id=NULL` |
| `GET /backup/last` | F10 (fatto) | ultimo esito backup in memoria, messaggi sanitizzati |
| `POST /backup/gdrive-test` | F10 (fatto) | probe reale write→read→delete; credenziali lette da `config.py`, mai dal body né in risposta |
| `GET /ai/sessions`, `GET /ai/sessions/{id}` | F14 (fatto) | elenco e messaggi delle conversazioni |
| `DELETE /ai/sessions/{id}` | F14 (fatto) | una sola conversazione, senza conferma |
| `DELETE /ai/sessions` | F14 (fatto) | azzera tutto lo storico, `confirm: true` obbligatorio |

`GET /transactions` ha dal Blocco B (F12) i filtri `date_from`, `date_to`, `amount_min`, `amount_max`,
`q` (full-text) e `group_by`; `year_month` resta per compatibilità.

**Migrazioni** — `settings` key/value (F9, 0003) · indici `transactions` (F12, 0004) ·
`transactions_fts` FTS5 + 3 trigger (F12, 0005) · `chat_sessions` + `chat_messages` (F14,
0006 su 0005, head attuale). F10, F11 e F13 **non** producono revision.

**Requisito FTS5 (F12).** La migrazione della ricerca full-text richiede un SQLite compilato con
FTS5. Guardrail: (1) il `lifespan` rifiuta l'avvio con errore esplicito se l'SQLite in esecuzione
non ha `ENABLE_FTS5` in `PRAGMA compile_options` (ADR-0029 p.3); (2) gate arm64 eseguito prima del
merge del Blocco B (GO) — `docker buildx build --platform linux/arm64 --load`, poi nel container
emulato `PRAGMA compile_options` (deve contenere `ENABLE_FTS5`) + una `CREATE VIRTUAL TABLE ...
USING fts5(...)` di prova. **Non** usare `SELECT fts5_version()`: non è una funzione SQL reale,
dà un falso negativo. Se l'immagine arm64 non avesse FTS5, la migrazione fallirebbe al primo
`docker compose up` sul Raspberry rompendo il deploy, non solo la ricerca.
L'indice viene ricostruito (`'rebuild'`) **dopo `POST /backup/restore`** (ADR-0034) e **a ogni
avvio** del backend se la tabella esiste; se manca, `GET /transactions?q=` risponde 503.

## Approfondimenti

- Piano architetturale + stato avanzamento: [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)
- Decisioni (ADR): [../docs/DECISIONS.md](../docs/DECISIONS.md)
- Guida avvio: [../docs/GETTING_STARTED.md](../docs/GETTING_STARTED.md)
- Guida funzionale endpoint: [../docs/USER_GUIDE.md](../docs/USER_GUIDE.md)

## Stato fase corrente (2026-10-23)

F0-F6 + F-DEBT completate. **F7 ◐ parcheggiata in attesa hardware, non bloccante.**
Blocchi A (F8-F9) e B (F11-F13) chiusi e mergiati su `master` (B = `ab9c360`).
**Fase corrente: Blocco C chiuso, mergiato e pushato; ambiente resettato a `0006` vuoto**
(F10 backup GDrive + F14 storicità chat AI; `55e2b79` + T10/fix `c18a86c`; DB `0003` archiviato in
`data/archive/portfolio-0003-20261023.db`); `phase` `"14"`, 347 test
verdi, `alembic heads` = `0006`.
Dettagli: [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).
