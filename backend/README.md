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
  drive.py              integrazione Google Drive (Service Account)
  routers/              endpoint FastAPI (accounts, ai, backup, categories, imports, insights, transactions)
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
  esplicita su `/settings`, blacklist permanente per `AI_API_KEY`, `GOOGLE_SA_KEY_PATH`,
  `GDRIVE_BACKUP_FOLDER_ID`. `GOOGLE_API_KEY` non esiste in questo progetto.
- **Nessun tool di scrittura esposto al modello AI** (ADR-0023/0032): la persistenza delle
  conversazioni è scritta dal router, mai da un tool.

## In arrivo con F8-F14

Pianificato il 2026-07-21 (spec
[../docs/superpowers/specs/2026-07-21-f8-f14-roadmap-design.md](../docs/superpowers/specs/2026-07-21-f8-f14-roadmap-design.md),
ADR-0026 → ADR-0032). Nessuna riga ancora scritta.

**Endpoint nuovi**

| Endpoint | Fase | Nota |
|---|---|---|
| `GET` / `PUT /settings` | F9 | solo chiavi in whitelist; i secret escono come `{configured: bool}`, mai come valore |
| `POST /transactions` | F11 | oggi **non esiste**: le transazioni entrano solo da import. `source='manual'`, `import_batch_id=NULL` |
| `POST /backup/gdrive-test` | F10 | probe reale write→read→delete; credenziali lette da `config.py`, mai dal body né in risposta |
| `GET /ai/sessions`, `GET /ai/sessions/{id}` | F14 | elenco e messaggi delle conversazioni |
| `DELETE /ai/sessions/{id}` | F14 | una sola conversazione, senza conferma |
| `DELETE /ai/sessions` | F14 | azzera tutto lo storico, `confirm: true` obbligatorio |

`GET /transactions` guadagna in F12 i filtri `date_from`, `date_to`, `amount_min`, `amount_max`,
`q` (full-text) e `group_by`; `year_month` resta per compatibilità.

**Migrazioni previste** — `settings` key/value (F9) · `transactions_fts` FTS5 + 3 trigger (F12) ·
`chat_sessions` + `chat_messages` (F14). F11 e F13 **non** producono revision.

**Requisito FTS5 (F12).** La migrazione della ricerca full-text richiede un SQLite compilato con
FTS5. Due guardrail: un check fail-fast all'avvio con errore esplicito se manca, e un **gate
bloccante prima del merge** del Blocco B — `docker buildx build --platform linux/arm64 --load` e poi
`SELECT fts5_version();` nel container emulato. Se l'immagine arm64 non avesse FTS5, la migrazione
fallirebbe al primo `docker compose up` sul Raspberry rompendo il deploy, non solo la ricerca.
Inoltre: **dopo `POST /backup/restore` l'indice va ricostruito**, perché il restore sovrascrive il
file DB e l'indice descriverebbe dati che non esistono più.

## Approfondimenti

- Piano architetturale + stato avanzamento: [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)
- Decisioni (ADR): [../docs/DECISIONS.md](../docs/DECISIONS.md)
- Guida avvio: [../docs/GETTING_STARTED.md](../docs/GETTING_STARTED.md)
- Guida funzionale endpoint: [../docs/USER_GUIDE.md](../docs/USER_GUIDE.md)

## Stato fase corrente (2026-07-21)

F0-F6 + F-DEBT completate. **F7 ◐ parcheggiata in attesa hardware, non bloccante per F8+.**
**Fase corrente: Blocco A (F8 dark mode + F9 settings)** — nessun codice F8-F14 ancora scritto.
Dettagli: [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).
