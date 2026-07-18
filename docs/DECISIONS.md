# Architecture Decision Records — Personal Portfolio

Registro delle decisioni architetturali (ADR). **Secondo cervello del progetto**: ogni scelta
non ovvia va qui, con contesto e conseguenze. Ogni fase aggiunge i propri ADR **prima** di
scrivere codice. Non modificare un ADR passato: se cambia, aggiungine uno nuovo che lo supera
(status `Superseded by ADR-XXXX`).

## Template

```
## ADR-XXXX — <Titolo>
- Status: Proposed | Accepted | Superseded by ADR-YYYY
- Fase: F<n>
- Data: YYYY-MM-DD
- Contesto: <perché serve una decisione>
- Decisione: <cosa si è deciso>
- Conseguenze: <trade-off, cosa diventa più facile/difficile>
```

---

## ADR-0001 — SQLite (WAL) come sorgente di verità canonica
- Status: Accepted — Fase: F0 — Data: 2026-07-12
- Contesto: single-user, deploy one-click su Windows e Raspberry, no server DB dedicato.
- Decisione: SQLite file singolo in **WAL mode** come store canonico. FastAPI = unico writer.
- Conseguenze: backup = copia file; niente overhead server; WAL abilita reader concorrenti sicuri
  (necessario per la replica Metabase). Non adatto a scritture multi-processo → un solo writer.

## ADR-0002 — Backend Python + FastAPI
- Status: Accepted — Fase: F0 — Data: 2026-07-12
- Contesto: ETL finanziario (parsing .xlsx, un-pivot, dedup) + futuro layer AI, mantenuto da solo dev.
- Decisione: Python + FastAPI; pandas/openpyxl per ETL.
- Conseguenze: un solo linguaggio, ecosistema dati/AI maturo; niente stack JS backend da mantenere.

## ADR-0003 — Alembic come migration tool
- Status: Accepted — Fase: F0 — Data: 2026-07-12
- Contesto: lo schema evolve per fase (F1 `category_pending`, F4 `settings`…). Modifiche manuali al DB = fragili.
- Decisione: Alembic (già nello stack Python). Ogni fase che tocca lo schema produce una revision versionata.
- Conseguenze: schema riproducibile e migrabile; nessun `ALTER TABLE` manuale non tracciato.

## ADR-0004 — Metabase disaccoppiato via replica read-only atomica + versione pinnata
- Status: Accepted — Fase: F0 (attivazione F3) — Data: 2026-07-12
- Contesto: Metabase che apre il file SQLite live in scrittura è un antipattern (lock/corruzione durante import).
- Decisione: Metabase legge SOLO una **replica read-only**. FastAPI genera la replica con
  `shutil.copy2(db_live, db_replica)` **al completamento di ogni `import_batch`**, mai mid-write
  (WAL garantisce consistenza point-in-time durante la copia file). Immagine Metabase **pinnata**
  (es. `v0.50.30`), mai `latest`; aggiornare solo con backup preventivo + lettura changelog.
  Alternativa aperta: se Metabase pesa troppo su Raspberry, saltarlo e anticipare la UI React (F5).
- Conseguenze: zero contesa file durante import; dashboard leggermente ritardate (post-batch), accettabile.

## ADR-0005 — Dedup hash su campi stabili
- Status: Accepted — Fase: F0 (uso F1) — Data: 2026-07-12
- Contesto: re-import dello stesso mese non deve creare duplicati; hash su campi editabili genererebbe falsi nuovi.
- Decisione: `hash_dedup` = hash di `(date_troncata_al_giorno, amount, category, account, type)`.
  **Contratto immutabile**: mai includere campi editabili post-import (`comment`, `tag`, timestamp con secondi).
- Conseguenze: idempotenza degli import; modifica di note/tag non duplica la transazione.

## ADR-0006 — Categorie con reconciliation queue; Conti importati as-is
- Status: Accepted — Fase: F0 (uso F1/F2) — Data: 2026-07-12
- Contesto: nomi categoria/conto possono divergere tra fonti e nel tempo (category drift).
- Decisione: **Categorie** → risolte via `category_map`; se ignote, transazione importata comunque +
  record in `category_pending` (F1) con UI di assegnazione e backfill. **Conti** → importati **as-is**
  (il nome sorgente diventa il valore `account`, nessuna coda pending), rinominabili/accorpabili in dashboard.
- Conseguenze: categorie governate senza perdere storico; conti gestiti con complessità minima (no secondo flusso).

## ADR-0007 — Bonifici/Transfer esclusi
- Status: Accepted — Fase: F0 — Data: 2026-07-12
- Contesto: i bonifici sono giri interni, non spese/entrate reali.
- Decisione: sheet `Bonifici` ignorato in import; `transactions.type` a 2 valori (`expense`|`income`).
- Conseguenze: totali puliti; se in futuro servono i transfer, nuovo ADR + migration.

## ADR-0008 — Backup: trigger manuale + startup opzionale, via Service Account
- Status: Accepted — Fase: F0 (uso F4) — Data: 2026-07-12
- Contesto: l'utente vuole controllo sul quando; deploy headless (Raspberry) per job automatici.
- Decisione: pulsante manuale sempre disponibile; job all'avvio SOLO se attivato in settings
  (`BACKUP_ON_STARTUP`). Autenticazione Drive via **Service Account** (JSON montata a runtime).
  Backup = dump SQLite + export "in chiaro" .xlsx → locale + Drive.
- Conseguenze: nessun login browser; nessun cron nascosto non voluto.

## ADR-0009 — Esposizione solo rete locale (per ora)
- Status: Accepted — Fase: F0 — Data: 2026-07-12
- Contesto: uso personale in casa; auth/reverse proxy = complessità non ancora necessaria.
- Decisione: app su rete locale, nessuna auth applicativa in questa fase. Rivedere se esposta fuori (nuovo ADR).
- Conseguenze: setup semplice; **non** esporre le porte fuori dalla LAN senza prima aggiungere auth.

## ADR-0010 — Ingestion manuale (per ora)
- Status: Accepted — Fase: F0 — Data: 2026-07-12
- Contesto: upload mensile manuale del file .xlsx; automazione da Drive = fase futura.
- Decisione: flusso base = upload manuale via web. Watcher/pickup automatico Drive rimandato (nuovo ADR quando serve).
- Conseguenze: meno parti mobili ora.

## ADR-0011 — Enforcement secrets: pre-commit content-based
- Status: Accepted — Fase: F0 — Data: 2026-07-12
- Contesto: un `git add .` accidentale può esporre la Service Account key (danno irreversibile anche su repo privato).
- Decisione: `.gitignore` con pattern secret + hook `pre-commit` che fa **grep del contenuto** dei file staged
  per marcatori (`private_key`, `client_email`, `auth_uri`, `token_uri`, `-----BEGIN ... PRIVATE KEY-----`).
  Criterio sul contenuto, non su dimensione byte (non blocca `package.json`/`tsconfig.json` legittimi).
  Hook versionato in `.githooks/`, attivato con `git config core.hooksPath .githooks`.
- Conseguenze: barriera automatica contro leak; segue `docs/SECURITY.md`.

## ADR-0012 — Import storico solo dal 2026, conti storici → principale
- Status: Accepted — Fase: F0 (uso F2) — Data: 2026-07-12
- Contesto: il master sheet ha tab 2024/2025/2026; l'utente vuole partire dal 2026.
- Decisione: import (incluso dry-run) limitato a `IMPORT_MIN_YEAR=2026`. Tutte le transazioni storiche
  assegnate al conto `principale` (lo storico wide non ha dettaglio conto).
- Conseguenze: dataset iniziale coerente e circoscritto; tab pre-2026 non importati.

## ADR-0013 — Parsing export My Finance: colonna importo, layout foglio, `category_raw`
- Status: Accepted — Fase: F1 — Data: 2026-07-13
- Contesto: ispezionato export reale (`2026_07_01_13_56_18_010808.xlsx`, sheet Spese/Entrate/Bonifici).
  Riga 1 = titolo periodo (non dato), riga 2 = header, dati da riga 3. Colonne importo multi-valuta:
  `Importo in valuta predefinita` / `Valuta predefinita`, `Importo in valuta del conto` / `Valuta conto`,
  `Importo in valuta della transazione` / `Valuta transazione` (quest'ultime vuote se transazione già in
  valuta predefinita). ADR-0005 dice hash su "category"/"account" ma non specifica se nome raw o id canonico.
- Decisione:
  1. **Importo canonico** = `Importo in valuta predefinita` + `Valuta predefinita` (coerente su tutti i
     conti, indipendente da valuta locale del conto/transazione). Le altre colonne importo ignorate in F1.
  2. **Parsing sheet**: skip riga 1 (titolo), riga 2 = header, righe successive = dati; righe con
     `Data e ora` vuota scartate (contate in `import_batches` come righe non importate).
  3. Sheet `Bonifici` ignorato (già ADR-0007).
  4. **Nuova colonna `transactions.category_raw`** (nome categoria as-is dalla fonte, immutabile) —
     campo stabile usato nell'hash dedup al posto di `category_id` (che è nullable/mutabile via backfill
     della reconciliation queue, ADR-0006). `hash_dedup` = hash di
     `(date@giorno, amount, category_raw, account, type)`. Chiarisce/implementa ADR-0005: "category"
     nell'hash = nome raw sorgente, non id canonico.
  5. Nuova tabella `category_pending`: `(id, source, source_name, created_at)`, unique su
     `(source, source_name)`. Alla risoluzione (assegnazione mapping da UI) → crea riga in
     `category_map`, backfill `transactions.category_id` dove `category_raw` combacia e `category_id`
     è NULL, poi elimina la riga pending (nessuno storico di stato: risolta = non più in coda).
- Conseguenze: hash stabile anche prima che la categoria venga mappata; backfill non tocca l'hash
  (mai ricalcolato) quindi nessun rischio di duplicati post-riconciliazione. Migrazione Alembic dedicata
  (schema-agent) per `category_raw` + `category_pending`.

## ADR-0014 — Pre-commit hook: esclude `docs/*.md` dal content-scan (falso positivo ADR-0011)
- Status: Accepted — Fase: F2 — Data: 2026-07-14
- Contesto: hook ha bloccato il commit su `docs/ARCHITECTURE.md` e `docs/DECISIONS.md`. Causa: questi
  file *citano letteralmente* i marcatori del hook (`private_key`, `client_email`, ecc., in ADR-0011 e
  nella sezione C3) come testo esplicativo di cosa il hook cerca — non un secret reale. `docs/SECURITY.md`
  contiene gli stessi marcatori da F0 (mai bloccato finora perché non ri-staged in un commit successivo
  all'attivazione del hook). Stessa causa strutturale anche per `.githooks/pre-commit` stesso: il file
  *definisce* i marcatori nella propria variabile `patterns=`, quindi si auto-bloccherebbe ogni volta
  che viene modificato/committato.
- Decisione: `.githooks/pre-commit` esclude dal grep (a) i file che matchano `docs/*.md` (unica estensione
  presente in `docs/`) e (b) se stesso (`.githooks/pre-commit`). Criterio pattern content-based
  **invariato** per tutti gli altri file (codice, config, `.env`, JSON, ecc.). Motivazione: i secret reali
  (Service Account JSON, API key) non transitano mai per markdown scritto a mano né per lo script del hook
  — vivono solo in `secrets/`/`.env`, già gitignored e già fuori dal content-scan per estensione/percorso.
- Conseguenze: elimina il falso positivo ricorrente sui documenti di governance, che devono poter
  discutere i marcatori del hook stesso senza bloccarsi da soli. Rischio residuo accettato: un secret
  reale incollato per errore in un file `.md` sotto `docs/` non verrebbe bloccato — trade-off ok per
  progetto solo-dev (N-NF4), rischio basso data la natura scritta-a-mano di questi file.

## ADR-0015 — Adapter master sheet storico: un-pivot, righe "Entrate", quadratura dry-run
- Status: Accepted — Fase: F2 — Data: 2026-07-14
- Contesto: ispezionato file reale (`Spese - V.2.xlsx`, tab `2026`, 38 colonne, righe 2-395 dati).
  Struttura più ricca di quanto assunto in ARCHITECTURE.md §3 Fase 2:
  - Righe spesa: col1 (`Data:`) = data reale; colonne categoria (`Alimentari`…`Finance -`, indici 2-19,
    dinamici = intervallo header tra `Data:` e `Commenti puliti` esclusi) possono essere valorizzate
    **più di una per riga** (stesso giorno, più categorie); `Commenti puliti` = commento condiviso.
  - Righe reddito: col1 = **stringa letterale `"Entrate"`** (non una data). Importo sempre in colonna 2
    per posizione (NON significa categoria "Alimentari"); categoria reddito reale = valore di
    `Commenti puliti` (`Stipendio`, `Finance +`, `Regalo`, `Altro`, …). **Nessun giorno preciso
    disponibile** — solo il mese è deducibile dal blocco in cui la riga si trova.
  - Righe `Totale %`: aggregato di chiusura mese. Colonne 2-19 = percentuali per categoria (possono
    essere `#DIV/0!` se `Spese` mese = 0 → ignorate). Colonne `Totale cumulato:`, `Spese`, `Differenza:`,
    `Accumulo totale`, `Trattenuta globali in busta paga ` = valori EUR mensili aggregati.
  - Blocchi Gennaio-Giugno: nessun marcatore di mese esplicito, il mese si deduce dalla prima riga-data
    del blocco. Blocchi Luglio-Dicembre: marcatore esplicito (riga con col1 = nome mese italiano, es.
    `Luglio`), preceduto/seguito da righe vuote.
  - Tab da considerare: solo `str(IMPORT_MIN_YEAR)` cioè `"2026"` (ADR-0012). Tab `2024`/`2025` e i tab
    di lavoro manuale `Copia qui le spese`/`Copia qui le entrate`/`PRENDI I VALORI DA QUI` ignorati (non
    sono dati, sono strumenti dell'utente per compilare il foglio a mano).
  - Utente consultato su convenzione data per righe reddito (nessun giorno recuperabile dal foglio):
    scelta **ultimo giorno del mese** del blocco.
- Decisione:
  1. **Colonne categoria**: intervallo dinamico nell'header tra `Data:` (esclusa) e `Commenti puliti`
     (esclusa) — per nome, non indice fisso, robusto a riordini.
  2. **Righe spesa** (col1 = datetime): una `Transaction` per ogni colonna categoria non-nulla/non-zero
     nella riga; `type=expense`; `comment` = valore condiviso di `Commenti puliti` applicato a tutte le
     transazioni generate dalla riga (limite noto della fonte: comment non disambiguabile per categoria
     se più di una valorizzata — accettato, non risolvibile senza perdere dati).
  3. **Righe reddito** (col1 == stringa `"Entrate"`): una `Transaction` con `amount` = valore colonna 2
     (posizionale), `category_raw` = valore di `Commenti puliti`, `type=income`,
     **`date` = ultimo giorno del mese corrente** (calcolato dal mese tracciato, vedi punto 5).
  4. **Righe `Totale %`**: mai importate come transazione. Le colonne EUR (`Spese`, `Differenza:`,
     `Totale cumulato:`, `Accumulo totale`, `Trattenuta...`) vengono catturate come riferimento mensile
     per la quadratura nel report dry-run (punto 6). Colonne percentuale (incluso `#DIV/0!`) ignorate.
  5. **Tracciamento mese corrente** (per datare le righe `Entrate` e associare i riferimenti `Totale %`):
     aggiornato da (a) ogni riga-data reale incontrata (year/month della data stessa, year sempre
     `IMPORT_MIN_YEAR` per questo tab) o (b) riga con nome mese italiano letterale. Riga `Entrate`
     incontrata senza mese noto (blocco senza alcuna riga-data precedente né marcatore) → **scartata**
     con motivo esplicito nel report dry-run, per revisione manuale — non blocca l'intero import.
  6. **Dry-run** (R1, ARCHITECTURE.md): import in **DB temporaneo effimero** (SQLite in-memory o file
     temp, schema creato con `Base.metadata.create_all` sui modelli correnti — non è una modifica dello
     schema canonico, nessuna revision Alembic necessaria qui), stessa pipeline hash/reconciliation di F1
     (ADR-0005/0006/0013) riusata as-is. **Mai** tocca `data/portfolio.db` reale. Report: N importate,
     righe scartate con motivo, somma mensile per categoria confrontata con `Spese` del foglio
     (quadratura), categorie finite in pending. Solo dopo validazione manuale dell'operatore contro il
     foglio originale → endpoint separato per l'import reale su DB live (stesso schema di F1: ImportBatch,
     replica atomica).
  7. **Conto**: sempre `principale` per tutto lo storico (ADR-0012, invariato).
- Conseguenze: adapter più complesso di quanto pianificato inizialmente in ARCHITECTURE.md, ma fedele
  alla struttura reale del foglio. Convenzione data reddito (fine mese) è un'approssimazione nota e
  accettata dall'utente — impatta solo il giorno, non il mese/importo (quadratura mensile invariata).
  Righe `Entrate` senza mese deducibile sono un edge case gestito come scarto segnalato, non come errore
  bloccante, coerente con lo spirito "dry-run + revisione manuale" di R1.

## ADR-0017 — Replica read-only: conversione WAL→DELETE post-copia (specializza ADR-0004)
- Status: Accepted — Fase: F3 — Data: 2026-07-14
- Contesto: durante il setup Metabase (F3), la connessione SQLite alla replica (mount
  `./replica:/replica:ro`, ADR-0004) falliva con `[SQLITE_CANTOPEN] Unable to open the
  database file`. Causa verificata: il DB live è in `journal_mode=WAL` (ADR-0001); `shutil.copy2`
  copia il file principale mantenendo l'intestazione WAL nel file copiato. Aprire un DB in
  WAL richiede poter creare/accedere ai file ausiliari `-wal`/`-shm` **anche per sole letture**
  (coordinamento wal-index) — impossibile su un mount realmente read-only. Confermato
  empiricamente: `touch` su `/replica` dentro il container Metabase → `Read-only file system`;
  stesso path con SQLite in WAL → `CANTOPEN`.
- Decisione: la generazione della replica (`app/db.py`, funzione `refresh_read_only_replica()`,
  usata dai due call site in `app/routers/imports.py` al posto di `shutil.copy2` diretto) esegue,
  nell'ordine: (1) `PRAGMA wal_checkpoint(TRUNCATE)` sulla connessione al DB **live** (fonde il
  WAL nel file principale, il live DB resta in WAL per gli scrittori futuri — invariato rispetto
  ad ADR-0001); (2) `shutil.copy2` del solo file principale (coerente point-in-time, WAL garantisce
  che al checkpoint il file rifletta uno stato committed); (3) apertura della **copia** (non il
  live) e `PRAGMA journal_mode=DELETE` — la replica non necessita più di `-wal`/`-shm` ed è apribile
  in sola lettura su mount realmente read-only. Nessuna modifica di schema (nessuna revision Alembic).
- Conseguenze: fix minimo, isolato alla funzione di replica; nessun impatto sul DB live (rimane
  WAL, unico writer FastAPI, ADR-0001 invariato). La replica è ora un file SQLite "semplice"
  (rollback-journal) rigenerato ad ogni `import_batch` completato — coerente con la sua natura di
  snapshot immutabile fino al prossimo import.

## ADR-0018 — Backup: online backup API SQLite, Drive Service Account opzionale, retention, restore con conferma
- Status: Accepted — Fase: F4 — Data: 2026-07-14
- Contesto: F4 richiede dump SQLite + export `.xlsx` leggibile verso locale e Google
  Drive (Service Account, ADR-0008), retention/rotazione, restore documentato e
  testato. Ricerca best practice: `shutil.copy2` su un DB WAL live (come in ADR-0017)
  richiede il workaround checkpoint+conversione journal_mode; l'online backup API di
  `sqlite3` (`Connection.backup()`) è progettata per copiare un DB in uso senza
  bloccarlo e senza quel workaround, producendo un file plain autonomo.
- Decisione:
  1. **Dump**: `sqlite3.Connection.backup()` (non `shutil.copy2`) per il file `.db`
     di backup. ADR-0017 (checkpoint + `journal_mode=DELETE`) resta invariato e
     specifico alla replica Metabase — non riusato qui, i due meccanismi restano
     distinti perché risolvono esigenze diverse (replica persistente vs snapshot
     puntuale).
  2. **Export xlsx**: sheet flat unico, tutte le transazioni (expense+income),
     colonne leggibili, via pandas/openpyxl. Naming accoppiato
     `portfolio_backup_YYYYMMDD_HHMMSS.{db,xlsx}` in `/backups`.
  3. **Drive upload**: `google-api-python-client` + `google-auth` (nuove dipendenze),
     Service Account da `GOOGLE_SA_KEY_PATH` (già montata a runtime, mai nel repo,
     ADR-0011). **Best-effort**: se la chiave manca o l'upload fallisce (rete,
     permessi), il backup locale riesce comunque; l'errore è loggato e riportato
     nella risposta endpoint, stesso pattern non-bloccante di
     `refresh_read_only_replica()` (ADR-0004). Nessun crash dell'app se la Service
     Account non è montata (deploy locale/single-dev, ADR-0009).
  4. **Retention**: `BACKUP_RETENTION` coppie `.db`+`.xlsx` mantenute; rotazione
     cancella le più vecchie sia in locale sia su Drive, stesso criterio
     non-bloccante del punto 3.
  5. **Restore**: `POST /backup/restore`, body `{filename, confirm: true}` —
     `confirm` esplicito obbligatorio (sovrascrive il DB live, operazione
     distruttiva). Legge solo da `/backups` locale (Drive = ridondanza off-site, non
     sorgente di restore: la retention locale mantiene lo stesso set di file).
     Procedura: `engine.dispose()` → overwrite `data/portfolio.db` → rimozione
     side-file WAL residui → riapertura → `refresh_read_only_replica()` per
     risincronizzare Metabase.
  6. **Trigger**: pulsante manuale sempre (`POST /backup`); job opzionale
     all'avvio via `BACKUP_ON_STARTUP` (già in `config.py` da F0), hook `lifespan`
     FastAPI, best-effort (non blocca l'avvio app).
  7. **Test**: nuova suite pytest `backend/tests/test_backup.py` (prima suite pytest
     committata nel repo — F1-F3 verificate manualmente). Backup → svuota/corrompi
     `transactions` → restore → verifica conteggi/somme tornano identici. Nessun
     mock di rete necessario: Service Account assente nei test → percorso Drive
     skippato per costruzione (punto 3).
  8. **Fuori scope** (YAGNI): tabella `settings` DB per toggle runtime (env var
     basta finché non c'è UI, F5); restore da Drive (ridondante con retention
     locale); cifratura dump/xlsx (esposizione solo rete locale, ADR-0009).
- Conseguenze: nessuna modifica di schema (nessuna Alembic revision per F4); due
  nuove dipendenze runtime (`google-api-python-client`, `google-auth`) e due di
  test (`pytest`, `httpx`); primo modulo del repo con test automatici, precedente
  per le fasi successive. Rischio residuo accettato: restore non testato contro
  backup provenienti da Drive (solo locali) — coerente con la scelta del punto 5.

## ADR-0019 — UI React (F5): scope read+write pieno, single-container, stack Vite+TS+TanStack Query+Tailwind/shadcn+Recharts, Metabase invariata

- Status: Accepted — Fase: F5 — Data: 2026-07-15
- Contesto: ARCHITECTURE.md §Fase 5 lasciava aperti tre punti: (a) React
  affianca o sostituisce Metabase; (b) topologia deploy (container unico o
  separato); (c) stack frontend concreto. Utente consultato su tutti e tre.
  Verificato lo stato attuale dei router FastAPI (`imports.py`,
  `categories.py`, `backup.py`): **nessun endpoint** copre oggi lettura
  aggregata (`/insights`), CRUD transazioni o rename conti (N-F6) — mancano
  interamente, non solo lato UI.
- Decisione:
  1. **Scope**: React copre **sia lettura sia scrittura** in modo completo
     (dashboard/insight equivalenti a Metabase + edit/delete transazioni +
     resolve category pending + rename conti + trigger backup/restore).
     Metabase **resta attiva in parallelo, invariata** (ADR-0004 non
     superato) — non è un affiancamento parziale né una sostituzione, sono
     due UI indipendenti sullo stesso backend.
  2. **Deploy**: build statico React (`vite build`) servito dal container
     FastAPI esistente via `StaticFiles` — **nessun nuovo servizio** in
     `docker-compose.yml`, nessun nginx, nessun CORS da configurare.
     Motivazione: N-NF4 (manutenibilità solo-dev) e N-NF2 (peso su
     Raspberry, F7) — un servizio JS in più (nginx) non aggiunge valore
     rispetto a file statici serviti dal processo Python già presente.
  3. **Nuovi endpoint FastAPI** (nessuno esiste oggi):
     `GET/PUT/DELETE /transactions` (lista filtrata/paginata, edit
     `comment`/`tag`/`category_id`, delete — mai campi dell'hash dedup),
     `GET/PATCH /accounts` (lista, rename `display_name`, N-F6 oggi non
     esposto da alcun router), `GET /insights` (trend mensile,
     breakdown per categoria, saldo cumulato, saldo per conto — stessa
     logica delle card SQL Metabase F3, ma via SQLAlchemy). Letture sul DB
     **live**, non sulla replica: il meccanismo di replica read-only
     (ADR-0004/ADR-0017) esiste solo per isolare Metabase in un container
     separato che non può condividere il file SQLite in WAL; FastAPI è già
     l'unico writer e WAL garantisce reader concorrenti sicuri nello stesso
     processo, quindi nessun bisogno di replica per i propri endpoint.
     Nessuna colonna nuova, nessuna Alembic revision per questo layer.
  4. **Stack frontend**: React + Vite + **TypeScript** (tipi generabili da
     schema OpenAPI FastAPI, contratto verificato a compile time),
     **TanStack Query** (fetch/cache/mutazioni/invalidation dichiarativa —
     necessario col requisito di scrittura piena, evita boilerplate
     manuale su ogni pagina), **React Router**, **Tailwind CSS +
     shadcn/ui** (look moderno N-NF5 senza design-system pesante da
     mantenere), **Recharts** (grafici dichiarativi React-native).
     Scartate: fetch nativo + `useState` puro (boilerplate eccessivo con
     tante mutazioni), MUI + Redux Toolkit Query (bundle pesante, opinioni
     di stile in conflitto con N-NF5, overkill single-user, peso extra su
     Raspberry — contro N-NF4).
  5. **Pagine**: Dashboard, Transazioni, Import (riusa endpoint `imports.py`
     esistenti as-is), Categorie pending (riusa `categories.py` as-is),
     Conti, Backup (trigger/lista/restore — riusa `backup.py` as-is).
  6. **Operazioni distruttive** (delete transazione, restore backup):
     conferma esplicita a 2 step in UI prima della chiamata — rispecchia
     lato frontend la stessa cautela già imposta lato backend da
     `confirm: true` obbligatorio su `/backup/restore` (ADR-0018 punto 5).
  7. **Testing**: nuova suite pytest per i router `transactions`/
     `accounts`/`insights` (stesso pattern F4, prima suite del repo).
     Nessuna suite automatica frontend (nessun requisito di produzione
     dichiarato dall'utente per questa fase, N-NF4) — verifica E2E manuale
     in browser a fine implementazione, coerente col pattern F1-F4
     (backend testato, frontend/dashboard verificato a mano).
  8. **Sottoagente**: `react-ui-agent` creato in `.claude/agents/`
     (componenti React, routing, chiamate FastAPI read+write, stato/query),
     mappato in CLAUDE.md.
- Conseguenze: nessuna modifica di schema in F5 (nessuna Alembic revision);
  tre nuovi router backend da implementare prima/insieme al frontend;
  due UI parallele da mantenere allineate ai dati (Metabase read-only +
  React read/write) — accettato perché sono processi indipendenti sullo
  stesso backend, nessuna duplicazione di logica di scrittura. Debito
  noto aperto: nessun test frontend automatico (rivedibile se emergono
  requisiti di produzione, nuovo ADR).

## ADR-0020 — Tiebreaker deterministico su `GET /transactions` (DEBT-01, F-DEBT)
- Status: Accepted — Fase: F-DEBT — Data: 2026-07-16
- Contesto: `list_transactions` ordinava solo per `Transaction.date.desc()`. Con più righe che
  condividono la stessa data (comune nel dataset reale, es. import batch mensili), l'ordine
  relativo tra loro non è garantito stabile da SQLite senza una seconda chiave esplicita —
  righe potevano duplicarsi o saltare tra pagine consecutive.
- Decisione: aggiunta `Transaction.id.desc()` come chiave di ordinamento secondaria, dopo
  `date.desc()`. Nessuna modifica di schema (nessuna Alembic revision — `id` è già la PK).
- Conseguenze: paginazione deterministica anche con date ripetute. Test di regressione
  (`test_list_transactions_pagination_stable_with_same_date`) inserisce 5 transazioni con data
  identica, pagina con `page_size=2` su 3 pagine, verifica zero duplicati/omissioni e ordine
  stabile (id decrescente).

## ADR-0021 — Favicon servita in produzione (DEBT-02, F-DEBT)
- Status: Accepted — Fase: F-DEBT — Data: 2026-07-16
- Contesto: `frontend/index.html` referenzia `/favicon.svg`, copiato da `frontend/public/`
  alla root del build Vite (comportamento standard Vite per la cartella `public/`). In
  produzione (`backend/app/main.py`) solo `/assets` era montato come `StaticFiles`
  (contiene il bundle JS/CSS con hash); qualunque altro path, incluso `/favicon.svg`,
  cadeva nel catch-all SPA che ritorna sempre `index.html` (200, `text/html`) —
  l'icona falliva silenziosamente. `frontend/public/icons.svg` risultava committato
  ma non referenziato da nessuna parte (asset morto).
- Decisione: aggiunta una route esplicita `@app.get("/favicon.svg")` in `main.py`,
  registrata PRIMA del catch-all `@app.get("/{full_path:path}")` (Starlette fa match
  per ordine di registrazione, non per specificità di path — l'ordine è vincolante).
  Rimosso `frontend/public/icons.svg` (nessun riferimento trovato, nessuno scopo
  noto). Nessuna estensione generica a "servi tutta la cartella public" per non
  introdurre un secondo meccanismo di static serving parallelo a `/assets` — un file
  esplicito per ogni asset di root effettivamente referenziato, pattern replicabile
  se in futuro si aggiungono altri file (`robots.txt`, ecc.).
- Conseguenze: `/favicon.svg` risponde `200 image/svg+xml` in produzione. Nessun
  impatto sul fallback SPA per le altre route (verificato: la route specifica non
  intercetta nulla oltre l'esatto path `/favicon.svg`).

## ADR-0022 — Fix collisione proxy Vite dev su `/import` e `/backup` (DEBT-04, F-DEBT)
- Status: Accepted — Fase: F-DEBT — Data: 2026-07-16
- Contesto: `frontend/vite.config.ts`'s `server.proxy` faceva match per prefisso su
  path bare (`/import`, `/backup`), identici alle pagine SPA omonime. Una
  navigazione/reload diretto del browser su quei path (non un click sidebar, che
  è client-side) veniva intercettato dal proxy e inoltrato al backend invece di
  servire la SPA. Verificati tutti i path proxati per lo stesso pattern di
  collisione (come richiesto dal piano F-DEBT): `/transactions` vs `/transazioni`,
  `/accounts` vs `/conti`, `/categories` vs `/categorie-pending` — nessuna
  collisione (stringhe diverse, nessun prefisso comune). Solo `/import` e
  `/backup` collidevano, perché le pagine SPA usano lo stesso nome esatto dei
  prefissi API.
- Decisione: due fix diversi, perché i due casi non sono equivalenti a livello di
  route reali del backend:
  1. **`/import`**: nessun endpoint reale è mai bare `/import` (sempre
     `/import/my-finance` o `/import/historical/*`) — sostituito il prefisso
     generico con due chiavi proxy specifiche (`/import/my-finance`,
     `/import/historical`), eliminando la collisione senza perdere copertura.
  2. **`/backup`**: `GET`/`POST /backup` sono endpoint reali **bare** (stesso
     path esatto della pagina SPA) — non esiste un pattern più specifico senza
     perdere quelle due route. Fix: proxy con funzione `bypass` basata su
     `Accept` header — richiesta con `text/html` (navigazione/reload reale del
     browser) bypassa il proxy e lascia servire la SPA da Vite; richiesta con
     `application/json` (fetch di TanStack Query) viene proxata normalmente al
     backend.
- Conseguenze: fix isolato a `vite.config.ts`, **solo ambiente dev** (in
  produzione FastAPI fa match per path esatto, nessuna collisione possibile,
  confermato in F5 Task 10). Verificato live: reload diretto su
  `http://localhost:5173/import` e `/backup` serve la SPA; "Backup ora" (POST
  `/backup` reale via fetch) continua a funzionare attraverso il bypass.

## ADR-0023 — Layer AI (F6): query NL read-only, adapter provider-agnostico con unico adapter Gemini, tool registry read-only, service layer insights con filtri

- Status: Accepted — Fase: F6 — Data: 2026-07-18
- Contesto: F6 implementa N-F11 ("plugin AI con API key utente per insight NL"). La spec di design
  (`docs/superpowers/specs/2026-07-18-f6-ai-nl-query-design.md`, rev. 1) nasceva da brainstorming e
  non era stata verificata contro il codice. Il confronto col repo ha trovato 7 incoerenze, due
  bloccanti:
  1. la spec introduceva `GEMINI_API_KEY`, ma `config.py:24-25` e `.env.example:28-31` hanno da F0
     `AI_API_KEY`/`AI_PROVIDER` (già pensate provider-agnostiche);
  2. la spec diceva "riusa la logica di `insights.py`", ma le 4 funzioni di aggregazione
     (`routers/insights.py:19-73`) **non accettano alcun filtro** e `GET /insights` non ha query
     param: aggregano sempre l'intera tabella. Una domanda del tipo "quanto ho speso a marzo per
     categoria" non sarebbe rispondibile se non scaricando le transazioni grezze e facendo sommare
     al modello — più costoso, più lento e aritmeticamente inaffidabile.
  Verificata inoltre l'API Gemini su ai.google.dev (2026-07-18): SDK `google-genai`
  (`from google import genai`), **Interactions API** (GA) via `client.interactions.create()`,
  function calling a **loop manuale** (il modello non esegue nulla; il backend intercetta lo step
  `function_call`, esegue, e rimanda `function_result` con `name`, `call_id` propagato identico, e
  `result`). Modelli GA al momento: `gemini-3.5-flash`, `gemini-3.1-flash-lite`, `gemini-2.5-flash`,
  `gemini-2.5-flash-lite`, `gemini-2.5-pro`.
- Decisione:
  1. **Scope**: solo query in linguaggio naturale in **sola lettura**. La categorizzazione AI delle
     transazioni pending (ARCHITECTURE.md §4) è un sottosistema **write** separato, fuori scope,
     con spec/ADR propri quando partirà.
  2. **Adapter provider-agnostico** (`app/ai/provider.py`, interfaccia `AIProvider` con
     `answer(question) -> AIAnswer`), un solo adapter concreto in questa fase
     (`app/ai/providers/gemini.py`). Anthropic/OpenAI = interfaccia pronta, non implementati.
     Scartate le librerie multi-provider (LiteLLM/AnyLLM) e i framework agent (LangChain):
     dipendenza pesante non giustificata per un uso stateless single-user (N-NF4) e peso extra su
     Raspberry (N-NF2, F7). Nuova dipendenza runtime: `google-genai` (client HTTP, il calcolo è
     remoto: impatto arm64 trascurabile, da confermare in F7).
  3. **Config**: si usano le variabili **già esistenti** `AI_PROVIDER` (oggi unico valore supportato
     `gemini`; vuoto = layer AI disattivo) e `AI_API_KEY`. Si aggiunge solo `AI_MODEL` (model id,
     default sulla linea *flash-lite* GA). **Nessuna variabile provider-specifica**: un
     `GEMINI_API_KEY` contraddirebbe l'adapter provider-agnostico del punto 2 e renderebbe la
     configurazione da riscrivere al primo secondo provider. Modello di default economico perché il
     dataset reale è di poche centinaia di righe: un modello di punta non porta valore proporzionale
     al costo, e il model id vive in una env var proprio per essere cambiabile senza rilascio.
  4. **Tool registry read-only** (`app/ai/tools.py`), condiviso da tutti gli adapter presenti e
     futuri: `list_transactions` (filtri data/categoria/conto/importo/tipo), `get_insights` (filtri
     del punto 5), `get_accounts`, `get_categories`. Sono **wrapper sulle query esistenti**, zero SQL
     duplicato. **Nessun tool può scrivere**: il modello non ha accesso ad alcuna operazione che
     modifichi `transactions`/`accounts`/`category_pending`. La cautela imposta su restore/delete
     (ADR-0018 p.5, ADR-0019 p.6) qui è applicata a monte, non esponendo affatto il tool di
     scrittura — un output non deterministico del modello non può alterare dati. `PUT
     /transactions/{id}` resta limitato a `comment`/`tag`/`category_id`, regola invariata e non
     richiamata da alcun tool.
  5. **Service layer insights** (`app/services/insights.py`): le 4 funzioni di aggregazione escono
     dal router e acquisiscono filtri opzionali (`date_from`, `date_to`, `account`, `type`).
     `GET /insights` diventa un wrapper sottile e, senza parametri, deve restituire **esattamente**
     l'output odierno — i 5 test esistenti di `test_insights.py` devono passare **invariati**.
     Specializza ADR-0019 p.3 (non lo supera): le letture restano sul DB **live**, la replica
     read-only serve solo a isolare Metabase in un container separato.
  6. **Stateless**: nessuna memoria conversazione, ogni domanda indipendente. Nessuna tabella nuova,
     **nessuna Alembic revision per F6**.
  7. **Guardrail operativi** (costo, latenza e volume di dati in egress dipendono tutti da questi):
     - cap righe per tool call (`list_transactions` non restituisce mai più di N righe al modello),
       col **troncamento dichiarato dentro il risultato del tool, mai silenzioso** — così il modello
       sa di vedere un sottoinsieme e restringe i filtri invece di rispondere su dati parziali;
     - cap iterazioni del loop tool-use: superato il limite l'endpoint risponde con quanto raccolto
       e lo segnala, invece di ciclare a costo indefinito;
     - timeout HTTP sulla chiamata al provider (stesso principio del timeout 30s già imposto al
       client Drive in F4).
     Valori concreti fissati nel piano implementativo, tarabili senza nuovo ADR.
  8. **Degradazione graceful**: provider non configurato, chiave o modello assenti → **4xx esplicito**
     dall'endpoint, nessun crash dell'app, nessun impatto sulle altre funzionalità (stesso pattern
     del Drive opzionale, ADR-0018 p.3).
  9. **Egress esterno**: secondo servizio esterno del progetto dopo Google Drive. Dati finanziari
     **incluso il testo libero di `comment`/`tag`** lasciano la LAN verso il provider scelto
     dall'utente, con la sua chiave personale, **solo su submit esplicito** — mai in background
     (stesso principio di controllo-utente-sul-quando di ADR-0008). Trade-off privacy scelto
     consapevolmente dall'utente in favore della capacità di rispondere anche sulle note delle
     transazioni. Documentato in `docs/SECURITY.md`. ADR-0009 invariato: è un flusso uscente
     iniziato dall'utente, non una nuova esposizione entrante.
  10. **Ordine di montaggio**: il router `/ai` va incluso in `main.py` **prima** del blocco che serve
      la SPA. Starlette fa match per ordine di registrazione, non per specificità: il catch-all
      `GET /{full_path:path}` intercetterebbe qualunque route registrata dopo di lui (stessa trappola
      già incontrata in DEBT-02/ADR-0021).
  11. **Frontend**: settima pagina "Assistente AI" su route `/assistente-ai` (nome diverso dal prefisso
      API `/ai`, quindi nessuna collisione proxy del tipo risolto in ADR-0022). Mostra sempre la
      **traccia dei tool chiamati** accanto alla risposta: i modelli possono sbagliare l'aritmetica,
      e la traccia rende i numeri ricontrollabili invece che da prendere sulla fiducia.
  12. **Test**: mock del **solo** `AIProvider` (adapter fake deterministico) — precedente accettato del
      fake Drive service (ADR-0018 p.7: mock ammesso solo per dipendenza esterna non deterministica e
      a pagamento, mai per DB o business logic). Tool registry e service layer testati **senza mock**
      su DB di test reale. Verifica E2E finale con risposta confrontata contro i totali noti del
      dataset (F2: 331 transazioni, uscite 9937.70 €, entrate 19497.14 €).
  13. **Sottoagente**: `ai-agent` creato in `.claude/agents/`, mappato in CLAUDE.md.
- Conseguenze: nessuna modifica di schema in F6. Un refactor non previsto dalla spec originale
  (service layer insights) diventa prerequisito del layer AI, ma paga anche fuori dall'AI: `/insights`
  guadagna filtri riusabili da qualunque consumatore futuro. Una nuova dipendenza runtime
  (`google-genai`). Debito noto accettato: la correttezza delle risposte non è verificabile
  automaticamente — mitigata dalla traccia tool in UI (punto 11) e dal fatto che il modello aggrega
  tramite tool invece di calcolare a mano dove possibile. Rischio residuo: le note personali in
  `comment`/`tag` lasciano la rete locale (punto 9), scelta esplicita dell'utente e reversibile
  restringendo il tool `list_transactions` senza toccare il resto dell'architettura.

## ADR-0016 — Versione Metabase pinnata reale: `v0.62.4` (specializza ADR-0004)
- Status: Accepted — Fase: F3 (scaffolding) — Data: 2026-07-14
- Contesto: ADR-0004 fissa la policy (replica read-only, immagine pinnata, mai `latest`) ma usa `v0.50.30`
  come *placeholder* di esempio, non una versione reale verificata. Serve una versione concreta per
  scrivere il blocco `metabase` in `docker-compose.yml`, e verificare supporto multi-arch in vista di F7
  (Raspberry Pi arm64). Interrogato Docker Hub (`hub.docker.com/v2/repositories/metabase/metabase/tags`)
  in data 2026-07-14: linea `v0.63.x` è ancora in **beta** (tag `v0.63.0.x`/`-beta`); ultima release
  **stabile** è `v0.62.4` (pubblicata 2026-07-08). Ogni tag ispezionato (`v0.62.4`, `v0.61.7`, `v0.60.12`,
  `v0.59.16`, `v0.58.19`, ecc.) espone manifest **multi-arch** con immagini sia `linux/amd64` sia
  `linux/arm64` (confermato via campo `architecture` nei manifest delle immagini del tag) — nessun rischio
  noto di incompatibilità arm64 per F7. Immagine pesa ~763 MB (layer amd64/arm64 comparabili): possibile
  onere su Raspberry Pi in termini di RAM/CPU a runtime (JVM), ma non di *build/pull* multi-arch.
- Decisione: pinnare `metabase/metabase:v0.62.4` (non `v0.50.30`, non `latest`, non linee beta) nel
  servizio `metabase` di `docker-compose.yml`. Nessuna scelta di skip Metabase in questa sessione: il
  peso reale su Raspberry va misurato empiricamente in F7 (nota di rischio, non decisione — l'alternativa
  UI React resta aperta come da ADR-0004 se il footprint risulta eccessivo). Aggiornamento immagine futuro
  segue comunque la policy di ADR-0004 (backup preventivo + lettura changelog prima di bump di versione).
- Conseguenze: `docker-compose.yml` ha un blocco `metabase` concreto e verificabile (`docker compose config`
  validato senza errori in questa sessione); nessuna ambiguità residua sul placeholder di ADR-0004. Rischio
  aperto per F7: verificare a runtime su hardware reale se `v0.62.4` (o la patch corrente a quel momento)
  è sostenibile su Raspberry Pi; se no, seguire l'alternativa già prevista (skip Metabase, anticipare F5).
