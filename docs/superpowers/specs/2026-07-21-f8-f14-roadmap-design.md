# F8–F14 — Roadmap: design spec

- **Status**: Approvata — 2026-07-21
- **Copre**: F8 dark mode · F9 settings · F10 backup GDrive + test · F11 inserimento manuale ·
  F12 filtri avanzati · F13 dashboard avanzate · F14 storicità chat AI
- **ADR prodotti**: 0026 → 0032 (`docs/DECISIONS.md`)
- **Non copre**: F7 Raspberry Pi, che resta ◐ parcheggiata e intatta

Questa è una **roadmap**: fissa decisioni, vincoli e milestone per tutte e 7 le fasi. Ogni blocco
produrrà la propria spec di dettaglio e il proprio piano implementativo quando parte, come hanno
fatto F5/F6/F7. Non sostituisce quei documenti: li precede.

---

## 1. Contesto

F0–F6 e F-DEBT sono chiuse. F7 è preparata e verificata da desktop, ferma in attesa dell'hardware
(Pi 4 4GB). Servono 7 funzionalità nuove che oggi non hanno né piano né ADR:

| Fase | Cosa manca oggi |
|---|---|
| F8 | Nessun tema scuro: `tailwind.config.js` non dichiara `darkMode`, `index.css` è 3 righe |
| F9 | Nessun punto di configurazione in UI; nessuna tabella `settings` |
| F10 | Il backup su Drive esiste ma è verificabile solo eseguendo un backup vero |
| F11 | Nessun modo di registrare una transazione senza importare un file |
| F12 | `GET /transactions` filtra solo per mese, categoria, conto, tipo |
| F13 | Una sola pagina Dashboard con 4 grafici e colori fissi |
| F14 | L'assistente AI è stateless: ogni domanda parte da zero (ADR-0023 p.6) |

**F7 resta intatta.** Nessuna riga di `docs/RASPBERRY-PI.md`, di ADR-0024/0025 o del compose viene
toccata da questa roadmap. F7 è annotata ovunque come *da sviluppare successivamente, in attesa
hardware*, non riordinata rispetto a F8+.

---

## 2. Fatti verificati nel repo

La roadmap nasce da un inventario del codice, non da assunzioni. I fatti che l'hanno cambiata:

| Fatto | Evidenza | Conseguenza |
|---|---|---|
| `POST /transactions` **non esiste** | `backend/app/routers/transactions.py:36-109` — solo GET/PUT/DELETE | F11 è un endpoint nuovo, non un'estensione |
| Nessuna tabella `settings` | `backend/app/models.py:1-6` — 6 modelli, la docstring la dichiara rimandata | F9 richiede una revision Alembic |
| `hash_dedup` ha **unique constraint** | `backend/app/models.py:104` | un duplicato manuale forzato non può riusare lo stesso hash |
| `source` è stringa libera | `backend/app/models.py:102` — nessun CheckConstraint | il valore `manual` non richiede migrazione |
| `import_batch_id` nullable, `category_raw` NOT NULL | `backend/app/models.py:98-103` | inserimento manuale: batch NULL, `category_raw` obbligatorio |
| 31 classi colore hardcoded su 11 file, 5 hex nei grafici | `frontend/src/pages/Dashboard.tsx:44-84` | superficie di conversione F8 nota e finita |
| shadcn adottata a metà | `lib/utils.ts` + `cva` + 2 componenti, **nessun `components.json`** | i componenti si portano a mano, la CLI non è inizializzata |
| Recharts **^3.9.2**, Tailwind **3.4.19**, React **19.2.7** | `frontend/package.json` | Recharts è già alla major che usa `var(--chart-N)` |
| `AIProvider.answer(question, session)` | `backend/app/routers/ai.py:76` | F14 cambia la firma di un contratto astratto |
| Drive: scope `drive.file`, timeout 30s | `backend/app/drive.py:16-27` | con quello scope una `list` non prova il permesso di scrittura |
| Env reali: `GDRIVE_BACKUP_FOLDER_ID`, `GOOGLE_SA_KEY_PATH`, `AI_API_KEY` | `backend/app/config.py`, `.env.example` | **`GOOGLE_API_KEY` non esiste** e non va introdotta (ADR-0023 p.3) |

---

## 3. Decisioni

1. **Settings ibrido** — tabella `settings` in SQLite = fonte di verità; localStorage = cache del
   solo tema, necessaria allo script anti-FOUC.
2. **Dark mode su Tailwind v3** — `darkMode: 'class'` + token semantici CSS. **Nessuna migrazione a
   v4**: sarebbe un cambio di build system in mezzo a 7 feature, con rischio su F7.
3. **"Patrimonio netto" non esiste nel dato** — si mostra il **saldo cumulato** transazionale, con
   l'etichetta corrispondente. Nessun modello asset/passività.
4. **AI: storico chat + finestra di contesto troncata** — nessun RAG vettoriale.
5. **Full-text con SQLite FTS5** (tabella virtuale + trigger), non `LIKE`.
6. **Duplicato manuale**: 409 con la transazione gemella, forzabile con conferma esplicita.
7. **Test GDrive**: probe reale write → read → delete.
8. **3 blocchi tematici, un branch ciascuno.**

Quattro punti restano deliberatamente **non decisi** perché dipendono da misure che solo il Pi reale
può produrre: sezione 9.

---

## 4. Struttura in blocchi

| Blocco | Branch | Fasi | Alembic | Agenti |
|---|---|---|---|---|
| **A — Fondamenta UI** | `f8-f9-theme-settings` | F8, F9 | `settings` | react-ui-agent, schema-agent |
| **B — Superficie transazioni** | `f11-f12-f13-transactions` | F11, F12, F13 | FTS5 | react-ui-agent, schema-agent, dashboard-agent |
| **C — Integrazioni** | `f10-f14-drive-chat` | F10, F14 | chat | backup-agent, ai-agent, schema-agent |

Ordine vincolante: **A prima di B** — F12 e F13 consumano i token colore di F8 e la pagina di F9.

C è indipendente **a livello funzionale** (non consuma nulla di B) ma **non** a livello di catena
Alembic: vedi la regola di rebase in sezione 7.

---

## 5. Blocco A

### F8 — Dark mode globale

- **M8.1 — Token semantici.** `frontend/src/index.css` guadagna un `@layer base` con `:root` e
  `.dark`: `--background --foreground --card --card-foreground --muted --muted-foreground --border
  --input --ring --primary --destructive --success --chart-1 … --chart-5`, in formato HSL triplo
  (sintassi Tailwind v3). `tailwind.config.js`: `darkMode: 'class'` più `theme.extend.colors` che
  mappa i token a utility (`bg-background`, `text-foreground`, `border-border`).
- **M8.2 — ThemeProvider e anti-FOUC.** Context React (`light | dark | system`), classe su
  `document.documentElement`, listener su `matchMedia('(prefers-color-scheme: dark)')`. Script
  inline in `frontend/index.html` che legge localStorage e applica la classe **prima** del bundle:
  senza, ogni caricamento lampeggia bianco.
- **M8.3 — Conversione della superficie esistente.** Le 31 classi hardcoded sugli 11 file diventano
  token semantici. `components/ui/button.tsx` e `alert-dialog.tsx` per primi: sono i più riusati.
- **M8.4 — chartConfig condiviso.** Nuovo `frontend/src/lib/chart-config.ts`: palette, `stroke` e
  `fill` per serie, valori di `tick`/`grid`/`tooltip` letti da `getComputedStyle`. I 5 hex di
  `Dashboard.tsx` spariscono. Il componente `chart` di shadcn (`ChartContainer`, `ChartTooltip`) si
  porta a mano in `components/ui/`, senza inizializzare la CLI.

**Milestone F8** — tutte e 7 le pagine esistenti navigate in dark e in light senza un solo elemento
illeggibile; grafici leggibili su nero; nessun flash bianco al reload; toggle persistente.

### F9 — Pagina Settings centralizzata

- **M9.1 — Schema.** Tabella `settings`: `key TEXT PK`, `value TEXT`, `updated_at`. Key/value e non
  colonne tipizzate, così ogni impostazione futura è un INSERT e non una migrazione.
- **M9.2 — Endpoint.** `GET /settings` restituisce le sole chiavi in whitelist più un blocco
  `secrets_status` con `{configured: bool}` per ciascun secret — **mai il valore**. `PUT /settings`
  accetta solo chiavi in whitelist. Precedenza: **DB > env > default**; env resta il bootstrap.
- **M9.3 — Whitelist iniziale e momento di applicazione.**

  | Chiave | Quando ha effetto |
  |---|---|
  | `theme` | immediato |
  | `metabase_url` | immediato (solo destinazione del link) |
  | `ai_history_max_turns` | immediato, dalla domanda successiva |
  | `import_min_year` | immediato, dal prossimo import |
  | `backup_retention` | immediato, dal prossimo backup |
  | `backup_on_startup` | **solo al boot successivo** |

  L'indicazione compare accanto al campo nella UI, non solo nell'ADR: è la differenza fra
  un'impostazione che funziona e un utente convinto che l'app ignori i suoi salvataggi. Ogni chiave
  aggiunta in futuro entra in whitelist **con la sua riga in questa tabella**.

  `metabase_url` è **solo la destinazione del link** mostrato dalla UI. Il servizio resta definito in
  `docker-compose.yml`: cambiarlo da `/settings` non riconfigura né riavvia nulla, serve a puntare a
  un'istanza su host o porta diversi (tipicamente il Pi).
- **M9.4 — Blacklist permanente.** Mai leggibili né scrivibili da API o UI: `AI_API_KEY`,
  `GOOGLE_SA_KEY_PATH`, `GDRIVE_BACKUP_FOLDER_ID`, e qualunque chiave futura che sia un segreto o un
  identificatore di risorsa privata. Test automatico che fallisce se una chiave blacklistata compare
  nella risposta di `GET /settings`.
- **M9.5 — Pagina `/settings`** (ottava route): sezioni Aspetto · Dashboard esterne · Parametri ETL ·
  Backup · AI. Ogni secret compare come badge "configurato / non configurato" con la riga `.env` da
  usare, mai come campo di input.

**Milestone F9** — la preferenza tema salvata sul DB sopravvive al cambio di browser; nessun valore
di secret è ottenibile da alcun endpoint; test di blacklist verde.

---

## 6. Blocco B

### F11 — Inserimento manuale transazione

- **M11.1 — `POST /transactions`.** Body: `date, amount, currency, type, category_id, account,
  comment, tag`. Il backend deriva `category_raw` dal nome della categoria canonica scelta, imposta
  `source='manual'` e `import_batch_id=NULL`. **Nessuna revision Alembic**: nessuna colonna nuova.
- **M11.2 — Dedup e duplicato consapevole.** Hash calcolato con la formula invariata di
  ADR-0005/0013. Se esiste già → **409** con la transazione gemella nel corpo. Reinvio con
  `allow_duplicate: true` → si scrive `hash_dedup = <hash>#<n>`, con `n` ordinale della ripetizione.

  Il suffisso serve a **convivere** con l'unique constraint senza modificarlo: stringhe diverse,
  nessuna violazione, nessuna migrazione. Corollario vincolante: **l'importer confronta sempre
  l'hash base, mai il suffisso** — una riga forzata non partecipa al dedup degli import e non ne
  altera l'idempotenza.

  **Chi calcola `n`, e sotto quale lock.** Leggere l'ordinale e poi scrivere in due passi separati è
  una race: due invii ravvicinati leggono entrambi "nessun `#n` esiste", scrivono entrambi `#1`, il
  secondo esplode con `IntegrityError`. Raro in single-user, non impossibile (doppio click, retry
  del browser), e visibile solo in produzione. Lettura dell'ordinale e insert avvengono nella
  **stessa transazione serializzata** (`BEGIN IMMEDIATE`, che prende il lock di scrittura subito e
  non alla prima INSERT), coerente con FastAPI unico writer (ADR-0004). Come cintura, retry
  idempotente: `IntegrityError` su `hash_dedup` → ricalcolo di `n`, un solo nuovo tentativo, poi 409.
- **M11.3 — Validazione doppia.** Pydantic lato backend (importo > 0, `type` in `expense|income`,
  data non futura oltre soglia); stessi vincoli nel form React, con errori per campo.

  **Ordine vincolante**: il `category_id` ricevuto va verificato esistente con una **lookup
  esplicita → 404 se assente**, e solo dopo si deriva `category_raw`. Invertire i due passi produce
  `category_raw = None` su una colonna NOT NULL (`models.py:98`): l'errore emerge come
  `IntegrityError` al commit, cioè un **500 opaco** invece di un 404 che dice quale categoria manca.
  Pydantic non copre questo caso — valida il tipo dell'intero, non la sua esistenza nel DB.
- **M11.4 — Form React** in `/transazioni`, con invalidazione TanStack Query di transazioni e
  insights.

**Milestone F11** — la transazione inserita a mano compare in lista, dashboard e Metabase (dopo
refresh replica); doppio invio identico → 409; forzatura → due righe distinte; re-import di un file
che contiene la stessa riga → nessun duplicato aggiuntivo.

### F12 — Filtri avanzati e ricerca full-text

- **M12.0 — Gate arm64, prerequisito bloccante del merge del blocco.** F12 arriva *prima* della
  chiusura di F7 sul Pi. Se l'SQLite dell'immagine arm64 non avesse FTS5, la migrazione fallirebbe
  al primo `docker compose up` sul Raspberry, rompendo **il deploy** e non solo la ricerca. Verifica
  con lo stesso metodo del gate F7 (ADR-0024 p.2): `docker buildx build --platform linux/arm64
  --load`, poi nel container emulato `SELECT fts5_version();` deve rispondere. Se fallisce, il
  Blocco B **non si mergia**: si torna a `LIKE` e si riapre la decisione.
- **M12.1 — Schema.** Tabella virtuale FTS5 `transactions_fts` su `comment`, `tag`, `category_raw`
  (content-table sincronizzata), più tre trigger INSERT/UPDATE/DELETE e il popolamento iniziale
  nella migrazione stessa. Due guardrail obbligatori: (a) check fail-fast all'avvio che l'SQLite del
  container abbia FTS5 compilato, con errore esplicito se assente; (b) **rebuild dell'indice dopo
  `POST /backup/restore`**, perché il restore sovrascrive il file DB (ADR-0018 p.5) e l'indice
  resterebbe incoerente — una ricerca che mente in silenzio.
- **M12.2 — Filtri su `GET /transactions`**: `date_from`, `date_to`, `category_id`, `account`,
  `amount_min`, `amount_max`, `type`, `q` (full-text). `year_month` resta per compatibilità.
- **M12.3 — Raggruppamento**: `group_by=category|month|account`, con intestazioni di gruppo e
  subtotali, senza rompere la paginazione esistente (ADR-0020: ordinamento `date desc, id desc`).
- **M12.4 — URL come stato.** I filtri vivono in `useSearchParams` (React Router è già presente,
  nessuna dipendenza nuova) e alimentano la `queryKey` di TanStack Query. Ogni configurazione di
  filtri diventa un permalink incollabile.

**Milestone F12** — la ricerca testuale trova una transazione per una parola nel commento; ogni
filtro è riflesso nell'URL e il reload lo ripristina; il restore di un backup non rompe la ricerca.

### F13 — Dashboard avanzate

Pannelli, tutti sul `chartConfig` condiviso di F8 e sugli aggregati di `services/insights.py`:

| Pannello | Grafico | Nota |
|---|---|---|
| Saldo cumulato | area / line | etichetta letterale **"Saldo cumulato"** |
| Cash flow mensile | barre entrate/uscite affiancate + linea netto | finestra scorrevole 12 mesi |
| Spese per categoria | **donut** (top 6 + "altro") | vedi nota sulla soglia treemap |
| Trend risparmio | line su % risparmio = (entrate − uscite) / entrate | |
| Confronto mese su mese | barre affiancate + delta % | |
| KPI cards | 4 numeri in cima | entrate, uscite, netto, tasso di risparmio |

La parola "patrimonio" è **vietata** in UI, tooltip, titoli e nomi di campo API: il dato non lo è, e
un'approssimazione fra parentesi diventa comunque la dicitura che l'utente legge.

La soglia "treemap solo oltre ~15 categorie" è una **nota di design**, non una condizione da
scrivere nel codice: nessun `if` che cambi tipo di grafico a runtime, nessun test che la verifichi.
Oggi si implementa il donut.

- **M13.1 — Estensione di `backend/app/services/insights.py`**, lo stesso modulo creato in F6
  (ADR-0023 p.5): si aggiungono le aggregazioni mancanti riusando i filtri già presenti. **Nessun
  secondo service layer, nessun SQL duplicato.**

  Criterio di accettazione: le firme esistenti restano **backward-compatible** — parametri nuovi
  solo come argomenti opzionali con default, mai riordinati, mai rinominati. I 5 test F5 su
  `GET /insights` senza parametri devono passare **invariati, senza una riga toccata**: se serve
  modificarli, è la firma ad essere rotta ed è la firma a tornare indietro.

  Il tool `get_insights` del registry AI entra nello **stesso criterio di merge**: è il secondo
  consumatore di quelle funzioni ed è silenzioso — una firma rotta lì non fallisce a compile time,
  fallisce la prima volta che il modello chiama il tool, cioè in produzione.
- **M13.2 — Pannelli React.** Metabase resta **invariata**: ADR-0004 e ADR-0019 non sono superati.

**Milestone F13** — ogni numero mostrato quadra con i totali noti del dataset F2 (331 transazioni,
uscite 9937.70 €, entrate 19497.14 €); tutti i pannelli leggibili in dark.

---

## 7. Blocco C

### F10 — Backup GDrive e test di connettività

- **M10.1 — `POST /backup/gdrive-test`.** Probe reale: crea un file di pochi byte nella cartella
  configurata, lo rilegge per id, lo cancella. Con scope `drive.file` la Service Account vede solo i
  file creati da sé, quindi una semplice `list` non dimostra nulla sul permesso di scrittura: il
  probe è l'unico test onesto.

  L'endpoint legge `GDRIVE_BACKUP_FOLDER_ID` e `GOOGLE_SA_KEY_PATH` **internamente da `config.py`**:
  non li accetta nel body e non li restituisce nella risposta, nemmeno parzialmente, nemmeno dentro
  un messaggio d'errore.
- **M10.2 — Esiti diagnostici distinti**, non un generico "errore": Service Account non montata,
  JSON malformato, `GDRIVE_BACKUP_FOLDER_ID` mancante, cartella non condivisa (404), permesso
  insufficiente (403), quota, timeout.

  Il messaggio di Google viene riportato **dopo sanitizzazione**, perché l'errore per una cartella
  inesistente contiene proprio l'id blacklistato. Meccanismo: (a) il messaggio si costruisce dai
  **campi strutturati** di `googleapiclient.errors.HttpError` (`resp.status`, `reason`), non da
  `str(exc)`, che è il posto dove l'id finisce; (b) qualunque stringa che esca comunque passa da
  **una sola** funzione di redazione che fa `str.replace` **letterale** dei valori noti letti da
  `config`, non una regex euristica che indovina cosa somiglia a un id e sbaglia in entrambe le
  direzioni; (c) test che chiama l'endpoint con un folder_id fasullo e asserisce che quella stringa
  non compaia in nessun punto della risposta.
- **M10.3 — Pulsante "Test connessione GDrive"** nella pagina Backup, con esito e dettaglio. Il
  `folder_id` non è mai mostrato né modificabile.
- **M10.4 — Pulizia best-effort, non garanzia.** Nome deterministico
  `portfolio_gdrive_probe_<YYYYMMDD_HHMMSS>.probe`, con prefisso **distinto** da `BACKUP_PREFIX`
  così che la retention dei backup non lo tocchi mai e viceversa. Se la creazione riesce e la
  lettura va in timeout, il backend potrebbe non riuscire nemmeno a cancellare: il test **fallisce
  con l'errore reale** (non lo maschera), la cancellazione è tentata comunque in un `finally`, e
  ogni esecuzione **inizia** rimuovendo gli orfani che matchano il prefisso. Un residuo su Drive non
  è un fallimento dell'app — stesso spirito non-bloccante di ADR-0018 p.3/p.4.

**Milestone F10** — con Service Account valida: esito verde e nessun residuo su Drive; con cartella
non condivisa: messaggio che nomina la causa e rimanda alla procedura di `docs/SECURITY.md`.

### F14 — Storicità chat AI e memoria

- **M14.1 — Schema.** `chat_sessions (id, title, created_at, updated_at)` e `chat_messages (id,
  session_id FK, role, content, tools_json, created_at)`, con indice su `(session_id, created_at)`.

  **Formato di `tools_json` fissato ora**, prima dell'implementazione: è il tipo di dettaglio che,
  deciso implicitamente da chi scrive per primo, diventa costoso da cambiare perché i dati storici
  sono già nel formato sbagliato. Colonna **TEXT** con una stringa JSON (`json.dumps`) il cui
  contenuto è la **stessa lista di oggetti già restituita da `POST /ai/query`** —
  `[{"name": …, "args": {…}, "result_summary": …}]` (`backend/app/routers/ai.py:82-85`). Un solo
  shape in tutto il sistema: risposta API, riga di DB e rendering della traccia leggono la stessa
  struttura. `NULL` per i messaggi `role="user"`. Nessuna tabella `chat_tool_calls`: sarebbe
  normalizzazione di un payload che non viene mai interrogato per campo, solo riletto intero.
- **M14.2 — Contratto provider.** `AIProvider.answer(question, session, history=None)`. L'adapter
  Gemini antepone le ultime `ai_history_max_turns` coppie (default 6). La finestra è **troncata, mai
  illimitata**: costo e latenza dipendono da qui.

  È un **breaking change** su una classe astratta, e `history=None` con default fa compilare tutto
  senza fallire — una regressione qui sarebbe silenziosa. **Ordine dei task obbligatorio**:

  1. aggiornare il **fake provider dei test** perché registri la `history` ricevuta **e il suo
     numero di elementi**, e scrivere il test che asserisce l'arrivo delle ultime N coppie — **il
     test deve fallire qui**, ed è l'unico momento in cui si vede che sta misurando qualcosa. Il
     conteggio serve a separare due responsabilità: il **router** carica dal DB e passa la
     conversazione, l'**adapter** applica il cap. Registrando solo il contenuto, un troncamento
     fatto per sbaglio nel router passerebbe inosservato e ogni adapter futuro erediterebbe un
     limite che non è suo. Due test distinti: (a) sul fake, la history arriva **completa** dal
     router; (b) sull'adapter Gemini in isolamento, la history lunga viene troncata **prima** della
     chiamata al provider;
  2. solo dopo, cambiare la firma su `AIProvider` astratto e sull'adapter → il test diventa verde;
  3. infine router, persistenza e UI.
- **M14.3 — Endpoint.** `POST /ai/query` accetta `session_id` opzionale (assente → nuova sessione);
  `GET /ai/sessions` (elenco), `GET /ai/sessions/{id}` (messaggi). Due cancellazioni distinte:
  - `DELETE /ai/sessions/{id}` — una sola conversazione, **nessun `confirm`**: la perdita è
    circoscritta e l'utente ha appena scelto quale riga colpire;
  - `DELETE /ai/sessions` — **azzera tutto lo storico**, con `confirm: true` obbligatorio nel body.
    È l'endpoint dietro il pulsante "Azzera storico". Qui la conferma serve perché non c'è modo di
    ricostruire cosa è andato perso.
- **M14.4 — UI.** `/assistente-ai` guadagna elenco sessioni, ripresa conversazione e "Azzera
  storico" con conferma a 2 step. La traccia dei tool resta sempre visibile (ADR-0023 p.11).
- **M14.5 — Vincolo invariato.** Nessun tool di scrittura è raggiungibile dal modello. La
  persistenza è scritta **dal router**, mai da un tool. Test di regressione che scandisce il registry.

FTS5 di F12 renderebbe banale un tool `search_transactions` read-only: registrato come evoluzione,
**fuori scope qui**.

**Milestone F14** — una domanda di follow-up ("e il mese prima?") riceve risposta corretta usando il
contesto; la conversazione si riprende dopo il riavvio del container; l'azzeramento cancella tutto;
il conteggio transazioni resta invariato a fine sessione.

---

## 8. Migrazioni Alembic

| Blocco | Contenuto | Rischio |
|---|---|---|
| A | `settings` (key PK, value, updated_at) | nullo, tabella nuova |
| B | `transactions_fts` FTS5 + 3 trigger + popolamento | medio: dipende da FTS5 compilato — chiuso dal gate M12.0 |
| C | `chat_sessions`, `chat_messages` + indice | nullo, tabelle nuove |

Ogni revision con `downgrade` funzionante e test di round-trip. **F11 e F13 non producono revision.**

**Regola sulla catena.** Il Blocco C è indipendente *funzionalmente*, ma la catena Alembic è lineare
per costruzione. Se C viene sviluppato mentre B non è ancora mergiato, la sua revision nascerebbe
con `down_revision` puntato alla head di A, e al merge di entrambi si otterrebbe un **branch
Alembic**: `alembic upgrade head` fallisce con head multiple, e la rottura si scopre al primo avvio
del container, non in sviluppo.

Quindi: **numero e `down_revision` si fissano al momento del merge, non alla scrittura.** Chi mergia
per secondo rebasa la propria revision sulla head reale. Verifica obbligatoria prima di ogni merge:
`alembic heads` → **una sola riga**, `alembic upgrade head` su DB pulito, `downgrade` fino a `0002`.

---

## 9. Punti aperti dipendenti dall'hardware Raspberry

Restano **pending per scelta**: dipendono da misure che solo il Pi reale può produrre, e deciderli
ora significherebbe indovinare. Vanno riportati all'utente quando l'hardware arriva.

| # | Punto aperto | Perché non si decide ora | Cosa lo sblocca |
|---|---|---|---|
| **P1** | Se Metabase viene fermata sul Pi (ADR-0025, Modello A), le dashboard React di F13 smettono di essere complementari e diventano l'unica superficie analitica: ADR-0030 andrebbe rivisto | Dipende dalle soglie di ADR-0025 (avvio ≤ 10 min, RAM ≤ 1.5GB, warm < 10s) | Checklist parte 2 di `docs/RASPBERRY-PI.md` |
| **P2** | Copertura funzionale minima di F13 se P1 si verifica: replicare le card SQL native di F3, o accettare di perderle | Discende da P1 | Esito di P1 + scelta utente |
| **P3** | Costo dei nuovi pannelli e del bundle su Pi 4 4GB: nessuna soglia di performance frontend è mai stata definita per questo progetto | Non misurabile da desktop | Sessione-Pi |
| **P4** | Punto di rientro di F7 rispetto a F8–F14: se l'hardware arriva a Blocco B in corso, F7 si inserisce subito o attende il merge | Priorità dell'utente, non scelta tecnica | Arrivo dell'hardware |

**Non è pending** il rischio FTS5 su arm64: lo chiude in anticipo il gate M12.0, bloccante per il
merge del Blocco B proprio perché non può aspettare il Pi.

---

## 10. Verifica

**Per blocco, prima del merge:**

- `alembic heads` → una sola head; `alembic upgrade head` e `downgrade` fino a `0002` su DB di prova.
- Suite pytest completa (oggi 100 test) verde, più i nuovi: blacklist settings, dedup manuale
  409/forzatura, filtri e full-text, guardrail read-only AI dopo la persistenza.
- Build del container di produzione e navigazione reale delle pagine — non solo dev server — in
  **dark e light**, con console pulita.
- Numeri incrociati contro i totali noti del dataset F2 su ogni pannello nuovo.
- `docker compose config` valido, `/health` con `phase` aggiornata.

**Gate bloccanti specifici:**

- **Blocco B** — M12.0: build `linux/arm64` e `SELECT fts5_version()` nel container emulato.
- **Blocco C** — (a) evidenza documentata che il fake provider registra la `history` **prima** del
  cambio di firma, col relativo passaggio rosso→verde; (b) suite verde **dopo** il cambio di firma.
  Senza (a), (b) non dimostra nulla: la suite resterebbe verde perché `history=None` assorbe ogni
  chiamata, e il merge passerebbe per il motivo sbagliato.

**Manuale, una volta:** test GDrive con Service Account reale e cartella condivisa (esito verde,
nessun residuo) e con cartella non condivisa (messaggio diagnostico corretto e **privo del
folder_id**).

---

## 11. Fuori scope

Asset e passività per il patrimonio netto reale · RAG vettoriale · tool `search_transactions` per
l'AI · categorizzazione AI delle pending (sottosistema write, spec propria) · migrazione Tailwind v4
· auth e reverse proxy (ADR-0009 invariato) · **tutto F7**, che riprende su hardware reale con il
runbook già pronto.
