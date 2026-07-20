# User Guide — Personal Portfolio

Guida funzionale: cosa puoi fare con l'app, una volta avviata. Per l'avvio da zero vedi
[GETTING_STARTED.md](GETTING_STARTED.md). Per il "perché" delle scelte tecniche vedi
[DECISIONS.md](DECISIONS.md) (ADR).

---

## Import mensile My Finance

Ogni mese puoi caricare l'export dell'app My Finance per aggiungere le tue transazioni al
portfolio.

**Come si carica**

Invia il file `.xlsx` esportato da My Finance a:

```
POST /import/my-finance
```

come upload multipart (campo `file`). Non serve nessun altro parametro: l'endpoint legge il
file così com'è.

**Cosa viene letto dal file**

- Vengono lette solo le due schede `Spese` ed `Entrate` dell'export. La scheda `Bonifici`
  viene **sempre ignorata** (sono movimenti tra tuoi conti, non spese/entrate reali) — non
  serve rimuoverla prima di caricare, il sistema la salta da sé.
- Da ogni riga vengono presi: data, categoria, conto, importo (in valuta predefinita),
  valuta, tag e commento.
- Eventuali righe vuote in fondo al foglio o righe con dati indispensabili mancanti (importo,
  categoria o conto assenti) vengono scartate automaticamente e segnalate nel conteggio
  `skipped_invalid_rows` della risposta — non generano errore, semplicemente non vengono
  importate.

**Categorie sconosciute**

Se una transazione usa una categoria che il sistema non ha mai visto prima (nessuna
corrispondenza nella mappa categorie), la transazione viene **importata comunque**, ma senza
categoria assegnata: la categoria grezza finisce in una coda di "categorie da risolvere" in
attesa di una decisione tua. Nessun dato viene perso o bloccato in attesa.

Per risolvere le categorie in sospeso:

- `GET /categories/pending` mostra l'elenco delle categorie ancora da mappare.
- `POST /categories/pending/{id}/resolve` associa la categoria grezza a una categoria
  canonica (esistente o nuova, a tua scelta): tutte le transazioni già importate con quella
  categoria vengono aggiornate automaticamente in un colpo solo, e le future importazioni
  con lo stesso nome verranno riconosciute direttamente.

I conti (es. "Conto corrente", "Contanti") non richiedono invece nessuna risoluzione: vengono
sempre accettati così come compaiono nel file, anche se non li avevi mai usati prima.

**Ricaricare lo stesso file**

Puoi ricaricare tranquillamente lo stesso export (o un export che si sovrappone a uno
precedente, es. mesi già coperti): il sistema riconosce automaticamente le transazioni già
presenti (stessa data, importo, categoria, conto e tipo) e le salta, senza creare duplicati.
Questo significa anche che se in un secondo momento modifichi manualmente un commento o un
tag su una transazione già importata, un nuovo caricamento dello stesso file non sovrascrive
quella modifica: il confronto per il duplicato non guarda commento/tag, solo i dati
finanziari "stabili" della riga.

**Cosa vedi dopo il caricamento**

La risposta dell'endpoint riepiloga l'esito dell'importazione:

- `imported` — quante transazioni sono state effettivamente aggiunte.
- `skipped_duplicates` — quante erano già presenti e sono state saltate.
- `skipped_invalid_rows` — quante righe del file non contenevano dati sufficienti.
- `pending_categories` — quali categorie nuove (mai viste prima in questo import) sono
  finite in coda da risolvere.

Con questi numeri puoi verificare al volo che l'import sia andato come previsto, ad esempio
che il conteggio `imported` corrisponda a quello che ti aspettavi dal mese appena chiuso.

## Migrazione storico (una tantum)

La migrazione dei dati storici (dal foglio Google "master sheet" con l'andamento delle spese
per anno) è un'operazione **una tantum**, pensata per essere eseguita una volta sola per
portare nel sistema lo storico pregresso, a partire dal 2026. Non è pensata per uso
ricorrente come l'import mensile.

Trattandosi di dato finanziario storico e di un'operazione che, una volta confermata, **non
si può annullare**, il flusso è sempre in due passi obbligatori: prima un'anteprima
(dry-run) che non scrive nulla nel database reale, poi — solo dopo aver controllato il
report — il caricamento definitivo (commit).

**1. Dry-run — anteprima senza rischi**

```
POST /import/historical/dry-run
```

Carica il file `.xlsx` del master sheet. Il file viene interpretato (righe categoria in
colonna trasformate in singole transazioni, una per cella valorizzata) e fatto passare
attraverso tutta la pipeline di importazione — incluso il controllo duplicati e la
risoluzione categorie — ma su un **database temporaneo**, creato al volo e scartato subito
dopo la richiesta. Il tuo database reale non viene toccato in nessun modo, anche se lanci
questa chiamata più volte.

Il report restituito contiene:

- `would_import` — quante transazioni verrebbero effettivamente importate se confermassi.
- `skipped_duplicates` — quante risultano già presenti nel database reale (quindi verrebbero
  saltate anche al commit).
- `skipped_rows` — l'elenco dettagliato delle righe del foglio scartate durante
  l'interpretazione, con il motivo per ciascuna (riga vuota, marcatore di mese, riga di
  totale/aggregato che non è una transazione, riga "Entrate" senza un mese deducibile, ecc.):
  utile per verificare che nulla di importante sia stato escluso per errore.
- `pending_categories` — le categorie del foglio storico non ancora mappate, che finirebbero
  in coda da risolvere.
- `monthly_quadrature` — per ogni mese, il confronto tra la somma delle spese che verrebbero
  importate (al netto dei duplicati) e il totale spese riportato nel foglio stesso per quel
  mese, con la differenza (`diff`) tra i due. È il controllo di coerenza principale: se un
  mese non quadra, è il segnale che qualcosa nell'interpretazione di quel blocco va
  verificato prima di procedere.

**2. Validazione manuale**

Prima di procedere al commit, controlla il report del dry-run con attenzione: in particolare
`monthly_quadrature` (differenze vicine a zero per ogni mese) e `skipped_rows` (nessuna riga
scartata per un motivo inatteso). Non esiste un flag di conferma automatico nel sistema: la
decisione di procedere è tua, dopo aver verificato che i numeri tornino. Questo passaggio è
importante perché si tratta di dati storici che, una volta importati, restano nel sistema —
eventuali correzioni successive richiederebbero interventi manuali sui dati, non un semplice
nuovo caricamento.

**3. Commit — caricamento definitivo**

```
POST /import/historical/commit
```

Stesso file, stesso formato di richiesta del dry-run, ma questa volta la scrittura avviene
sul database reale. La risposta ha la stessa forma del report di dry-run (con `imported` al
posto di `would_import`), così puoi confrontare direttamente i numeri ottenuti con quelli
previsti in anteprima: dovrebbero coincidere, a meno che nel frattempo non sia cambiato lo
stato del database (ad esempio un altro import intermedio).

Anche qui vale la stessa protezione anti-duplicati dell'import mensile: se per qualsiasi
motivo lanci il commit più di una volta (o hai già importato in parte quello stesso storico),
le transazioni già presenti vengono riconosciute e saltate, senza creare doppioni.

---

## Dashboard Metabase

### Come accedervi

Con lo stack avviato (`docker compose up -d`), apri il browser su:

```
http://localhost:3000
```

La porta è configurabile tramite la variabile d'ambiente `METABASE_PORT` (default `3000`) nel file
`.env` — usa quella se l'hai personalizzata.

**Primo accesso**: al primissimo avvio Metabase chiede di creare un account amministratore locale
(nome, email, password) — è l'onboarding standard di Metabase, un'operazione una tantum, tutta in
rete locale (nessun dato lascia la tua LAN, coerente con l'esposizione solo-locale del progetto).
La connessione al database ("Personal Portfolio") è già configurata: punta alla replica read-only
in `/replica/portfolio_replica.db`, non serve aggiungerla a mano. Se in fase di setup Metabase
dovesse chiedertela comunque, seleziona motore **SQLite** e il path indicato sopra.

Nota: la prima partenza del container Metabase può richiedere alcuni minuti (di più su Raspberry
Pi che su un PC/desktop) — è la JVM che si avvia, non un errore. Se il browser non risponde subito,
attendi e ricarica.

### Cosa mostra: dashboard "Personal Portfolio - Overview"

La dashboard principale contiene quattro card:

- **Entrate vs uscite per mese** — confronto mensile tra entrate e uscite, per vedere a colpo
  d'occhio i mesi in attivo o in passivo.
- **Spesa per categoria** — ripartizione della spesa per categoria (es. Alimentari, Trasporti,
  Casa…), utile per capire dove va la maggior parte del budget.
- **Trend saldo cumulato** — andamento nel tempo del saldo cumulato mese su mese, per seguire la
  crescita (o riduzione) del patrimonio nel periodo importato.
- **Saldo per conto** — situazione per singolo conto (es. conto principale, eventuali altri conti
  importati as-is dalle fonti), per sapere quanto è "fermo" su ciascuno.

### Importante: i dati sono su una replica, non in tempo reale

Metabase **non legge mai il database principale** dell'app (quello su cui scrivi importando file o
modificando transazioni). Legge una **copia separata, di sola lettura** ("replica"), che viene
rigenerata automaticamente **solo al completamento di un import** (fine di `import_batch`, mai a
metà scrittura — questo garantisce che la copia sia sempre coerente, mai a metà di
un'operazione).

Cosa significa in pratica:

- Se modifichi/elimini una transazione o assegni una categoria pending dalla UI React, **la
  dashboard Metabase non si aggiorna finché non fai un nuovo import** (anche minimo). Non è un bug:
  è la scelta progettuale per evitare che Metabase tenga aperto/blocchi il database live durante le
  tue operazioni quotidiane.
- **Prima di guardare la dashboard per numeri freschi, fai un import** (anche di un file vuoto/di
  aggiornamento, se disponibile) — questo rigenera la replica. In alternativa, per dati sempre
  aggiornati in tempo reale (incluse modifiche manuali, non solo import), usa la Dashboard della UI
  React del progetto, che legge direttamente il database live.
- Se ti serve solo un controllo veloce e aggiornato senza aspettare un import, preferisci la
  Dashboard React.

### Come filtrare/esplorare

- **Click su una card** (es. una barra del grafico "Spesa per categoria" o un punto del trend) per
  fare drill-down: Metabase apre automaticamente i dati grezzi dietro quel punto (es. le singole
  transazioni di quella categoria/mese).
- Dalla card puoi anche aprire il menu "..." per **scaricare i dati** (CSV/xlsx) o vedere la query
  SQL sottostante.
- Per filtri più avanzati (intervallo di date, per conto, ricerche personalizzate) puoi creare una
  nuova "domanda" (Question) in Metabase partendo dalla tabella `transactions` della replica, oppure
  duplicare/modificare una card esistente. Per l'uso avanzato di Metabase (filtri salvati, nuove
  domande, editor SQL nativo), fai riferimento alla
  [documentazione ufficiale Metabase](https://www.metabase.com/docs/latest/) — le funzionalità
  base di esplorazione (click-through, download, duplicazione card) coprono già la maggior parte
  delle esigenze quotidiane di questo progetto.

---

## Backup e ripristino

### Backup manuale

Puoi avviare un backup in qualsiasi momento chiamando:

```
POST /backup
```

(nessun body richiesto). L'operazione produce, per ogni esecuzione, una coppia di file con lo
stesso timestamp:

- **`portfolio_backup_YYYYMMDD_HHMMSS.db`** — dump completo del database SQLite, ottenuto con
  l'online backup API di SQLite (copia sicura e coerente anche mentre l'app è in uso, nessun
  blocco del database live).
- **`portfolio_backup_YYYYMMDD_HHMMSS.xlsx`** — export "in chiaro" di tutte le transazioni
  (uscite ed entrate) in un unico foglio Excel leggibile con qualsiasi programma, colonne: Data,
  Importo, Valuta, Tipo, Categoria, Conto, Commento, Tag, Fonte.

Entrambi i file vengono salvati:

1. **In locale**, nella cartella `/backups` del container (montata sull'host).
2. **Su Google Drive**, se la Service Account è configurata (vedi sotto), nella cartella
   indicata da `GDRIVE_BACKUP_FOLDER_ID`.

Per vedere l'elenco dei backup locali disponibili:

```
GET /backup
```

Risponde con la lista dei timestamp delle coppie `.db`/`.xlsx` presenti in `/backups`, dal più
recente al più vecchio.

La risposta di `POST /backup` riporta anche l'esito dell'upload su Drive (`drive_uploaded`,
`drive_error`) e i file eventualmente rimossi per rotazione (`local_deleted`, `drive_deleted`) —
utile per verificare a colpo d'occhio se tutto è andato a buon fine.

### Backup automatico all'avvio

Di norma il backup **non** parte da solo: l'unico modo per generarne uno è il pulsante/endpoint
manuale sopra. Se vuoi che l'app esegua un backup ogni volta che si avvia (utile ad esempio prima
di un aggiornamento), imposta nel file `.env`:

```
BACKUP_ON_STARTUP=true
```

Default: `false` (disattivato). Quando attivo, il backup all'avvio gira in background e in modalità
best-effort: se fallisce (es. Drive irraggiungibile), l'errore viene solo loggato e **non** impedisce
l'avvio dell'applicazione.

### Se la Service Account Google Drive non è configurata

L'upload su Drive richiede che il file della Service Account sia montato a runtime in
`/secrets/service_account.json` (mai committato nel repository, vedi [SECURITY.md](SECURITY.md)). Se questo
file manca (o è illeggibile/corrotto), l'upload su Drive viene semplicemente saltato — **il backup
locale viene comunque creato normalmente**. Non è un errore bloccante: la risposta dell'endpoint
segnalerà `"drive_uploaded": false` con una nota nel campo `drive_error`, ma i file `.db`/`.xlsx`
saranno comunque disponibili in `/backups`.

In altre parole: la configurazione di Google Drive è **opzionale** — il backup funziona in locale
anche senza di essa; Drive aggiunge solo una copia di sicurezza fuori sede.

### Retention (rotazione automatica)

Ad ogni backup (manuale o all'avvio), viene applicata una rotazione automatica sia in locale sia
su Drive: si mantengono solo le **`BACKUP_RETENTION`** coppie `.db`+`.xlsx` più recenti (default:
`12`); le coppie più vecchie oltre questo numero vengono cancellate automaticamente. Puoi
modificare il valore impostando `BACKUP_RETENTION` nel file `.env`.

### Restore

**Attenzione: operazione distruttiva e irreversibile.** Il restore sovrascrive completamente il
database live con il contenuto del file di backup scelto. Tutti i dati inseriti dopo la data di
quel backup vengono persi.

Per effettuare un restore:

```
POST /backup/restore
Content-Type: application/json

{
  "filename": "portfolio_backup_20260715_093000.db",
  "confirm": true
}
```

Punti importanti:

- **`filename`** deve corrispondere esattamente a uno dei file `.db` elencati da `GET /backup`
  (formato `portfolio_backup_YYYYMMDD_HHMMSS.db`). Il file viene letto **solo dalla cartella
  locale `/backups`** — il restore non legge mai da Google Drive (Drive è solo una copia di
  sicurezza off-site, la fonte del restore è sempre la copia locale).
- **`confirm: true` è obbligatorio.** Se lo ometti (o lo imposti a `false`), l'endpoint risponde
  con errore `400` e non tocca nulla. Questo campo esiste apposta come "freno a mano" esplicito:
  ti costringe a dichiarare consapevolmente che vuoi sovrascrivere il database live prima che
  l'operazione venga eseguita.
- Se il filename indicato non esiste tra i backup locali, l'endpoint risponde `404` senza
  modificare il database.

**Prima di confermare, verifica con attenzione il timestamp nel nome del file** (`GET /backup` per
consultare l'elenco): una volta eseguito, il restore **non può essere annullato** — l'unico modo
per tornare indietro è, se esiste, un restore successivo da un backup ancora più vecchio (con la
stessa perdita di dati nel frattempo). Dopo il ripristino, il sistema riallinea automaticamente
anche la replica read-only usata da Metabase, così la dashboard torna coerente con il nuovo stato
del database.

---

## Interfaccia React

L'app espone una SPA React (servita dallo stesso container FastAPI, nessuna porta separata) raggiungibile
dalla root del backend (es. `http://localhost:8000/`). Affianca Metabase senza sostituirla: stesso backend,
ma letture **live** sul database (non sulla replica read-only usata da Metabase), così i dati mostrati sono
sempre aggiornati all'ultima transazione importata.

### Pagine disponibili

| Pagina | URL | Scopo |
|---|---|---|
| Dashboard | `/` | Grafici riepilogativi: entrate/uscite mensili, spesa per categoria, saldo cumulato, saldo per conto. |
| Transazioni | `/transazioni` | Elenco paginato delle transazioni, con filtri, modifica e cancellazione. |
| Import | `/import` | Caricamento file mensile "My Finance" e import storico (dry-run + commit). |
| Categorie pending | `/categorie-pending` | Assegnazione manuale delle categorie non riconosciute automaticamente durante l'import. |
| Conti | `/conti` | Elenco conti con possibilità di rinominare il nome visualizzato. |
| Backup | `/backup` | Backup manuale immediato, elenco backup disponibili, restore. |
| Assistente AI | `/assistente-ai` | Domande in linguaggio naturale sui propri dati finanziari (solo lettura, nessuna memoria tra domande). |

### Filtrare le transazioni

Nella pagina Transazioni (`/transazioni`) sono disponibili due filtri, applicati lato server come parametri
della richiesta a `GET /transactions`:

- **Mese** (`year_month`): selettore di tipo mese/anno; filtra le transazioni del mese scelto.
- **Tipo** (`type`): "Tutti i tipi", "Uscite" (`expense`) o "Entrate" (`income`).

L'elenco è paginato (50 righe per pagina) con i pulsanti "Precedente"/"Successiva"; cambiare un filtro
riporta automaticamente alla prima pagina. Da ogni riga si può:

- **Modificare** commento, tag e categoria (unici campi editabili — gli altri, incluso quelli usati per il
  dedup, non sono modificabili da UI);
- **Eliminare** la transazione (operazione distruttiva, vedi conferma a 2 step più sotto).

### Gestire i conti

Nella pagina Conti (`/conti`) è mostrato l'elenco dei conti con il nome sorgente (quello che arriva
dall'import) e il nome visualizzato. Cliccando "Rinomina" si può impostare un nome visualizzato
personalizzato (`display_name`) per rendere l'etichetta più leggibile in dashboard e nell'elenco
transazioni; il nome sorgente originale resta sempre visibile e non viene mai alterato. Non è presente una
funzione di accorpamento conti: ogni conto sorgente resta un'entità distinta, si può solo rinominarne
l'etichetta.

### Leggere gli insight/grafici

La Dashboard (`/`) mostra quattro grafici alimentati da `GET /insights`:

- **Entrate vs uscite (mensile)**: andamento a linee di entrate e uscite mese per mese.
- **Spesa per categoria**: istogramma della spesa totale raggruppata per categoria.
- **Saldo cumulato**: area chart del saldo netto accumulato nel tempo, mese su mese.
- **Saldo per conto**: istogramma orizzontale con il saldo attuale di ciascun conto.

Sono gli stessi aggregati esposti dalle card SQL di Metabase (Fase 3), ricalcolati però al momento della
richiesta sul database live, non sulla replica.

### Conferme a 2 step per azioni distruttive

Le operazioni irreversibili — eliminazione di una transazione e restore di un backup — richiedono sempre
una conferma esplicita a due passaggi in UI (ADR-0019 punto 6, a specchio del `confirm: true` obbligatorio
già imposto lato backend su `/backup/restore`, ADR-0018 punto 5): un primo clic sul pulsante rosso
("Elimina" / "Restore") apre una finestra di dialogo con il dettaglio dell'operazione (data/importo/categoria
per la transazione, timestamp per il backup) e un avviso esplicito di non reversibilità; solo un secondo
clic, dentro la finestra di dialogo, esegue effettivamente la chiamata. In qualunque momento si può annullare
senza effetti.

### Rispetto a Metabase

L'interfaccia React non sostituisce Metabase: sono due UI parallele e indipendenti sullo stesso backend
FastAPI (ADR-0004, ADR-0019). Metabase continua a leggere dalla replica read-only del database (aggiornata
periodicamente) ed è pensata per l'esplorazione dashboard/BI più avanzata; l'interfaccia React legge invece
sempre i dati live e aggiunge le funzioni di scrittura (modifica/cancellazione transazioni, resolve categorie
pending, rename conti, trigger backup/restore) che Metabase, essendo solo di lettura, non offre.

---

## Query AI in linguaggio naturale

Puoi fare domande in italiano sulle tue finanze e ricevere una risposta calcolata a partire dai
tuoi dati reali, non generata a memoria dal modello.

### Come attivarla

La funzione è **disattivata di default**. Per accenderla, imposta in `.env` (mai nel repository)
tre variabili:

- `AI_PROVIDER` — il provider AI da usare (oggi supportato solo `gemini`);
- `AI_API_KEY` — la tua chiave personale del provider scelto, ottenibile dal sito del provider
  stesso;
- `AI_MODEL` — l'identificativo del modello (es. una linea "flash-lite"), con un default già
  proposto in `.env.example`.

La chiave è **tua**: il progetto non fornisce né usa una chiave propria, e la spesa/uso del
provider è a tuo carico secondo le condizioni d'uso che accetti registrandoti. Se `AI_PROVIDER` è
vuoto o la chiave manca, l'assistente resta semplicemente disattivo: il resto dell'app funziona
esattamente come sempre.

### Come si usa

Dal menu apri la pagina **Assistente AI** (`/assistente-ai`). Scrivi la domanda nel campo di testo
e premi "Chiedi". Ogni domanda è indipendente: l'assistente non ricorda le domande precedenti,
quindi se serve contesto va ripetuto nella domanda stessa.

Per un uso diretto via riga di comando (o da script), lo stesso endpoint è raggiungibile con:

```bash
curl -X POST http://localhost:8000/ai/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Quanto ho speso in alimentari negli ultimi 3 mesi?"}'
```

### Cosa puoi chiedere

L'assistente legge transazioni, conti, categorie e aggregazioni già calcolate dal database.
Esempi di domande realistiche:

- "Quanto ho speso a marzo?"
- "Quali sono le mie entrate totali quest'anno?"
- "Quanto ho speso in alimentari negli ultimi 3 mesi?"
- "Qual è il saldo del conto principale?"
- "Quali sono le categorie di spesa più alte del 2026?"
- "Trovami le transazioni sopra i 200 euro sul conto corrente a gennaio."

### La traccia dei tool: perché è sempre mostrata

Sotto la risposta trovi sempre un riquadro "Tool utilizzati", con il nome di ogni tool chiamato,
gli argomenti (filtri) usati e un riassunto del risultato. Non è un dettaglio tecnico opzionale:
i modelli linguistici possono sbagliare l'aritmetica o interpretare male un filtro, quindi ogni
numero che vedi in risposta deve restare **ricontrollabile** — puoi verificare da quali dati e con
quali filtri è stata costruita la risposta, invece di doverti fidare a scatola chiusa.

### Garanzia: sola lettura

L'assistente **non può mai scrivere** sul database. Tutti i tool disponibili (`list_transactions`,
`get_insights`, `get_accounts`, `get_categories`) eseguono solo letture: nessuno di essi può
inserire, modificare o cancellare transazioni, conti o categorie. Se in futuro verrà introdotta una
funzione di scrittura assistita da AI, sarà un'altra fase del progetto, con una decisione
documentata a parte e approvazione umana esplicita per ogni modifica.

### Nota privacy

Quando invii una domanda, il backend può interrogare il database e passare i risultati al
provider AI per costruire la risposta. Questi risultati possono includere le **note libere che hai
scritto tu** nei campi commento e tag delle transazioni (utile per rispondere a domande tipo
"quanto ho speso per il regalo di X", ma può contenere dettagli personali). Questo invio avviene
**solo quando premi "Chiedi"**, mai in background o in automatico. Per il dettaglio completo su
cosa esce dalla rete locale, verso chi e come rendere il flusso più restrittivo, vedi
[SECURITY.md](SECURITY.md).

### Se non è configurata

Se provi a usare l'assistente senza aver impostato `AI_PROVIDER`/`AI_API_KEY`/`AI_MODEL`, ricevi un
errore esplicito e comprensibile invece di un malfunzionamento silenzioso o un crash. Il resto
dell'applicazione (transazioni, insight, backup, dashboard) continua a funzionare senza alcuna
limitazione: l'assistente AI è un componente opzionale, non una dipendenza del resto del sistema.

---

## Comandi utili da CLI

```bash
# Health check backend
curl http://localhost:8000/health

# Log dei container (utile per diagnosticare avvio lento/errori)
docker compose logs -f backend
docker compose logs -f metabase

# Stato/salute dei container
docker compose ps

# Migrazioni Alembic (dentro il container backend)
docker compose exec backend alembic upgrade head
docker compose exec backend alembic revision -m "descrizione"   # ogni schema change (ADR-0003)

# Riavvio dopo modifiche al codice
docker compose up -d --build

# Query AI via CLI (se configurata, vedi sopra)
curl -X POST http://localhost:8000/ai/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Quanto ho speso questo mese?"}'
```
