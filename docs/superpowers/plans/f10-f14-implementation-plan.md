# Blocco C — F10 + F14 — piano implementativo

- **Status**: Approvato per l'esecuzione — 2026-10-14 (D7 e D8 confermate)
- **Spec di dettaglio**: `docs/superpowers/specs/2026-10-14-f10-f14-detail-spec.md`
- **Branch**: `f10-f14-drive-chat` (aperto da `master` `749d86c` = `origin/master`)
- **Esecuzione**: subagent-driven-development — un task di codice per subagent, review dopo
  ciascuno, **tre checkpoint umani** (CP1 · CP2 · CP3). Review finale whole-branch con subagent
  **Claude Opus 5.5**, dichiarato nel report.
- **Ledger**: `.superpowers/sdd/progress.md` · brief per task: `.superpowers/sdd/task-N-brief.md`

## Context

Terzo e ultimo blocco della roadmap F8-F14. A e B chiusi e mergiati (`master` = `749d86c`, 252 test
verdi, `alembic heads` = `0005`, gate arm64 GO). F7 ◐ parcheggiata, **non si tocca**.

La ricognizione del codice ha trovato quattro fatti che la roadmap non vedeva e che giustificano
alcuni criteri qui sotto:

| # | Fatto | Perché è pericoloso |
|---|---|---|
| **C1** | `POST /backup` restituisce `drive_error = str(exc)` | Il folder id esce **già oggi** in JSON e in UI (regola 7). Spec D7 |
| **C2** | Nessuna configurazione di logging applicativo | Un `logger.info` passa i test con `caplog` e non compare mai nei `docker logs`. Spec D4 |
| **C3** | `history[-2*n:]` con `n = 0` restituisce **tutta** la lista | Il cap "zero memoria" diventerebbe "memoria illimitata", in silenzio. Spec D11 |
| **C4** | `Turn` deprecato nell'SDK; `previous_interaction_id` è stato lato Google | History come Step non deprecati, mai stato server fra domande diverse. Spec D10 |

## Ordine e checkpoint

```
T1 ADR rettifiche + ledger
T2 probe Drive (core)  →  T3 endpoint gdrive-test + redazione POST /backup
T4 schema 0006 + restore pre-0006
T5 ROSSO: fake registrante + test (a)/(b)
T6 VERDE: firma + adapter + router lettura   (rosso→verde in 4 tempi nel ledger)
T7 router scrittura + endpoint sessioni + guardrail registry
                                   →  [CP1: contratti F10 + F14]
                                   →  [CP2: dal vivo, DB scratch + Drive reale + Gemini reale]
T8 UI F10 su /backup-restore  →  T9 UI F14 su /assistente-ai (+ campo in /impostazioni)
                                   →  [CP3: visivo chat + backup, light e dark]
T10 chiusura blocco  →  review finale whole-branch (Opus 5.5)  →  merge
```

F10 (T2-T3) e F14 (T4-T7) sono indipendenti, ma si eseguono **in sequenza**: un subagent alla volta.
CP2 sta **prima** della UI di proposito: il rischio "quota della Service Account" (spec §4) e
l'accettazione degli step `model_output` da parte di Gemini (spec D10) si scoprono senza aver
ancora scritto una riga di frontend che li dia per scontati.

Comando test (venv del progetto): `backend/.venv/Scripts/python.exe -m pytest` dalla cwd `backend/`.

---

## T1 — ADR rettifiche + ledger

**Agente**: main. **File**: `docs/DECISIONS.md`, `.superpowers/sdd/progress.md`. **Zero codice.**

- **Rettifica ADR-0031**: contratto a 11 esiti e `stage` (spec §4); 200 per ogni esito
  diagnostico, 409 su probe concorrente; riuso di `upload_file`/`delete_file`; `google_reason` =
  token dal primo dict di `error_details`, mai `HttpError.reason` (che è il messaggio umano e
  contiene l'id); `redact()` sulle tre chiavi di `BLACKLIST`, valori vuoti saltati; **estensione
  della redazione a `POST /backup`** (D7, solo se confermata).
- **Rettifica ADR-0032**: `ChatTurn` e formato Step (D10); `n <= 0` = nessuna history (D11);
  persistenza solo su successo, coppia atomica, 404 su `session_id` ignoto (D6); interpretazione
  dell'ordine p.3 in lettura/scrittura (D9); colonna `truncated` (D8, solo se confermata); xlsx
  senza chat e chat nella replica Metabase (D2).
- Ledger: intestazione, checkpoint, tabella task.

**Criterio**: `git diff --name-only` = solo i due file. Grep `^## ADR-` invariato (nessun ADR nuovo).

---

## T2 — Probe Drive: core

**Agente**: backup-agent. **File**: `backend/app/drive.py`, `backend/tests/test_gdrive_probe.py`.

`redact(text) -> str`, `classify_drive_error(exc, stage) -> (outcome, google_status,
google_reason)`, `run_gdrive_probe(sa_key_path, folder_id) -> ProbeResult` con la sequenza
config → cleanup → write → read → delete di spec §4. Il servizio Drive si costruisce con
`get_drive_service` **esistente**; la scrittura passa da `upload_file`, la cancellazione da
`delete_file`. Prefisso `PROBE_PREFIX = "portfolio_gdrive_probe_"`, distinto da `BACKUP_PREFIX`.

**Test obbligatori** (fake Drive service come in `test_drive.py`; unico mock ammesso, ADR-0018 p.7):

1. Un test per **ogni** esito della tabella di spec §4, compreso `ok`.
2. Gli `HttpError` sono **istanze reali** di `googleapiclient.errors.HttpError` costruite con
   `httplib2.Response({"status": …})`, `content` JSON con la sentinella del folder id dentro
   `message`, e `uri` con la sentinella: un fake che non contenesse l'id renderebbe il test (c)
   inutile.
3. `redact`: sostituzione letterale, più valori, valori sovrapposti (ordine per lunghezza), **valore
   vuoto non altera il testo** (`"abc".replace("", "X")` = `"XaXbXcX"`).
4. `folder_id_missing` → **zero** chiamate al fake (nessuna scrittura nella root della SA).
5. Orfani: due file con `PROBE_PREFIX` e uno con `BACKUP_PREFIX` → cancellati **solo** i primi due.
6. Read che fallisce dopo write riuscito → delete tentato comunque, esito del read, non del delete.
7. Contenuto riletto diverso → `unexpected`, stage `read`.

**Criterio**: suite verde, nessun file fuori dai due dichiarati.

---

## T3 — `POST /backup/gdrive-test` + redazione di `POST /backup`

**Agente**: backup-agent. **File**: `backend/app/routers/backup.py`,
`backend/tests/test_backup_router.py`.

Endpoint senza parametri, `threading.Lock` di modulo acquisito con `blocking=False` → 409 se
occupato. Credenziali solo da `settings`. **D7 (se confermata)**: in `run_backup()`,
`drive_error` diventa il `message` dell'esito classificato e il `logger.warning` passa da
`redact()`; la forma del body di `POST /backup` non cambia.

**Test obbligatori:**

1. **Test (c) ADR-0031**: sentinelle in `settings.gdrive_backup_folder_id` e
   `settings.google_sa_key_path`; per ogni esito producibile via monkeypatch del probe/servizio,
   nessuna sentinella in `resp.text`.
2. Body `{"folder_id": "<altra sentinella>", "sa_key_path": "…"}` → ignorato, sentinella assente.
3. Probe in corso (lock già acquisito nel test) → **409**.
4. **D7**: `POST /backup` con upload che solleva un `HttpError` 404 reale contenente la sentinella →
   200, `drive_error` non vuoto e **senza** sentinella. Oggi questo test fallirebbe: annotarlo nel
   report come rosso iniziale.
5. `test_spa_routing.py` invariato e verde (nessuna route SPA nuova).

---

## T4 — Schema F14: revision `0006` + restore pre-0006

**Agente**: schema-agent. **File**: `backend/app/models.py`,
`backend/alembic/versions/0006_chat_sessions_messages.py`, `backend/tests/test_chat_schema.py`,
`backend/tests/test_backup_router.py`.

Modelli `ChatSession`/`ChatMessage` e revision secondo spec §5 (`truncated` solo se D8 confermata).
`down_revision = "0005"`. Solo `op.create_table`/`op.create_index` — **nessun
`batch_alter_table`**.

**Criteri:**

1. Round-trip sulla fixture `fts_engine` (Strategia A di `conftest.py`): head → `downgrade 0005` →
   le due tabelle non esistono → `upgrade head` → esistono; **3 trigger FTS** presenti dopo ogni
   passo; `'integrity-check'` FTS ok.
2. CHECK su `role` rifiuta un valore diverso da `user`/`assistant`.
3. `test_restore_runs_migrations_and_reports_applied`: `== 3` → `== 4`. Unica modifica a un test
   esistente, dichiarata (il commento del test la prevede).
4. **Test nuovo (spec D3)**: backup migrato a `0005` con una transazione → restore → 200,
   `migrations_applied >= 1`, `schema_note` presente, `version_num` sul file di `settings.db_path`
   = head, `chat_sessions` e `chat_messages` con `COUNT(*) = 0`, transazione intatta.
5. `test_fts_triggers.py` **non toccato**. `alembic heads` = 1 riga.
6. `data/portfolio.db` intatto dopo il run.

---

## T5 — ROSSO: fake registrante + test (a) e (b)

**Agente**: ai-agent. **File**: **solo test** — nuovo `backend/tests/test_ai_history.py`.
**Nessun file in `backend/app/` toccato** (criterio verificato con `git diff --name-only`).

- `_RecordingProvider(AIProvider)` con `answer(self, question, session, history=None)` che registra
  `calls`, `history` e `history_len` (`None` se `history is None`). La firma accetta già `history`
  così il rosso è un'`AssertionError`, non un `TypeError` sulla chiamata del router.
- **Test (a) — il router passa la conversazione completa**: sessione seminata via ORM con
  **K = 9 coppie** (> default 6), `POST /ai/query {"question", "session_id"}` → asserisce
  `history_len == 18`, contenuti e ruoli nell'ordine seminato. Deve fallire oggi perché
  `QueryRequest` ignora `session_id` e il router chiama `answer(question, session)`.
- **Test (b) — l'adapter tronca prima della chiamata**: `GeminiProvider` con `_FakeClient`, cap a 6
  (via sessione di test con riga `settings`), `answer(q, session, history=<18 turni>)` → il primo
  `create` riceve `input` con **12 step di history + 1 step della domanda**, gli ultimi 12 in ordine.
  Oggi fallisce con `TypeError: answer() got an unexpected keyword argument 'history'`.

**Evidenza nel ledger (tempo 1)**: output pytest dei due test, copiato. Il rosso di (a) deve essere
un'`AssertionError` su `history_len`; quello di (b) un `TypeError` sull'argomento `history`.
Qualunque altro rosso (import, fixture) = test da correggere, non rosso valido.

---

## T6 — VERDE: firma + adapter + router (percorso di lettura)

**Agente**: ai-agent. **File**: `backend/app/ai/provider.py`, `backend/app/ai/providers/gemini.py`,
`backend/app/routers/ai.py`, `backend/tests/test_ai_router.py`, `backend/tests/test_ai_provider.py`.

Sequenza **obbligata**, un commit per tempo, output pytest nel ledger a ogni tempo:

- **Tempo 2** — firma su `AIProvider` (`ChatTurn`, `history: list[ChatTurn] | None = None`) e su
  `GeminiProvider`, che per ora **inoltra tutta** la history come step, senza cap. I 7 fake
  esistenti aggiornati alla nuova firma (modifica meccanica, dichiarata). Atteso: (b) **ancora
  rosso**, ora `AssertionError` (18 step invece di 12) — è la prova che (b) misura il troncamento e
  non la firma. (a) ancora rosso.
- **Tempo 3** — cap nell'adapter (spec D11: `n <= 0` → nessuna history con ramo esplicito; cap letto
  solo se history non vuota). Atteso: (b) **verde**, (a) ancora rosso.
- **Tempo 4** — router, percorso di lettura: `session_id` opzionale in `QueryRequest`, 404 se
  inesistente **prima** del provider, caricamento dei messaggi `(created_at, id)`, chiamata
  `provider.answer(question, session, history=…)` per keyword (`[]` senza `session_id`). Atteso:
  (a) **verde**, suite intera verde.

**Test aggiuntivi**: `n = 0` e `n = -1` → `input` è la stringa della domanda; history vuota →
`input` identico a oggi (i test adapter esistenti passano **senza modifiche** di asserzione);
nessuna chiamata contiene `previous_interaction_id` al primo `create` anche con history; 404 su
`session_id` inesistente con `calls == 0` sul fake.

**Vincolo**: nessuna persistenza in questo task — `POST /ai/query` non scrive ancora nulla.

---

## T7 — Router: percorso di scrittura + endpoint sessioni + guardrail

**Agente**: ai-agent. **File**: `backend/app/routers/ai.py`, `backend/tests/test_ai_sessions.py`,
`backend/tests/test_ai_tools.py`.

Contratto di spec §5 alla lettera: persistenza su 200 in una transazione, `session_id` in risposta,
`GET /ai/sessions`, `GET /ai/sessions/{id}`, `DELETE /ai/sessions/{id}`, `DELETE /ai/sessions` con
`confirm`. Cancellazioni esplicite (messaggi, poi sessione).

**Test obbligatori:**

1. Prima domanda senza `session_id` → sessione creata, 2 messaggi, titolo troncato a 80.
2. Seconda domanda con `session_id` → stessa sessione, 4 messaggi, `updated_at` avanzato, il fake
   riceve la history di 2 messaggi.
3. Provider 400 e 502 → `COUNT(*)` di entrambe le tabelle **invariato**.
4. `tools_json`: `NULL` per `user`; per `assistant` `json.loads` == `tools_used` della risposta
   (stesso shape, ADR-0032 p.2); `"[]"` senza tool.
5. `DELETE` singola → 204, zero messaggi orfani, le altre sessioni intatte; 404 su id assente.
6. `DELETE /ai/sessions`: senza body → 400; `{"confirm": false}` → 400; `{"confirm": true}` → 200
   con i conteggi, tabelle vuote.
7. **Guardrail M14.5** in `test_ai_tools.py`: `set(TOOLS)` = i 4 tool attuali; sorgente di
   `ai/tools.py` senza `ChatSession`/`ChatMessage`/`chat_`; `test_tools_never_mutate_the_database`
   esteso alle due tabelle chat.
8. `COUNT(*)` su `transactions` invariato dopo una sequenza di query.

### ▸ CHECKPOINT UMANO 1 — contratti F10 + F14

Congela le forme di spec §4 e §5. Verifica: OpenAPI generato (`/openapi.json`) per i 6 endpoint;
risposte reali via `TestClient` con fake provider e fake Drive, copiate nel ledger per: un esito
`ok`, un `folder_not_found`, un `sa_missing`, il 409; una query nuova, una di follow-up, un 404 di
sessione, le due `DELETE`. `alembic heads` = 1 riga; suite verde. Decisioni D7/D8 riconfermate sul
codice reale.

### ▸ CHECKPOINT UMANO 2 — dal vivo (DB scratch, Drive reale, Gemini reale)

**Solo DB scratch**: copia di `data/portfolio.db` via online backup API in una directory temporanea,
`alembic upgrade head` sulla copia, `uvicorn` su porta dedicata con `DB_PATH="$SCRATCH"` come
prefisso inline (mai `export`, mai `data/portfolio.db`). Egress reale verso Gemini sui dati della
copia, come nell'E2E di F6.

- **F10**, con la SA reale dell'utente: (1) cartella condivisa → `ok`, poi una `list` sul prefisso
  probe → **zero residui**; (2) `GDRIVE_BACKUP_FOLDER_ID` fasullo (prefisso inline) → esito che
  nomina la causa, `grep` del valore fasullo su risposta e log del processo → **0 occorrenze**;
  (3) cartella reale non condivisa (passo dell'utente) → idem; (4) SA non montata → `sa_missing`.
  Se (1) dà `quota_exceeded/storageQuotaExceeded` → **stop**: spec §4, decisione utente.
- **F14**: domanda, poi follow-up "e il mese prima?" → risposta coerente col contesto (spec D10:
  se Gemini rifiuta gli step `model_output` → **stop**); riavvio del processo → `GET
  /ai/sessions/{id}` restituisce la conversazione; `DELETE /ai/sessions` con `confirm` → tabelle
  vuote; `COUNT(*)` su `transactions` identico a inizio sessione.
- **Restore**: backup scratch a `0005` → restore → chat vuote, 200, nessun errore nel log.

Copia scratch cancellata a fine CP2; evidenze nel ledger.

---

## T7b — Ultimo esito backup + folder id vuoto nel backup (aggiunto a CP2, 2026-10-19)

**Agente**: backup-agent. **File**: `backend/app/routers/backup.py`, `backend/app/main.py`,
`backend/tests/test_backup_last.py`. Rettifica ADR-0031 (2026-10-19), nessuna revision.

`run_backup(trigger)` registra l'ultimo esito in memoria (lock) su successo ed errore;
`GET /backup/last` → `{"last": {...} | null}`; folder id vuoto → nessun upload,
`folder_id_missing` (G2); log del thread di avvio via `redact()`.

**Criteri**: esito `startup` e `manual` registrati; `null` al boot senza backup; sentinella del
folder id assente da risposte e log; 8 backup concorrenti → stato coerente; G2 con test dedicato;
suite verde, `alembic heads` = `0006`.

---

## T8 — UI F10 su `/backup-restore`

**Agente**: react-ui-agent. **File**: `frontend/src/pages/Backup.tsx`.

Spec §6. `useMutation` sul click, mai al mount. Tipi TypeScript dell'esito dal contratto di CP1.
Banner "Ultimo backup" da `useQuery` su `GET /backup/last` (T7b): `null` → "Nessun backup in
questa sessione" (non un errore); Drive fallito → avviso con il `message`.

**Criteri**: grep su `Backup.tsx` di `useQuery(` con `gdrive` → 0; ricaricare la pagina non
produce alcuna richiesta a `/backup/gdrive-test` (verificato nel pannello Network); `tsc` e build
puliti; `SPA_ROUTES`/`App.tsx` invariati.

---

## T9 — UI F14 su `/assistente-ai` + `ai_history_max_turns` in `/impostazioni`

**Agente**: react-ui-agent. **File**: `frontend/src/pages/AiAssistant.tsx`,
`frontend/src/lib/api.ts` (solo `api.delete(path, body?)`), `frontend/src/pages/Settings.tsx`
(solo D11).

Spec §6. Sessione nell'URL con `useSearchParams` e nella `queryKey`. "Azzera storico" con
`AlertDialog` a 2 step che invia `{"confirm": true}`.

**Criteri:**

- `curl -H 'Accept: text/html' 'http://localhost:5173/assistente-ai?sessione=1'` → SPA, mentre
  `/ai/sessions` raggiunge il backend; output nel ledger.
- Il catch del 404 usa `ApiError.status`, non il testo del messaggio.
- Traccia tool visibile per **ogni** messaggio `assistant`, anche dopo reload.
- In `api.ts` cambia solo `delete`; il ramo d'errore di rete resta com'è (debito B, fuori scope).
- `/impostazioni`: `ai_history_max_turns` rifiuta -1 con messaggio visibile, accetta 0.
- `tsc` e build puliti, nessuna classe colore hardcoded (token semantici di F8).

### ▸ CHECKPOINT UMANO 3 — giudizio visivo

Sul **container di produzione** ricostruito, DB scratch: `/assistente-ai` e `/backup-restore` in
**light e dark** — elenco sessioni, conversazione ripresa, traccia tool, avviso troncamento, dialog
"Azzera storico", esito del test Drive verde e rosso. Console pulita. Ultimo punto in cui la UI si
modifica a basso costo.

---

## T10 — Chiusura blocco

**Agente**: main. **File**: `backend/app/main.py`, `backend/tests/test_health_version.py`,
`CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, `docs/USER_GUIDE.md`.

- `phase` → `"14"`, `version` → `0.1.0-phase14`, test aggiornato con la convenzione già scritta
  nel commento di B (C chiude F10 **e** F14 → `"14"`).
- `SECURITY.md`: chat nei backup e non rimosse da "Azzera storico" finché la retention non li ruota;
  chat nella replica Metabase; tabella esiti F10 → rimedio, con `quota_exceeded`; `POST /backup`
  ora sanitizzato (D7).
- `ARCHITECTURE.md`: stato F10/F14, debito nuovo "logging applicativo non configurato, INFO
  invisibile" (D4), prompt di ripresa.
- `alembic heads` = 1 riga; `upgrade head` e `downgrade` fino a `0002` su DB scratch; 3 trigger.
- **Gate arm64 sull'immagine finale**: `docker buildx build --platform linux/arm64 --load`, nel
  container `PRAGMA compile_options` con `ENABLE_FTS5` + `CREATE VIRTUAL TABLE … USING fts5` di
  prova; alembic `0001 → 0006` su DB vuoto scratch; polling su `/health` fino a `phase:"14"`;
  `0.1.0-phase14` in `/openapi.json`. `MSYS_NO_PATHCONV=1` su ogni `docker run -e VAR=/path`.
  **Mai** `SELECT fts5_version()`.
- Dopo `git add -A`: `git grep -i patrimon` = 0; `git grep -E "GOOGLE_API_KEY|GEMINI_API_KEY"` solo
  nelle righe di documentazione che ne vietano l'uso.
- Suite completa verde.

### Review finale whole-branch

Subagent **Claude Opus 5.5** su `git diff master...HEAD`. Prescrizioni: regola 7 (nessun folder id/
path SA/chiave in risposta, messaggi, log); registry ancora read-only; `previous_interaction_id`
mai fra domande; nessun `batch_alter_table`; il rosso→verde nel ledger corrisponde ai commit. Esito
e modello dichiarati nel report.
