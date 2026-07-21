# Security — Personal Portfolio

## Principio
I secret (Service Account key Google, API key AI) **non entrano mai nel repository**.
Vengono forniti al container **a runtime**, tramite volume montato o variabili ambiente.

## Cosa non committare mai
- Service Account JSON (`*service_account*.json`, contenuti in `secrets/`)
- File `.env` (solo `.env.example` è versionato)
- Chiavi private (`*.key`, `*.pem`), DB (`*.db`), backup (`backups/`)

Tutti coperti da `.gitignore`.

## Enforcement automatico (ADR-0011)
Hook `pre-commit` in `.githooks/pre-commit`: fa **grep del contenuto** dei file staged cercando
marcatori di secret e **blocca il commit** se li trova:
```
private_key | client_email | auth_uri | token_uri | -----BEGIN ... PRIVATE KEY-----
```
Criterio sul **contenuto**, non sulla dimensione: non blocca `package.json`/`tsconfig.json` legittimi.

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
1. **Service Account Google** (backup, Fase 4): salva il JSON in `./secrets/service_account.json`
   sull'host. `docker-compose.yml` lo monta **read-only** su `/secrets`. Path in `.env`:
   `GOOGLE_SA_KEY_PATH=/secrets/service_account.json`.
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
- `GOOGLE_SA_KEY_PATH` — percorso della Service Account montata;
- `GDRIVE_BACKUP_FOLDER_ID` — id della cartella Drive di backup.

`GDRIVE_BACKUP_FOLDER_ID` **non è una credenziale**, ed è proprio per questo che va detto
esplicitamente perché è in blacklist: identifica una cartella privata dell'utente. Esporlo non
permette a nessuno di scriverci — serve comunque la Service Account — ma rivela l'esistenza e la
posizione di una risorsa personale, e finirebbe in cronologia browser, screenshot e log. Il criterio
della blacklist non è "è un segreto?" ma **"identifica o apre qualcosa di privato?"**.

### Come si presentano i secret in interfaccia

Mai come campo di input, mai come valore mascherato con asterischi (un valore mascherato è comunque
un valore trasmesso). `GET /settings` restituisce per ciascun secret solo:

```json
{ "secrets_status": { "ai_api_key": { "configured": true }, "google_sa_key_path": { "configured": false } } }
```

La UI mostra un badge "configurato / non configurato" e la riga `.env` da compilare. Il valore reale
si imposta solo modificando `.env` sull'host, come è sempre stato.

Un **test automatico** fallisce se una chiave blacklistata compare in qualunque punto della risposta
di `GET /settings`: la regola è verificata dalla suite, non solo dichiarata qui.

### Nota sui nomi

**`GOOGLE_API_KEY` non esiste in questo progetto e non va introdotta.** La chiave del provider AI si
chiama `AI_API_KEY` ed è provider-agnostica per scelta (ADR-0023 p.3): un nome legato a un fornitore
specifico contraddirebbe l'adapter e andrebbe riscritto al primo cambio di provider. Le variabili
Google realmente esistenti sono `GOOGLE_SA_KEY_PATH` e `GDRIVE_BACKUP_FOLDER_ID`, entrambe relative
al backup su Drive.

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

**Cosa non cambia neanche qui.** L'egress avviene sempre e solo su **submit esplicito**: nessuna
domanda parte da sola, nessuna sincronizzazione in background. La persistenza è scritta dal router
del backend, **mai da un tool**: il modello continua a non avere alcuna operazione di scrittura
raggiungibile (ADR-0023 punto 4, ADR-0032 punto 6).

## Backup su Google Drive: condivisione cartella con la Service Account (Fase 4, ADR-0018)

La Service Account **non ha uno spazio Drive proprio**: può scrivere solo in cartelle
condivise esplicitamente con lei. Passo umano, una tantum, da fare nella console Google:

1. Apri il JSON della Service Account (`secrets/service_account.json`) e leggi il campo
   `"client_email"` (es. `nome-account@progetto.iam.gserviceaccount.com`).
2. Su [Google Drive](https://drive.google.com), crea (o scegli) la cartella destinata ai
   backup, click destro → **Condividi** → incolla l'email della Service Account → ruolo
   **Editor** (serve per creare/cancellare i file di backup, non solo leggerli).
3. Apri la cartella e copia l'ID dall'URL (`https://drive.google.com/drive/folders/<ID>`).
4. Imposta `GDRIVE_BACKUP_FOLDER_ID=<ID>` in `.env`.

Se lo scope OAuth della Service Account è `drive.file` (usato da questa app, non `drive`
pieno — vedi `backend/app/drive.py`), la Service Account vede **solo** i file che ha creato
lei stessa: la cartella condivisa limita comunque dove può scrivere, ma non le dà accesso
al resto del Drive dell'utente. Se `GOOGLE_SA_KEY_PATH` non esiste a runtime, il backup
Drive viene skippato senza errori bloccanti — il backup locale funziona comunque
(degradazione graceful, ADR-0018 punto 3).

### Il test di connettività scrive davvero (Fase 10, ADR-0031)

`POST /backup/gdrive-test` **non è una verifica passiva**: crea un file di pochi byte
(`portfolio_gdrive_probe_<timestamp>.probe`) nella cartella configurata, lo rilegge e lo cancella.
Va saputo prima di premere il pulsante.

Il motivo è lo scope `drive.file` descritto sopra: la Service Account vede **solo i file creati da
lei**, quindi una cartella condivisa ma vuota e una cartella mai condivisa danno lo stesso identico
risultato in lettura. Un test che si limitasse a elencare i file potrebbe passare mentre il backup
fallisce. Solo una scrittura reale dimostra il permesso che al backup serve davvero.

Il file è effimero e la cancellazione è tentata in ogni caso, ma la pulizia è **best-effort, non
garantita**: se la rete cade dopo la creazione, un residuo può restare su Drive fino al test
successivo, che rimuove gli orfani all'avvio. Il prefisso è distinto da quello dei backup, quindi il
probe non interferisce mai con la rotazione.

Le credenziali non passano dalla richiesta: `GDRIVE_BACKUP_FOLDER_ID` e `GOOGLE_SA_KEY_PATH` sono
letti dal backend dalla propria configurazione e **non compaiono nella risposta**, nemmeno dentro un
messaggio d'errore — gli errori di Google che contengono l'id vengono sanitizzati prima di uscire.
