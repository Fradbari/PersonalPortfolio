# Security — Personal Portfolio

## Principio
I secret (credenziali OAuth Google per il backup, API key AI) **non entrano mai nel repository**.
Vengono forniti al container **a runtime**, tramite volume montato o variabili ambiente.

## Cosa non committare mai
- File di token OAuth Google (generato dallo script di setup, contiene refresh token e client
  secret) e JSON del client OAuth scaricato dalla console: vivono solo in `secrets/`
- Service Account JSON (`*service_account*.json`): non più usata (ADR-0035), il pattern resta in
  `.gitignore` per sicurezza
- File `.env` (solo `.env.example` è versionato)
- Chiavi private (`*.key`, `*.pem`), DB (`*.db`), backup (`backups/`)

Tutti coperti da `.gitignore`.

## Enforcement automatico (ADR-0011)
Hook `pre-commit` in `.githooks/pre-commit`: fa **grep del contenuto** dei file staged cercando
marcatori di secret e **blocca il commit** se li trova:
```
private_key | client_email | auth_uri | token_uri | "refresh_token" | "client_secret" | -----BEGIN ... PRIVATE KEY-----
```
Criterio sul **contenuto**, non sulla dimensione: non blocca `package.json`/`tsconfig.json` legittimi.

I marcatori `"refresh_token"` e `"client_secret"` (ADR-0035) sono cercati **con le virgolette**, cioè
nella forma di chiave JSON: bloccano il file di token OAuth e il JSON del client scaricato dalla
console, ma non l'accesso ad attributo nel codice Python (`creds.refresh_token`). Per lo stesso
motivo test e script del repository non contengono quei letterali quotati.

### Attivazione (una tantum, dopo il clone)
```bash
git config core.hooksPath .githooks
# su Windows Git Bash il file è già eseguibile; su Linux/Mac:
chmod +x .githooks/pre-commit
```

### Test del hook
```bash
# crea una fake key e prova a committarla: il commit deve essere BLOCCATO
printf '{"private_key":"-----BEGIN PRIVATE KEY-----\\nX\\n-----END PRIVATE KEY-----","client_email":"x@y"}' > /tmp/fake_sa.json
git add -f /tmp/fake_sa.json && git commit -m "test" ; echo "exit=$?"
# atteso: "BLOCKED ..." + exit diverso da 0. Poi: git reset /tmp/fake_sa.json
```

## Come fornire le credenziali a runtime
1. **Token OAuth Google Drive** (backup, ADR-0035): lo genera l'utente, una tantum, sul proprio PC
   con `scripts/gdrive_oauth_setup.py` (procedura completa nella sezione «Backup su Google Drive»).
   Il file di token va nella cartella `./secrets/` dell'host; `docker-compose.yml` la monta
   **read-only** su `/secrets`. In `.env` imposta `GOOGLE_OAUTH_TOKEN_PATH` al percorso **nel
   container** di quel file. Il default è vuoto: senza token il backup Drive viene saltato e quello
   locale funziona comunque. Il backend non riscrive mai il file.
2. **API key AI** (Fase 6): imposta `AI_API_KEY` in `.env` (non committato), insieme a
   `AI_PROVIDER` (oggi solo `gemini`) e `AI_MODEL`. Se `AI_PROVIDER` è vuoto il layer AI resta
   disattivo e il resto dell'app funziona invariato.

La cartella `secrets/` esiste nel repo solo con un `.gitkeep`; il contenuto reale è ignorato.

## Campi sensibili nella UI (Fase 9, ADR-0027)

Fino a F8 il progetto aveva **un solo perimetro** da difendere: il repository. Il pre-commit hook
(ADR-0011) impedisce che un secret finisca in un commit, e tanto bastava perché nessuna interfaccia
leggeva la configurazione.

La pagina `/settings` di F9 crea un **secondo perimetro**: una superficie HTTP che espone
configurazione. Sono due cose diverse, e vanno difese separatamente — un secret può essere fuori dal
repository e uscire lo stesso da un endpoint.

### Cosa può passare dalla UI

**Whitelist** — le uniche chiavi leggibili e scrivibili da `/settings`:

| Chiave | Cos'è | Quando ha effetto |
|---|---|---|
| `theme` | preferenza tema (`light`/`dark`/`system`) | immediato |
| `metabase_url` | destinazione del link a Metabase | immediato |
| `ai_history_max_turns` | ampiezza della finestra di contesto AI | dalla domanda successiva |
| `import_min_year` | anno minimo di import | dal prossimo import |
| `backup_retention` | numero di backup conservati | dal prossimo backup |
| `backup_on_startup` | backup automatico all'avvio | **dal boot successivo** |

Qualunque chiave aggiunta in futuro entra qui **con la sua riga**, altrimenti non è esposta.

### Cosa non può passare, mai

**Blacklist permanente** — non leggibili né scrivibili da alcun endpoint o pagina:

- `AI_API_KEY` — chiave del provider AI;
- `GOOGLE_OAUTH_TOKEN_PATH` — percorso del file di token OAuth montato (ADR-0035; ha sostituito
  `GOOGLE_SA_KEY_PATH`, la cui voce di blacklist è stata rettificata);
- `GDRIVE_BACKUP_FOLDER_ID` — id della cartella Drive di backup.

`GDRIVE_BACKUP_FOLDER_ID` **non è una credenziale**, ed è proprio per questo che va detto
esplicitamente perché è in blacklist: identifica una cartella privata dell'utente. Esporlo non
permette a nessuno di scriverci — serve comunque il token OAuth — ma rivela l'esistenza e la
posizione di una risorsa personale, e finirebbe in cronologia browser, screenshot e log. Il criterio
della blacklist non è "è un segreto?" ma **"identifica o apre qualcosa di privato?"**.

### Come si presentano i secret in interfaccia

Mai come campo di input, mai come valore mascherato con asterischi (un valore mascherato è comunque
un valore trasmesso). `GET /settings` restituisce per ciascun secret solo:

```json
{ "secrets_status": { "ai_api_key": { "configured": true }, "google_oauth_token_path": { "configured": false } } }
```

`configured` per il token OAuth significa «il file esiste nel container», mai il suo percorso o
contenuto. La UI mostra un badge "configurato / non configurato" e la riga `.env` da compilare. Il valore reale
si imposta solo modificando `.env` sull'host, come è sempre stato.

Un **test automatico** fallisce se una chiave blacklistata compare in qualunque punto della risposta
di `GET /settings`: la regola è verificata dalla suite, non solo dichiarata qui.

### Nota sui nomi

**`GOOGLE_API_KEY` non esiste in questo progetto e non va introdotta.** La chiave del provider AI si
chiama `AI_API_KEY` ed è provider-agnostica per scelta (ADR-0023 p.3): un nome legato a un fornitore
specifico contraddirebbe l'adapter e andrebbe riscritto al primo cambio di provider. Le variabili
Google realmente esistenti sono `GOOGLE_OAUTH_TOKEN_PATH` e `GDRIVE_BACKUP_FOLDER_ID`, entrambe
relative al backup su Drive.

## Egress esterno verso il provider AI (Fase 6, ADR-0023)

Il layer AI è il **secondo** servizio esterno del progetto dopo Google Drive, ed è il primo verso cui
escono dati finanziari veri e propri. Va capito bene prima di attivarlo.

**Cosa esce dalla rete locale.** Quando poni una domanda nella pagina "Assistente AI", il backend
esegue un loop di function calling: il modello chiede l'esecuzione di un tool, il backend interroga il
DB locale e **rimanda il risultato al provider**. Quei risultati possono contenere:

- dati aggregati (trend mensili, breakdown per categoria, saldi);
- **transazioni grezze**: data, importo, categoria, conto, tipo, e **i campi liberi `comment` e
  `tag`** — cioè le note che hai scritto tu, che possono contenere nomi di persone, luoghi, dettagli
  personali.

L'inclusione di `comment`/`tag` è una **scelta esplicita** dell'utente (ADR-0023 punto 9), fatta per
poter rispondere a domande come "quanto ho speso per il regalo di X". È il trade-off privacy di questa
fase. È reversibile: basta restringere il tool `list_transactions` a non restituire quei due campi,
senza toccare nient'altro dell'architettura.

**Quando esce.** Solo su **submit esplicito** del form. Mai in background, mai a un orario, mai
all'avvio — stesso principio di controllo-utente-sul-quando già applicato al backup (ADR-0008).
Nessuna domanda parte da sola.

**Verso chi.** Verso il provider che configuri tu, autenticato con **la tua chiave personale**. Il
progetto non ha né usa una chiave propria. Vale la pena leggere le condizioni d'uso del provider
scelto per capire se e per quanto conserva i contenuti inviati: è una decisione che resta tua, non
del progetto.

**La chiave.** In `.env`, mai nel repository, coperta dall'hook pre-commit content-based (ADR-0011).
Se `AI_PROVIDER` è vuoto o la chiave manca, l'endpoint risponde con un errore esplicito e il resto
dell'app continua a funzionare (degradazione graceful, ADR-0023 punto 8).

**Cosa NON cambia.** ADR-0009 resta invariato: questo è un flusso **uscente** iniziato dall'utente,
non una nuova esposizione entrante. L'app continua a stare solo sulla rete locale, senza auth né
reverse proxy. Nessun tool AI può scrivere sul database (ADR-0023 punto 4): il modello legge e basta.

### Estensione con la memoria conversazionale (Fase 14, ADR-0032)

F14 rende l'assistente non più stateless. Due conseguenze da capire prima di usarlo.

**Le conversazioni restano sul tuo disco.** Domande, risposte e traccia dei tool vengono salvate in
`data/portfolio.db`, nelle tabelle `chat_sessions` e `chat_messages`, e ci restano finché non le
cancelli. Finiscono quindi anche **dentro i backup**, compresi quelli su Drive: se hai posto domande
che contengono dettagli personali, quei testi viaggiano con il backup.

**Il contesto viene rispedito al provider a ogni domanda.** In una conversazione, ogni nuova domanda
parte insieme alle ultime `ai_history_max_turns` coppie domanda/risposta (default 6). Significa che
il volume di dati in egress **cresce con la lunghezza della conversazione**: una chat di venti
scambi rimanda più materiale di quanto si ricordi di aver inviato. Il cap esiste proprio per questo
ed è abbassabile da `/settings` senza toccare il codice.

**"Azzera storico" è anche una leva di privacy**, non solo di pulizia: cancella tutte le sessioni e
tutti i messaggi dal database locale. Richiede una conferma esplicita perché non c'è modo di
ricostruire cosa è andato perso.

**Ma "Azzera storico" agisce solo sul database vivo.** Due copie delle chat restano dove sono:

- **I backup già creati** (locali e su Drive) contengono le chat com'erano al momento del backup.
  Sopravvivono all'azzeramento **finché la retention (`backup_retention`) non li ruota** fuori: per
  eliminarle prima va cancellato a mano il backup, in locale e su Drive. Un restore da un backup
  precedente all'azzeramento le riporta indietro, salvo il caso del backup pre-`0006`, che non ha le
  tabelle chat e le lascia vuote.
- **La replica read-only di Metabase** è una copia intera del database (ADR-0004): include
  `chat_sessions` e `chat_messages`, quindi chiunque abbia accesso a Metabase può interrogarle con
  una domanda SQL. La replica si rigenera solo dopo un import o un restore, **non** dopo
  "Azzera storico" né dopo l'eliminazione di una singola conversazione: le chat cancellate restano
  leggibili in Metabase fino al refresh successivo.
  Se la cosa conta, rigenera la replica con un import o un restore (debito: un refresh esplicito
  dopo l'azzeramento non esiste, vedi ARCHITECTURE.md).

**Cosa non cambia neanche qui.** L'egress avviene sempre e solo su **submit esplicito**: nessuna
domanda parte da sola, nessuna sincronizzazione in background. La persistenza è scritta dal router
del backend, **mai da un tool**: il modello continua a non avere alcuna operazione di scrittura
raggiungibile (ADR-0023 punto 4, ADR-0032 punto 6).

## Backup su Google Drive: OAuth utente (Fase 4 ADR-0018, rimedio ADR-0035)

Il backup off-site usa **OAuth utente** con un refresh token e lo scope `drive.file`. Una Service
Account non è più usata: non ha quota di storage propria e in un My Drive personale non può creare
file (vedi `quota_exceeded` sotto). Con `drive.file` l'app vede e modifica **solo i file che ha
creato lei**; non ha accesso al resto del Drive dell'utente. Ne segue che la **cartella di
destinazione deve essere creata dall'app** (la crea lo script di setup): una cartella creata a mano
è invisibile all'app e un upload risponde 404 (`folder_not_found`).

Il file di token è generato **una tantum, dall'utente, sul proprio PC** e montato nel container in
sola lettura: il backend non lo riscrive mai (l'access token vive solo in memoria). Se
`GOOGLE_OAUTH_TOKEN_PATH` è vuoto o il file non esiste a runtime, il backup Drive viene saltato senza
errori bloccanti e il backup locale funziona comunque (degradazione graceful, ADR-0018 punto 3).

### Procedura di setup (una tantum, la esegue l'utente)

L'assistente di sviluppo non esegue questi passi, non legge i file prodotti e non ne conosce i nomi.

1. **Progetto Google Cloud** — va bene quello già usato oppure uno nuovo. «API e servizi →
   Libreria → Google Drive API» → Abilita.
2. **Schermata di consenso** («Google Auth Platform»):
   - *Branding*: nome app (es. "PersonalPortfolio backup"), email di supporto = la tua. **Nessun
     logo** (richiederebbe la verifica del brand).
   - *Audience*: tipo utente **External** (unico disponibile su un account `@gmail`).
   - *Data access*: aggiungi solo lo scope `https://www.googleapis.com/auth/drive.file`.
   - *Audience* → **Publish app** → stato **In production**. In "Testing" il refresh token
     scade dopo 7 giorni e il backup smetterebbe di funzionare in silenzio. Con soli scope
     non-sensitive non serve la verifica dell'app.
3. **Client OAuth** — «Clients → Create client» → tipo **Desktop app** → scarica il JSON del client
   e salvalo nella cartella dei secret del progetto con un nome a tua scelta. La cartella è già
   esclusa da git e l'hook pre-commit blocca comunque un commit accidentale.
4. **Generazione del token** sul tuo PC (serve un browser):
   ```bash
   python -m venv .venv-oauth
   .venv-oauth/Scripts/pip install -r scripts/requirements-oauth.txt
   .venv-oauth/Scripts/python scripts/gdrive_oauth_setup.py --client-secrets <json del client> --out <file di token> --create-folder "PersonalPortfolio backup"
   ```
   (su Linux/Mac `.venv-oauth/bin/...`). Si apre il browser: accedi con il tuo account Google e
   concedi l'accesso. Se compare «Google non ha verificato questa app», è la tua app personale:
   «Avanzate → Vai a … (non sicura)». Lo script scrive il file di token (permessi 0600; su Windows
   i permessi POSIX sono solo indicativi, proteggi il file con le ACL della cartella) e stampa
   **solo** l'id della cartella appena creata. Senza `--force` rifiuta di sovrascrivere un file
   esistente.
5. **Cartella** — su Google Drive puoi spostare la cartella creata dallo script dentro un'altra
   cartella a tua scelta (facoltativo): l'accesso `drive.file` è legato al file, non alla sua
   posizione.
6. **`.env`** — imposta `GOOGLE_OAUTH_TOKEN_PATH` al percorso **nel container** del file di token
   (la cartella dei secret è montata in sola lettura su `/secrets`, vedi `docker-compose.yml`) e
   `GDRIVE_BACKUP_FOLDER_ID` all'id stampato dallo script.
7. **Avvio e verifica** — `docker compose up -d --build`, poi `/backup-restore` → «Test
   connessione» → atteso `ok`.
8. **Dismissione della vecchia Service Account** (solo dopo `ok`) — console Google → «IAM →
   Account di servizio» → chiavi → elimina la chiave; su Drive togli la condivisione della cartella
   manuale con l'email della Service Account; elimina il vecchio JSON dalla cartella dei secret.

### Rotazione, revoca, scadenza del token

- **Rotazione**: rigenera con lo stesso comando e `--force` (sostituisce il file in modo atomico,
  con permessi 0600). Dopo la sostituzione il backend usa il nuovo token alla prima operazione
  Drive, senza riavvio.
- **Revoca immediata** (token compromesso): https://myaccount.google.com/permissions → rimuovi
  l'accesso dell'app, poi rigenera. Dopo una revoca senza rigenerazione l'esito atteso è
  `auth_expired`.
- **Scadenza**: il refresh token può smettere di funzionare per revoca, sei mesi di inutilizzo, app
  rimasta in "Testing" o superamento del limite di 100 token per client e account. Il sintomo è
  `auth_expired` con rimedio esplicito (rigenerare); il backup locale continua a funzionare.
- **Protezione reale**: il secret di un client "Desktop app" non è confidenziale per definizione di
  Google; ciò che va protetto è il file di token. Il suo raggio d'azione è limitato ai file creati
  dall'app (non l'intero Drive).

### Restore da un backup su Drive (manuale)

Il restore (`POST /backup/restore`, ADR-0018 p.5 e ADR-0034) legge **solo** dalla cartella locale dei
backup e non usa alcuna credenziale Drive. Per ripristinare da una copia off-site: scarica da Drive
la coppia `.db`/`.xlsx` nella cartella dei backup e ripristinala dalla pagina `/backup-restore`.

### Il test di connettività scrive davvero (Fase 10, ADR-0031)

`POST /backup/gdrive-test` **non è una verifica passiva**: crea un file di pochi byte
(`portfolio_gdrive_probe_<timestamp>.probe`) nella cartella configurata, lo rilegge e lo cancella.
Va saputo prima di premere il pulsante.

Il motivo è lo scope `drive.file` descritto sopra: l'app vede **solo i file creati da lei**, quindi
una cartella vuota e una cartella non creata dall'app danno lo stesso identico risultato in lettura.
Un test che si limitasse a elencare i file potrebbe passare mentre il backup fallisce. Solo una scrittura reale dimostra il permesso che al backup serve davvero.

Il file è effimero e la cancellazione è tentata in ogni caso, ma la pulizia è **best-effort, non
garantita**: se la rete cade dopo la creazione, un residuo può restare su Drive fino al test
successivo, che rimuove gli orfani all'avvio. Il prefisso è distinto da quello dei backup, quindi il
probe non interferisce mai con la rotazione.

Le credenziali non passano dalla richiesta: `GDRIVE_BACKUP_FOLDER_ID` e `GOOGLE_OAUTH_TOKEN_PATH` sono
letti dal backend dalla propria configurazione e **non compaiono nella risposta**, nemmeno dentro un
messaggio d'errore — gli errori di Google che contengono l'id vengono sanitizzati prima di uscire.

#### Esiti del test e rimedio

`POST /backup/gdrive-test` risponde sempre con uno di questi dodici esiti (`outcome`), mai con il
testo grezzo di Google. Il campo `message` è fisso per esito.

| `outcome` | Cosa significa | Rimedio |
|---|---|---|
| `ok` | scrittura, lettura e cancellazione riuscite | nessuno |
| `auth_missing` | `GOOGLE_OAUTH_TOKEN_PATH` vuoto o file di token assente nel container | genera il token con lo script di setup, verifica `GOOGLE_OAUTH_TOKEN_PATH` e il bind mount di `secrets/` |
| `auth_invalid` | file di token non valido o incompleto; client OAuth non più valido (es. eliminato); scope insufficiente | rigenera il token con lo script di setup |
| `folder_id_missing` | `GDRIVE_BACKUP_FOLDER_ID` vuoto: nessuna scrittura eseguita | imposta l'ID stampato dallo script in `.env` |
| `auth_expired` | autorizzazione scaduta o revocata (revoca, sei mesi di inutilizzo, app rimasta in "Testing"), oppure HTTP 401 | rigenera il token con lo script di setup |
| `folder_not_found` | 404 sulla cartella | l'ID è errato **oppure la cartella non è stata creata dall'app** (scope `drive.file`): usa la cartella creata dallo script |
| `permission_denied` | altri 403 | verifica i permessi dell'account sulla cartella |
| `api_disabled` | 403 `accessNotConfigured`: Drive API spenta nel progetto Google Cloud del client OAuth | abilita «Google Drive API» in «API e servizi → Libreria», attendi qualche minuto |
| `quota_exceeded` | 403 `storageQuotaExceeded` (o quota/rate limit) | Drive dell'utente pieno o limite di richieste: libera spazio o riprova più tardi |
| `timeout` | nessuna risposta entro 30 s | riprova |
| `network_error` | DNS o connessione | controlla la rete del container |
| `unexpected` | qualunque altro caso | consulta i log (`docker logs`): riga `Probe Drive fallito in <stage>` |

**Storia di `quota_exceeded`.** Con la Service Account (F4/F10) questo esito non si risolveva con un
permesso: una Service Account **non ha quota di storage propria** e in un My Drive personale non può
creare file nemmeno in una cartella condivisa come Editor. Il rimedio è stato l'OAuth utente
(ADR-0035): con quella credenziale i file appartengono all'utente, e `quota_exceeded` significa solo
Drive dell'utente pieno o rate limit.

#### `POST /backup` è sanitizzato (D7)

Prima di F10 il campo `drive_error` di `POST /backup` poteva riportare il testo di un'eccezione
Google, che a volte include l'ID della cartella. Ora il messaggio è lo stesso fisso del test
(`outcome_message`), passato da `redact()`, e il log applicativo contiene solo tipo di eccezione,
stage, status e `reason`. La forma della risposta è invariata. Un test controlla che l'ID cartella
non compaia nella risposta di **entrambi** gli endpoint né nei log.
