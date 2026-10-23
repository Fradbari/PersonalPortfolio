# Rimedio Drive — OAuth utente al posto della Service Account — piano implementativo

- **Status**: Approvato ed eseguito (T1-T8, CP1/CP2 superati) — 2026-10-23; merge in attesa di ok utente
- **ADR**: ADR-0035 in `docs/DECISIONS.md` (Proposed → Accepted in T7)
- **Branch**: `drive-oauth` (aperto da `master` `1571813`)
- **Esecuzione**: subagent-driven-development, un task di codice per subagent, review dopo
  ciascuno, **due checkpoint umani** (CP1 · CP2). Review finale whole-branch con subagent
  **Claude Opus 5.5**, dichiarata nel report.
- **Scelte confermate dall'utente (2026-10-23)**: cartella creata dall'app e spostata dall'utente ·
  rinomina esiti `sa_*` → `auth_*` · Service Account rimossa del tutto.

## Context

Il probe F10 (`POST /backup/gdrive-test`) dal container restituisce `quota_exceeded`, stage
`write`, 403 `storageQuotaExceeded`: una Service Account non ha quota e non può creare file in un
My Drive personale. Account `@gmail` → niente Shared Drive né domain-wide delegation. Rimedio:
OAuth utente con refresh token, scope `drive.file`, cartella creata dall'app (ADR-0035).

Fatti dal codice che determinano il perimetro:

| # | Fatto | Conseguenza |
|---|---|---|
| **K1** | `get_drive_service()` (`backend/app/drive.py`) è l'unico punto che costruisce credenziali | il cambio di credenziale è locale a una funzione; probe, backup e retention la riusano |
| **K2** | `POST /backup/restore` legge solo `settings.backup_dir` | il restore non tocca Drive: **nessuna modifica**, nessun test di restore da riscrivere |
| **K3** | `classify_drive_error()` mappa `RefreshError` non ritentabile e 401 su `sa_auth_failed` | va separato `invalid_grant` (token scaduto/revocato) da `invalid_client` (client rotto) |
| **K4** | `_is_secret_configured()` ha un caso speciale per `google_sa_key_path` (default non vuoto) | con default **vuoto** il nuovo path resta comunque su `os.path.exists` (vuoto → `False`) |
| **K5** | L'hook pre-commit non conosce `"refresh_token"` né `"client_secret"` | un file di token committato per errore oggi passerebbe |
| **K6** | `Backup.tsx` mostra `outcome` e `message` senza logica per-esito | la rinomina degli esiti non rompe la UI; cambiano solo i testi |

Fuori perimetro: schema DB (nessuna revision, `alembic heads` resta `0006`), restore, retention
(stessa logica, ora vede solo i file creati dall'app OAuth), F7.

## Ordine e checkpoint

```
T1 drive.py: credenziali OAuth + classificazione + messaggi
T2 config + router backup + .env.example + compose     (dipende da T1)
T3 blacklist settings                                    (dipende da T2: nome della chiave)
T4 script host gdrive_oauth_setup.py                     (indipendente)
T5 hook pre-commit                                       (indipendente)
                                  →  [CP1: contratto esiti + suite verde + rilettura script]
T6 UI: Settings.tsx + testi Backup.tsx
T7 documenti: SECURITY, README, agent, CLAUDE.md, ARCHITECTURE, ADR → Accepted
                                  →  [CP2: dal vivo, backup preventivo DB → Drive reale]
T8 review finale whole-branch (Opus 5.5) → fix → merge --no-ff (solo su ok utente)
```

## Esiti del probe dopo il cambio (contratto `ProbeResult` invariato nella forma)

| `outcome` | Stage | Trigger strutturato | Messaggio (rimedio) |
|---|---|---|---|
| `ok` | — | write→read→delete riusciti | invariato |
| `auth_missing` | `config` | `GOOGLE_OAUTH_TOKEN_PATH` vuoto o file assente | "Token OAuth non configurato: genera il token con lo script di setup e imposta `GOOGLE_OAUTH_TOKEN_PATH`." |
| `auth_invalid` | `config` / qualunque | `ValueError`/`KeyError`/`TypeError` dal caricamento; `RefreshError` non ritentabile con `error` ≠ `invalid_grant`; 403 reason `insufficientPermissions`/`ACCESS_TOKEN_SCOPE_INSUFFICIENT` | "File del token non valido o client OAuth non più valido: rigenera il token con lo script." |
| `folder_id_missing` | `config` | `GDRIVE_BACKUP_FOLDER_ID` vuoto | invariato |
| `auth_expired` | qualunque | `RefreshError` non ritentabile con `error = invalid_grant`; HTTP 401 | "Autorizzazione scaduta o revocata (revoca, sei mesi di inutilizzo o app rimasta in Testing): rigenera il token con lo script." |
| `folder_not_found` | `cleanup`/`write` | 404 | "Cartella non trovata: l'id è errato oppure la cartella non è stata creata dall'app (scope `drive.file`). Usa la cartella creata dallo script." |
| `permission_denied` | qualunque | altri 403 | testo senza riferimenti alla SA |
| `api_disabled` | qualunque | 403 `accessNotConfigured`/`SERVICE_DISABLED` | "…nel progetto Google Cloud del client OAuth…" |
| `quota_exceeded` | qualunque | 403/429 reason di quota | "Spazio Google Drive esaurito o limite di richieste: libera spazio o riprova più tardi." |
| `timeout` · `network_error` · `unexpected` | — | invariati | invariati |

Regole invariate (ADR-0031): mai `str(exc)`, `exc.reason`, `exc.content`, `exc.uri`; ogni testo
passa da `redact()`; `RefreshError(retryable=True)` resta `network_error`. Per il campo `error` di
un `RefreshError` si legge solo il dict strutturato in `exc.args[1]` quando è un `dict`; se manca,
`auth_invalid` (prudente: non dichiarare "scaduto" senza prova).

## Task

### T1 — `drive.py`: credenziali OAuth, classificazione, messaggi · **backup-agent**

- **File**: `backend/app/drive.py`, `backend/tests/test_gdrive_probe.py`.
- `get_drive_service(token_path)`: `None` se path vuoto o file assente; altrimenti
  `google.oauth2.credentials.Credentials.from_authorized_user_file(token_path, DRIVE_SCOPES)` →
  `AuthorizedHttp` con timeout invariato → `build(...)`. Rimuovere l'import di `service_account`.
- `run_gdrive_probe(token_path, folder_id)`: rinomina parametro, esiti `auth_missing`/`auth_invalid`.
- `classify_drive_error`: tabella sopra. 401 → `auth_expired`.
- `_MESSAGES`: chiavi e testi nuovi; `_SECURITY_REF` invariato.
- `redact()`: chiave `google_oauth_token_path` al posto di `google_sa_key_path`.
- **Test** (FakeDrive esistente; credenziali **mockate** con monkeypatch di
  `Credentials.from_authorized_user_file`, mai un file JSON con chiavi di token reali o quotate):
  path vuoto/assente → `auth_missing`; loader che solleva `ValueError` → `auth_invalid`;
  `RefreshError("…", {"error": "invalid_grant"})` → `auth_expired`;
  `RefreshError("…", {"error": "invalid_client"})` → `auth_invalid`; `RefreshError(retryable=True)`
  → `network_error`; 401 → `auth_expired`; 404 in `write` → `folder_not_found`; 403
  `storageQuotaExceeded` → `quota_exceeded`; 403 `insufficientPermissions` → `auth_invalid`;
  sentinel: token path e folder id assenti da `message`, `google_reason`, log (`caplog`).
- **Vincolo hook**: nessun file di test contiene i letterali `"refresh_token"` o
  `"client_secret"` con le virgolette.

### T2 — config, router backup, `.env.example`, compose · **backup-agent**

- **File**: `backend/app/config.py`, `backend/app/routers/backup.py`, `.env.example`,
  `docker-compose.yml` (solo commento del mount), `backend/tests/test_backup_router.py`,
  `backend/tests/test_backup_last.py`.
- `config.py`: `google_oauth_token_path: str = ""` al posto di `google_sa_key_path`.
- `routers/backup.py`: `_drive_and_retention()` e `gdrive_test()` usano il nuovo campo;
  `drive["outcome"] = "auth_missing"` con `outcome_message("auth_missing")` (oggi il testo SA è
  fisso nel router: va uniformato al messaggio dell'esito); `sa_invalid` → `auth_invalid`.
- `.env.example`: `GOOGLE_OAUTH_TOKEN_PATH=` vuoto con commento che rimanda a SECURITY.md;
  rimossa `GOOGLE_SA_KEY_PATH`. **Nessun path di esempio sotto la cartella dei secret.**
- `docker-compose.yml`: il mount read-only resta; aggiornare il commento (token OAuth, non SA).
- **Test**: sostituzione dei monkeypatch `google_sa_key_path` → `google_oauth_token_path`;
  regressioni D7/G2 invariate (folder id vuoto → nessun upload; `drive_error` sanitizzato);
  sentinel sul token path in risposta di `POST /backup`, `POST /backup/gdrive-test`,
  `GET /backup/last` e nei log.

### T3 — blacklist settings · **backup-agent**

- **File**: `backend/app/services/settings.py`, `backend/app/routers/settings.py`,
  `backend/tests/test_settings_service.py`, `backend/tests/test_settings_router.py`.
- `BLACKLIST = {"ai_api_key", "google_oauth_token_path", "gdrive_backup_folder_id"}`.
- `_is_secret_configured`: ramo `google_oauth_token_path` → `bool(value) and os.path.exists(value)`;
  docstring aggiornata (default ora vuoto).
- **Test**: frozenset aggiornato; `configured` false con path vuoto, false con file assente, true
  con file presente; sentinel: il path non compare mai in `GET /settings`; `PUT /settings` con la
  nuova chiave → 400 messaggio fisso.

### T4 — script di setup sul host · **backup-agent**

- **File nuovi**: `scripts/gdrive_oauth_setup.py`, `scripts/requirements-oauth.txt`
  (`google-auth-oauthlib`, `google-api-python-client`, versioni pinnate e coerenti con
  `backend/requirements.txt`), `backend/tests/test_oauth_setup_script.py`.
- CLI: `--client-secrets PATH` (JSON del client "Desktop app"), `--out PATH` (file di token),
  `--create-folder NOME` (opzionale), `--force` (consente di sovrascrivere `--out`).
- Flusso: `InstalledAppFlow.from_client_secrets_file(..., scopes=[drive.file])` →
  `run_local_server(host="127.0.0.1", port=0, access_type="offline", prompt="consent")` (PKCE
  attivo nel flusso). Se il refresh token manca → errore esplicito, nessun file scritto.
- Scrittura: `os.open(out, O_WRONLY|O_CREAT|O_EXCL, 0o600)` (con `--force`: `O_TRUNC` al posto di
  `O_EXCL`); contenuto = `creds.to_json()`. Su Windows i permessi POSIX sono indicativi: lo dice
  l'help.
- Output a terminale: solo esito e, con `--create-folder`, l'id della cartella creata (unico dato
  che l'utente deve copiare). **Mai** token, secret, path completi in eccezioni.
- Lo script non legge `.env` e non conosce path di default: tutto dagli argomenti.
- **Test** (flow e Drive mockati): file scritto con il contenuto di `to_json()`; rifiuto senza
  `--force` se `--out` esiste; refresh token assente → exit ≠ 0 e nessun file; `--create-folder`
  chiama `files().create` con `mimeType` cartella e stampa solo l'id; stdout/stderr non contengono
  il valore del token fittizio.

### T5 — hook pre-commit · **main**

- **File**: `.githooks/pre-commit`.
- Pattern esteso con `"refresh_token"|"client_secret"` (virgolette incluse); messaggio di blocco
  che nomina anche i token OAuth.
- **Verifica manuale** (il hook non ha suite): file finto con `{"refresh_token": "x"}` in
  staging → commit bloccato; `scripts/gdrive_oauth_setup.py` e i test di T1-T4 → commit
  consentito. Esito nel ledger.

### CP1 — checkpoint umano: contratto

Tabella esiti finale, `pytest` completo verde, rilettura dello script di T4 (cosa stampa, cosa
scrive, dove). Nessun Drive reale.

### T6 — UI · **react-ui-agent**

- **File**: `frontend/src/pages/Settings.tsx`, `frontend/src/pages/Backup.tsx`.
- `Settings.tsx`: voce secret `{ key: 'google_oauth_token_path', envVar: 'GOOGLE_OAUTH_TOKEN_PATH',
  label: 'Token OAuth Google Drive' }` al posto della SA.
- `Backup.tsx`: nessun testo che nomini la Service Account; commento di contratto aggiornato.
- **Verifica**: `npx tsc --noEmit`, `npm run build`; grep `Service Account`/`service_account` in
  `frontend/src` vuoto.

### T7 — documenti · **main**

- `docs/SECURITY.md`: sezione «Backup su Google Drive» riscritta (OAuth, `drive.file`, cartella
  creata dall'app, tabella dei 12 esiti, rotazione/revoca del token, restore manuale da Drive) +
  la **procedura utente** sotto, + paragrafo «Come fornire le credenziali a runtime» aggiornato;
  blacklist aggiornata.
- `.claude/agents/backup-agent.md`, `.claude/agents/README.md`, `backend/README.md`: SA → OAuth.
- `CLAUDE.md`: regola 7 (blacklist), stato corrente, riga backup-agent.
- `docs/ARCHITECTURE.md`: stato avanzamento + «Prompt di ripresa».
- ADR-0035 → **Accepted**; rettifica breve in coda ad ADR-0018 e ADR-0031 che rimanda a ADR-0035.

### CP2 — checkpoint umano dal vivo

1. **Backup preventivo del DB reale, prima di qualunque rebuild** (l'utente potrebbe aver già
   ricaricato dati): copia con l'online backup API SQLite (`sqlite3.Connection.backup()`, come
   ADR-0018 p.1) in `data/archive/portfolio-pre-oauth-<YYYYMMDD>.db` (gitignored, **non
   cancellare**); `PRAGMA integrity_check` sulla copia = `ok`; conteggio di `transactions`,
   `accounts`, `categories` annotato nel ledger.
2. L'utente esegue la procedura (sotto) fino al file di token e all'id cartella in `.env`.
3. `docker compose up -d --build`; `/health` 200.
4. Probe da `/backup-restore` → `ok`.
5. `POST /backup` → `drive_uploaded: true`; la coppia `.db`/`.xlsx` compare nella cartella.
6. Secondo backup con `backup_retention` temporaneamente a 1 da `/impostazioni` → rotazione su
   Drive della coppia precedente; poi `backup_retention` riportato al valore di prima.
7. L'utente sposta la cartella creata dallo script dentro la propria cartella → probe ancora `ok`.
8. Annotare se la schermata di consenso ha mostrato l'avviso "app non verificata".
9. Solo dopo il GO: l'utente revoca la chiave della SA e toglie la condivisione della cartella.

#### Esiti CP2 (registrati 2026-10-23)

Backup preventivo del DB reale eseguito prima del rebuild (`data/archive/portfolio-pre-oauth-20261023.db`,
integrity_check `ok`, 514 transazioni · 3 conti · 20 categorie, revisione `0006`). Esiti riportati
dall'utente: passi 3-4 (probe `ok`) · 5 (`drive_uploaded: true`, coppia nella cartella) · 6 (rotazione su
Drive corretta, `backup_retention` ripristinato) · 7 (probe `ok` dopo lo spostamento della cartella) ·
passo 8 (avviso "app non verificata"): **non registrato**. Passo 9 (revoca chiave SA, rimozione
condivisione) non ancora fatto: dopo il task "rimozione completa SA". Durante il CP2 è emerso che il
`.env` non era stato aggiornato al primo tentativo (`GOOGLE_OAUTH_TOKEN_PATH` assente nel container):
diagnosticato con controlli booleani nel container, senza leggere `.env`.

### T8 — review finale e merge · **main**

Review whole-branch (subagent Opus 5.5) su codice + documenti, fix dei Critical/Important, merge
`--no-ff` in `master` **solo su ok esplicito dell'utente**, nessun push senza richiesta.

## Gate finali

- `pytest` completo verde (347 di partenza ± test rinominati/aggiunti, numero esatto nel report).
- `alembic heads` = una sola riga, `0006`.
- `npx tsc --noEmit` e `npm run build` verdi.
- `grep -rn "service_account\|GOOGLE_SA_KEY_PATH\|google_sa_key_path\|sa_missing\|sa_invalid\|sa_auth_failed"
  backend/app frontend/src` → vuoto (i documenti storici e gli ADR passati restano invariati).
- Hook: file finto di token bloccato (T5, ripetuto sul branch finale).
- `docker compose build --no-cache backend` + `/health` 200. Gate arm64 non richiesto (stesse
  dipendenze dell'immagine); se T4 tocca `backend/requirements.txt`, il gate torna obbligatorio.
- Nessun id di cartella e nessun path reale della cartella dei secret in documenti, log o test.

## Procedura per l'utente (diventa parte di `docs/SECURITY.md` in T7)

L'agente non esegue questi passi, non legge i file prodotti e non ne conosce i nomi.

1. **Progetto Google Cloud** — quello della SA va bene, oppure uno nuovo. «API e servizi →
   Libreria → Google Drive API» → Abilita.
2. **Schermata di consenso** («Google Auth Platform»):
   - *Branding*: nome app (es. "PersonalPortfolio backup"), email di supporto = la tua. **Nessun
     logo**.
   - *Audience*: tipo utente **External** (unico disponibile su `@gmail`).
   - *Data access*: aggiungi solo lo scope `https://www.googleapis.com/auth/drive.file`.
   - *Audience* → **Publish app** → stato **In production**. In "Testing" il token scade dopo
     7 giorni.
3. **Client OAuth** — «Clients → Create client» → tipo **Desktop app** → scarica il JSON del
   client e salvalo nella cartella dei secret del progetto con un nome a tua scelta (la cartella è
   già esclusa da git; il nuovo marcatore dell'hook blocca comunque un commit accidentale).
4. **Generazione del token** sul tuo PC (serve un browser):
   ```bash
   python -m venv .venv-oauth
   .venv-oauth/Scripts/pip install -r scripts/requirements-oauth.txt
   .venv-oauth/Scripts/python scripts/gdrive_oauth_setup.py --client-secrets <json del client> --out <file di token> --create-folder "PersonalPortfolio backup"
   ```
   (su Linux/Mac `.venv-oauth/bin/...`). Si apre il browser: accedi con il tuo account `@gmail` e
   concedi l'accesso. Se compare «Google non ha verificato questa app», è la tua app personale:
   «Avanzate → Vai a … (non sicura)». Lo script scrive il file di token e stampa **solo** l'id
   della cartella appena creata.
5. **Cartella** — su Google Drive sposta la cartella creata dallo script dentro la cartella che
   avevi creato a mano (facoltativo: funziona anche dove si trova).
6. **`.env`** — imposta `GOOGLE_OAUTH_TOKEN_PATH` al percorso **nel container** del file di token
   (la cartella dei secret è montata in sola lettura, vedi `docker-compose.yml`) e
   `GDRIVE_BACKUP_FOLDER_ID` all'id stampato; rimuovi `GOOGLE_SA_KEY_PATH`.
7. **Avvio e verifica** — `docker compose up -d --build`, poi `/backup-restore` → «Test
   connessione» → atteso `ok`.
8. **Dismissione della SA** (dopo `ok`) — console Google → «IAM → Account di servizio» → chiavi →
   elimina la chiave; su Drive togli la condivisione della cartella manuale con l'email della SA;
   elimina il JSON della SA dalla cartella dei secret.
9. **Rotazione o revoca** — rigenera con lo stesso comando e `--force`. Per revocare subito un
   token compromesso: https://myaccount.google.com/permissions → rimuovi l'accesso dell'app, poi
   rigenera. Esito atteso dopo una revoca senza rigenerazione: `auth_expired`.
