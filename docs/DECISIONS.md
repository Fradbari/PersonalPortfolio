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

## ADR-0024 — Strategia arm64 (F7): build nativa sul Pi, pre-verifica QEMU fail-fast, compose unico universale

- Status: Accepted — Fase: F7 — Data: 2026-07-20
- Contesto: F7 implementa N-NF2 (portabilità `linux/arm64`). Fatti raccolti dall'utente
  (2026-07-20): target **Raspberry Pi 4, 4GB RAM**, non ancora disponibile (verifica hardware
  rimandata a sessione futura); nessuna preferenza per registry di immagini. Ricerca best
  practice: QEMU è 5-20x più lento del nativo (adeguato come verifica one-off, non come canale
  di build ricorrente); per Python non serve cross-compilation se tutte le dipendenze hanno
  wheel `manylinux aarch64`; log Docker illimitati usurano/riempiono la SD; healthcheck senza
  `start_period` adeguato marca `unhealthy` una JVM che su Pi 4 impiega minuti ad avviarsi.
  Spec: `docs/superpowers/specs/2026-07-20-f7-raspberry-arm64-design.md` (rev. 3).
- Decisione:
  1. **Canale di distribuzione = build nativa sul Pi**: `git clone` + comando standard
     `docker compose up -d --build` (identico per primo bootstrap e aggiornamenti — build
     no-op se nulla è cambiato, mai immagini stale). Nessun registry, nessun login (N-NF1,
     N-NF3). Costo accettato: prima build lenta sul Pi, una tantum.
  2. **Pre-verifica QEMU da desktop come gate di fase, fail-fast e deterministico** (non
     ispezione di log): (a) wheel check `pip download --only-binary=:all: --platform
     manylinux2014_aarch64` su `requirements.txt` — scelta conservativa intenzionale, il
     rischio da intercettare è la compilazione nativa C/Rust che sul Pi diventerebbe ore;
     (b) `docker buildx build --platform linux/arm64 --load` deve produrre un'immagine
     eseguibile; (c) smoke test del container emulato (`/health` 200, import moduli).
  3. **Un solo `docker-compose.yml`, tuning universale** (niente override, niente profiles):
     limiti/healthcheck/logging calibrati per il Pi ma innocui su desktop. Milestone
     letterale: stesso comando, stesso file, entrambe le architetture. Log rotation
     esplicita per-servizio nel compose (`json-file`, `max-size`/`max-file`) — nessun
     intervento su `daemon.json` del Pi (one-click).
  4. Healthcheck attesi (tarabili senza nuovo ADR): backend `30s/10s/5/90s`
     (interval/timeout/retries/start_period), metabase `30s/15s/10/900s`.
- Conseguenze: nessun servizio o meccanismo nuovo; la fase produce tuning compose, runbook e
  verifica emulata. F7 resta ◐ finché la checklist hardware non gira sul Pi reale. Rischio
  residuo: QEMU valida l'avvio ma non le performance — i numeri veri (tempi build/avvio,
  RAM) arrivano solo dall'hardware.

## ADR-0025 — Metabase su Raspberry Pi 4 4GB (F7): misura-poi-decidi con protocollo e soglie fissate prima, esito come raccomandazione operativa (Modello A)

- Status: Accepted — Fase: F7 — Data: 2026-07-20
- Contesto: ADR-0004/0016 lasciano aperta l'alternativa "se Metabase pesa troppo su Raspberry,
  skip + UI React". Su Pi 4 4GB la JVM è il carico dominante (doc Metabase: lasciare 1-2GB al
  resto del sistema). L'utente ha scelto di **misurare sul hardware reale prima di decidere**.
  Vincolo architetturale: la milestone F7 è "stesso `docker compose up`" — uno skip che
  introduce file/comandi alternativi contraddirebbe la fase (tensione rilevata in review
  della spec e risolta qui).
- Decisione:
  1. **Tuning preventivo universale** nel compose unico: `JAVA_OPTS=-Xmx1g`, limite memoria
     container 2GB.
  2. **Protocollo di misura ripetibile** (definizioni operative nel runbook
     `docs/RASPBERRY-PI.md`): tempo di avvio = dal ritorno del comando standard al container
     `healthy` (soglia ≤ 10 min, con margine intenzionale sotto lo `start_period` di 900s:
     il healthcheck non deve uccidere una misura borderline che spetta al protocollo
     bocciare); RAM steady-state = media di 3 letture `docker stats --no-stream` a 1 min di
     distanza, iniziate 5 min dopo il primo login, senza import in corso (soglia ≤ 1.5GB);
     query dashboard F3 "Personal Portfolio - Overview": cold registrata come informativa,
     **warm < 10s** è la soglia; stabilità = nessun OOM-kill in 24h (`docker events`,
     `dmesg`).
  3. **Modello A per l'esito**: la milestone si valida SEMPRE col full stack e col comando
     standard. Se una soglia sfora, l'esito è una **raccomandazione operativa
     post-validazione** — `docker compose stop metabase` (riattivabile con `start`), UI
     React come dashboard quotidiana — non una topologia alternativa, nessun file/comando
     diverso, nessun nuovo ADR per l'esito (già previsto qui); esito registrato nello Stato
     avanzamento di ARCHITECTURE.md.
- Conseguenze: decisione sul campo con dati ripetibili invece che a sensazione; nessuna
  biforcazione di topologia da mantenere; se skip, Metabase resta nel compose (riattivabile
  su hardware futuro più capace) e ADR-0004 resta valido su desktop. Rischio accettato:
  finché la misura non avviene, il comportamento reale su Pi è una stima.

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

## ADR-0026 — Dark mode (F8): token semantici CSS su Tailwind v3 `class`, nessuna migrazione a v4, chartConfig condiviso obbligatorio

- Status: Accepted — Fase: F8 — Data: 2026-07-21
- Contesto: il frontend F5 non ha alcun supporto al tema scuro, e non parzialmente — proprio da zero.
  Inventario verificato sul codice: `frontend/tailwind.config.js` non dichiara la chiave `darkMode`
  (default `media`, cioè il tema seguirebbe il sistema **senza che nessuna classe `dark:` esista**);
  `frontend/src/index.css` contiene 3 righe (`@tailwind base/components/utilities`) e **zero CSS
  custom properties**; 31 occorrenze di classi colore hardcoded (`bg-white`, `text-gray-*`,
  `border-gray-*`) su 11 file; 5 letterali esadecimali passati direttamente a Recharts in
  `frontend/src/pages/Dashboard.tsx:44-84` (`#16a34a`, `#dc2626`, `#2563eb`, `#7c3aed`/`#ddd6fe`,
  `#0891b2`). shadcn/ui è adottata **a metà**: ci sono `lib/utils.ts` (`cn()`),
  `class-variance-authority` e 2 componenti in `components/ui/`, ma **nessun `components.json`** —
  la CLI non è mai stata inizializzata. Versioni reali: Tailwind `3.4.19` (pinnato in F5 per
  incompatibilità note), Recharts `^3.9.2`, React `19.2.7`.
  Ricerca best practice (2026): la strategia raccomandata è token semantici in `:root` e `.dark`
  (coppie `background`/`foreground`) mappati su utility Tailwind; per i grafici, colori dichiarati
  via variabili `--chart-N` e riferiti come `var(--chart-N)` — forma introdotta con Recharts v3,
  che il progetto ha già. La documentazione shadcn dichiara esplicitamente che i componenti restano
  compatibili con Tailwind v3: la migrazione a v4 non è un prerequisito.
- Decisione:
  1. **`darkMode: 'class'`** in `tailwind.config.js`, non `media`: la preferenza esplicita
     dell'utente deve poter vincere sul sistema operativo (F9 espone la scelta `light|dark|system`).
  2. **Token semantici** in `frontend/src/index.css`, `@layer base`, definiti in `:root` e
     ridefiniti in `.dark`: `--background --foreground --card --card-foreground --muted
     --muted-foreground --border --input --ring --primary --destructive --success` e
     `--chart-1 … --chart-5`. Formato **HSL triplo** (sintassi Tailwind v3, i token vanno avvolti in
     `hsl(var(--x))` nella config), non OKLCH: OKLCH è il default di Tailwind v4 e qui
     introdurrebbe una dipendenza dalla major che non stiamo adottando.
  3. **Nessuna migrazione a Tailwind v4** in questa fase. Sarebbe un cambio di build system nel
     mezzo di 7 feature, con impatto su tutto il CSS esistente e sulla build arm64 di F7. Il costo
     è pagare a mano il porting dei componenti shadcn che oggi arriverebbero in sintassi v4;
     accettato. Rivedibile con un ADR successivo, mai come effetto collaterale di un'altra fase.
  4. **La CLI shadcn resta non inizializzata**: nessun `components.json`. I componenti nuovi
     (`ChartContainer`, `ChartTooltip`) si portano a mano in `components/ui/`, coerentemente con
     come sono già arrivati `button.tsx` e `alert-dialog.tsx`. Introdurre la CLI ora
     riscriverebbe la configurazione esistente per allinearla ai default v4.
  5. **ThemeProvider + script inline anti-FOUC**: il context React gestisce `light|dark|system` e
     applica la classe su `document.documentElement`; uno **script inline in `index.html`**, che gira
     **prima** del bundle, legge localStorage e applica la classe. Senza quello script ogni
     caricamento lampeggia bianco prima che React monti — difetto visibile a ogni singolo reload.
  6. **`chartConfig` condiviso obbligatorio** (`frontend/src/lib/chart-config.ts`): nessun grafico,
     presente o futuro, dichiara colori propri. Stroke, fill, tick, grid e tooltip escono da lì,
     leggendo i token via `getComputedStyle`. Motivazione: un colore hardcoded è invisibile finché
     qualcuno non apre la pagina in dark, e allora è illeggibile — è esattamente lo stato attuale
     dei 5 esadecimali di `Dashboard.tsx`.
- Conseguenze: la superficie di conversione è nota e finita (31 classi su 11 file, 5 esadecimali su
  1 file), quindi F8 è verificabile per esaurimento e non a campione. Nessuna dipendenza nuova.
  Debito accettato: i componenti shadcn presi dal registry ufficiale andranno tradotti in sintassi
  v3 a mano finché non si deciderà la migrazione. Vincolo permanente introdotto: **ogni grafico
  nuovo passa dal `chartConfig` condiviso** — un `stroke="#..."` in una PR è un difetto, non una
  scelta.

## ADR-0027 — Settings centralizzati (F9): `/settings` unico punto di configurazione UI, tabella key/value, precedenza DB > env > default, whitelist esplicita e blacklist permanente

- Status: Accepted — Fase: F9 — Data: 2026-07-21
- Contesto: il progetto non ha alcun punto di configurazione in interfaccia. `backend/app/config.py`
  espone 13 impostazioni via env; `backend/app/models.py` non ha una tabella `settings` e la sua
  docstring lo dichiara esplicitamente rimandato ("sarà aggiunta in una fase successiva tramite
  Alembic revision dedicata"), coerentemente con ADR-0018 p.8 che l'aveva descopata per YAGNI
  ("env var basta finché non c'è UI, F5"). Quella condizione è ora caduta: la UI esiste, e F8
  introduce la prima preferenza che **non può** vivere in env, perché è dell'utente e non del deploy.
  Senza una regola, ogni fase futura aggiungerebbe il proprio pannello di configurazione dove
  capita. Serve inoltre una policy sui secret: F9 è la prima fase che crea una superficie HTTP di
  lettura della configurazione, cioè un modo nuovo di far uscire valori che finora vivevano solo
  nel processo.
- Decisione:
  1. **`/settings` è l'unico punto di configurazione esposto all'utente — vincolo permanente di
     prodotto.** Nessuna pagina costruisce un proprio pannello di impostazioni: ogni preferenza
     presente e futura passa da qui. È il motivo per cui la tabella è key/value.
  2. **Tabella `settings`**: `key TEXT PRIMARY KEY`, `value TEXT`, `updated_at`. Key/value e non
     colonne tipizzate: così ogni impostazione futura è un INSERT e **non** una migrazione. Il
     tipo si applica in lettura, lato applicazione.
  3. **Precedenza DB > env > default.** Env resta il bootstrap (primo avvio, deploy headless,
     Raspberry); il DB è la fonte di verità runtime quando la chiave è stata scritta almeno una
     volta. Non è una violazione di 12-factor: la configurazione di *deploy* resta in env, quella
     di *preferenza utente* vive nel dato, che è dove appartiene.
  4. **Whitelist esplicita**, con il momento di applicazione dichiarato chiave per chiave — è la
     differenza fra un'impostazione che funziona e un utente convinto che l'app ignori i suoi
     salvataggi:

     | Chiave | Quando ha effetto |
     |---|---|
     | `theme` | immediato |
     | `metabase_url` | immediato (solo destinazione del link) |
     | `ai_history_max_turns` | immediato, dalla domanda successiva |
     | `import_min_year` | immediato, dal prossimo import |
     | `backup_retention` | immediato, dal prossimo backup |
     | `backup_on_startup` | **solo al boot successivo** |

     L'indicazione compare **accanto al campo nella UI**, non solo qui. Ogni chiave aggiunta in
     futuro entra in whitelist **con la sua riga in questa tabella**: è parte del contratto.
  5. **`metabase_url` è solo la destinazione del link** mostrato dalla UI React. Il servizio
     Metabase resta definito in `docker-compose.yml`: cambiarlo da `/settings` **non riconfigura né
     riavvia nulla**. Serve a puntare a un'istanza su host o porta diversi (tipicamente il Pi).
  6. **Blacklist permanente** — mai leggibili né scrivibili da API o UI: `AI_API_KEY`,
     `GOOGLE_SA_KEY_PATH`, `GDRIVE_BACKUP_FOLDER_ID`, e qualunque chiave futura che sia un segreto
     **o un identificatore di risorsa privata**. `GDRIVE_BACKUP_FOLDER_ID` non è una credenziale ma
     identifica una cartella Drive personale: esporlo è una fuga di informazione, non una comodità.
     `GET /settings` restituisce per i secret solo un blocco `secrets_status` con
     `{configured: true|false}` e **mai il valore**; la UI li mostra come badge con la riga `.env`
     da usare, mai come campo di input.
  7. **Nota che vale come regola di progetto**: `GOOGLE_API_KEY` **non esiste** in questo repository
     e non va introdotta. La chiave del provider AI è `AI_API_KEY`, provider-agnostica per
     ADR-0023 p.3; un nome provider-specifico contraddirebbe l'adapter e andrebbe riscritto al
     primo secondo provider.
  8. **Test di blacklist automatico**: la suite fallisce se una chiave blacklistata compare in
     qualunque punto della risposta di `GET /settings`. Non è una verifica una tantum — è il
     guardrail che rende la regola 6 verificabile invece che dichiarata.
  9. **Il tema vive in due posti, con ruoli distinti**: DB = fonte di verità (sopravvive al cambio
     di browser), localStorage = cache letta dallo script inline anti-FOUC di ADR-0026 p.5. Non è
     duplicazione: la cache serve a un vincolo temporale (applicare la classe prima del bundle) che
     una lettura via API non può soddisfare.
- Conseguenze: una revision Alembic (tabella nuova, rischio nullo). Il vincolo del punto 1 diventa
  una regola non negoziabile in `CLAUDE.md`. La superficie HTTP guadagna un perimetro di sicurezza
  che prima non esisteva, e che ADR-0031 specializza per il caso Drive. Rischio residuo accettato:
  la precedenza DB > env può disorientare chi cambia una env var e non vede effetti — mitigato
  mostrando in `/settings` il valore effettivo e la sua provenienza.

## ADR-0028 — Inserimento manuale (F11): `POST /transactions`, `source='manual'`, duplicato consapevole con ordinale `#n` (specializza ADR-0005/ADR-0013)

- Status: Accepted — Fase: F11 — Data: 2026-07-21
- Contesto: verificato sul codice — `backend/app/routers/transactions.py` espone **solo**
  `GET`/`PUT`/`DELETE`; **non esiste alcun `POST /transactions`**. Le transazioni possono entrare
  unicamente da un import di file. Vincoli di schema rilevanti (`backend/app/models.py`):
  `hash_dedup` ha `unique=True` a livello DB (riga 104); `category_raw` è **NOT NULL** (riga 98);
  `source` è una stringa senza `CheckConstraint` (riga 102), quindi un valore nuovo non richiede
  migrazione; `import_batch_id` è nullable (riga 103). L'unicità di `hash_dedup` è ciò che rende
  idempotenti gli import (ADR-0005/0013) ed è quindi intoccabile — ma rende anche **impossibile**
  registrare due spese realmente identiche nello stesso giorno (due caffè, stesso importo, stessa
  categoria, stesso conto), che è un caso quotidiano e legittimo.
- Decisione:
  1. **`POST /transactions`** con body `date, amount, currency, type, category_id, account,
     comment, tag`. Il backend deriva `category_raw` dal nome della categoria canonica scelta,
     imposta `source='manual'` e `import_batch_id=NULL`. **Nessuna Alembic revision per F11**:
     nessuna colonna nuova, e `source='manual'` passa perché la colonna non ha vincolo di dominio.
  2. **Ordine di validazione vincolante**: il `category_id` ricevuto va verificato esistente con
     una **lookup esplicita → 404 se assente**, e solo *dopo* si deriva `category_raw`. Invertire i
     due passi produce `category_raw = None` su una colonna NOT NULL: l'errore emergerebbe come
     `IntegrityError` al commit, cioè un **500 opaco**, al posto di un 404 che dice quale categoria
     manca. Pydantic **non** copre questo caso: valida che l'intero sia un intero, non che esista
     nel database.
  3. **Duplicato consapevole**: se l'hash calcolato esiste già → **409** con la transazione gemella
     nel corpo, così l'utente vede *cosa* sta per duplicare. Reinvio con `allow_duplicate: true` →
     si scrive `hash_dedup = <hash_base>#<n>`, con `n` ordinale della ripetizione.
  4. **Il suffisso `#n` è il meccanismo scelto per convivere con l'unique constraint senza
     modificarlo** — va detto esplicitamente perché non è ovvio a chi legge il codice dopo:
     stringhe diverse, nessuna violazione, nessuna migrazione, `hash_dedup` resta `unique`.
     **Corollario vincolante: l'importer confronta sempre l'hash base, mai il suffisso.** Una riga
     forzata `#n` non partecipa al dedup degli import e non ne altera l'idempotenza. Questo
     **specializza** ADR-0005 e ADR-0013 (che definiscono la formula dell'hash) e **non li supera**:
     la formula resta identica, cambia solo cosa si scrive in colonna per una riga esplicitamente
     marcata come ripetizione voluta.
  5. **Serializzazione del calcolo di `n`.** Leggere l'ordinale e poi scrivere in due passi separati
     è una race: due invii ravvicinati leggono entrambi "nessun `#n` esiste", scrivono entrambi `#1`
     e il secondo esplode con `IntegrityError`. È raro in single-user ma non impossibile (doppio
     click, retry del browser) ed è il tipo di errore che si manifesta solo in produzione. Lettura
     dell'ordinale e insert avvengono nella **stessa transazione serializzata**, aperta con
     `BEGIN IMMEDIATE` (prende il lock di scrittura subito, non alla prima INSERT) — coerente con
     FastAPI unico writer (ADR-0001/ADR-0004). Come cintura: `IntegrityError` su `hash_dedup` →
     ricalcolo di `n` e **un solo** nuovo tentativo, poi 409. Test di regressione con due richieste
     concorrenti che devono produrre `#1` e `#2`, mai un 500.
  6. **Validazione doppia**: Pydantic lato backend (importo > 0, `type` in `expense|income`, data
     non futura oltre soglia) e gli stessi vincoli nel form React, con errori per campo. La
     validazione frontend è ergonomia, non sicurezza: quella che conta è la backend.
  7. **Campi immutabili invariati**: `PUT /transactions/{id}` continua a toccare solo
     `comment`/`tag`/`category_id` (ADR-0019 p.3). Una transazione manuale sbagliata si cancella e
     si riscrive, non si edita nei campi dell'hash.
- Conseguenze: nessuna modifica di schema in F11. Il dedup resta l'invariante centrale del progetto
  e guadagna una via d'uscita esplicita e tracciabile invece di un aggiramento silenzioso. Debito
  noto accettato: il suffisso rende `hash_dedup` non più un hash puro ma "hash + discriminante di
  ripetizione" — chi scrive query dirette sul DB deve saperlo, ed è il motivo per cui il punto 4
  esiste.

## ADR-0029 — Filtri avanzati e ricerca full-text (F12): SQLite FTS5 con trigger, rebuild post-restore, gate arm64 come prerequisito di merge, URL come unico stato dei filtri

- Status: Accepted — Fase: F12 — Data: 2026-07-21
- Contesto: `list_transactions` (`backend/app/routers/transactions.py:36-70`) filtra oggi solo per
  `year_month`, `category_id`, `account`, `type`, senza alcuna ricerca testuale. Il dataset reale è
  di 331 transazioni con crescita di circa 50/mese: su questi volumi un `LIKE '%termine%'` sarebbe
  istantaneo. L'utente ha scelto comunque **FTS5**, accettando il costo di un secondo indice da
  mantenere coerente, in cambio di ranking, query booleane, match per prefisso e di una base
  riusabile per un eventuale retrieval AI futuro. Due fatti del progetto rendono la scelta non
  gratuita: (a) `POST /backup/restore` **sovrascrive il file DB** (ADR-0018 p.5), quindi un indice
  costruito prima del restore descrive dati che non esistono più; (b) F12 arriva *prima* della
  chiusura di F7 sul Raspberry, e la disponibilità di FTS5 dipende da come è compilato l'SQLite
  dell'immagine.
- Decisione:
  1. **Tabella virtuale FTS5 `transactions_fts`** su `comment`, `tag`, `category_raw`
     (content-table sincronizzata con `transactions`), più **tre trigger** INSERT/UPDATE/DELETE e
     il popolamento iniziale nella migrazione stessa. FastAPI è unico writer (ADR-0001), quindi i
     trigger sono l'unico punto di sincronizzazione necessario.
  2. **Gate arm64, prerequisito bloccante del merge del blocco.** Se l'SQLite dell'immagine arm64
     non avesse FTS5, la migrazione fallirebbe al primo `docker compose up` sul Pi rompendo **il
     deploy**, non solo la ricerca. Verifica con lo stesso metodo del gate F7 (ADR-0024 p.2):
     `docker buildx build --platform linux/arm64 --load`, poi nel container emulato
     `SELECT fts5_version();` deve rispondere. Se fallisce, il blocco **non si mergia**: si torna a
     `LIKE` e si riapre la decisione con un nuovo ADR. Non è rimandabile alla sessione-Pi: sarebbe
     scoprire il problema quando è già in produzione.
  3. **Check fail-fast all'avvio** che l'SQLite in esecuzione abbia FTS5, con errore esplicito se
     assente — stessa logica del gate, applicata a runtime per l'ambiente reale.
  4. **Rebuild dell'indice dopo `POST /backup/restore`**, dentro la stessa procedura che già
     rigenera la replica Metabase. Senza, la ricerca risponderebbe su dati vecchi **senza segnalare
     nulla**: un errore silenzioso, la categoria peggiore.
  5. **Filtri su `GET /transactions`**: `date_from`, `date_to`, `category_id`, `account`,
     `amount_min`, `amount_max`, `type`, `q` (full-text). `year_month` **resta** per compatibilità:
     è consumato dalla UI esistente e dai test.
  6. **Raggruppamento** `group_by=category|month|account`, con intestazioni di gruppo e subtotali,
     senza rompere la paginazione (ADR-0020: ordinamento `date desc, id desc` invariato).
  7. **URL come unico stato dei filtri**: `useSearchParams` di React Router (già dipendenza, nessuna
     libreria nuova) è la fonte di verità, e alimenta la `queryKey` di TanStack Query. Nessuno stato
     di filtro in `useState` parallelo all'URL — due fonti di verità divergono al primo back del
     browser. Effetto: ogni configurazione di filtri è un permalink incollabile e ricaricabile.
- Conseguenze: una revision Alembic con rischio medio, ridotto a basso dal gate del punto 2. Il
  progetto acquisisce un indice secondario, quindi un nuovo modo di essere incoerente: i punti 3 e 4
  sono le due cinture. Beneficio collaterale registrato ma **fuori scope**: con FTS5 in casa, un
  tool AI `search_transactions` read-only diventerebbe banale (nota in ADR-0032). Rischio residuo:
  se in futuro qualcuno scrivesse sul DB fuori da FastAPI, i trigger resterebbero l'unica difesa —
  accettabile finché ADR-0001 regge.

## ADR-0030 — Dashboard avanzate (F13): estensione del service layer di F6, mai un secondo; "saldo cumulato" non è "patrimonio netto"; Metabase invariata

- Status: Accepted — Fase: F13 — Data: 2026-07-21
- Contesto: la Dashboard React attuale ha 4 grafici; l'utente ne chiede sei fra cui "andamento
  patrimonio netto". Verifica sul modello dati: `transactions` è l'unica tabella di fatti, non
  esistono saldi iniziali, asset, passività né snapshot patrimoniali. Il patrimonio netto (attività
  meno passività) **non è calcolabile** con i dati presenti: ciò che si può mostrare è la somma
  cumulata di entrate meno uscite, che coincide col patrimonio solo se si parte da zero e tutto
  transita dai conti tracciati. Sul lato backend, F6 ha già estratto le aggregazioni in
  `backend/app/services/insights.py` con filtri opzionali (ADR-0023 p.5), consumato oggi da **due**
  chiamanti: `GET /insights` e il tool AI `get_insights`.
- Decisione:
  1. **Le dashboard React sono complementari a Metabase, che resta invariata.** ADR-0004 e ADR-0019
     non sono superati: due UI indipendenti sullo stesso backend, nessuna duplicazione di logica di
     scrittura.
  2. **Estensione di `services/insights.py`, mai un secondo service layer.** Le aggregazioni nuove
     entrano nello stesso modulo riusando i filtri esistenti: nessun SQL duplicato. Pannelli React,
     `GET /insights` e tool AI restano alimentati dalle stesse funzioni.
  3. **Criterio di accettazione esplicito**: le firme esistenti restano **backward-compatible** —
     parametri nuovi solo come argomenti opzionali con default, mai riordinati, mai rinominati. I 5
     test F5 su `GET /insights` senza parametri devono passare **invariati, senza una riga toccata**:
     se serve modificarli, è la firma ad essere rotta ed è la firma a tornare indietro. **Il tool
     `get_insights` del registry AI rientra nello stesso criterio di merge**, non in una nota a
     margine: è il secondo consumatore ed è silenzioso — una firma rotta lì non fallisce a compile
     time, fallisce la prima volta che il modello chiama il tool, cioè in produzione.
  4. **Divieto di nomenclatura**: la parola "patrimonio" non compare in UI, tooltip, titoli di
     pannello né nomi di campo API. Il pannello si chiama **"Saldo cumulato"**. Un'etichetta
     approssimata, anche fra parentesi, diventa comunque la dicitura che l'utente legge e su cui
     prende decisioni. Il patrimonio netto reale richiede un modello asset/passività: sottosistema
     separato, fuori scope, con spec e ADR propri quando partirà.
  5. **Set di pannelli**: saldo cumulato (area/line) · cash flow mensile (barre entrate/uscite +
     linea netto, finestra 12 mesi) · spese per categoria (**donut**, top 6 + "altro") · trend
     risparmio (% = (entrate − uscite)/entrate) · confronto mese su mese (barre + delta %) · riga di
     4 KPI (entrate, uscite, netto, tasso di risparmio).
  6. **Donut, non treemap.** Ricerca best practice: il treemap serve a dati gerarchici con molte
     foglie; sotto una quindicina di categorie comunica *meno* di un donut o di un bar chart, e
     viene scelto per estetica da cruscotto. La soglia "treemap solo oltre ~15 categorie" è una
     **nota di design, non una condizione da implementare**: nessun `if` che cambi tipo di grafico
     a runtime, nessun test che la verifichi. Oggi si implementa il donut.
  7. **Ogni grafico usa il `chartConfig` condiviso** di ADR-0026 p.6. Nessun colore dichiarato nel
     componente.
  8. **Nota sul punto aperto P1**: se la misura su Raspberry (ADR-0025) portasse a fermare Metabase,
     queste dashboard smetterebbero di essere complementari e diventerebbero l'unica superficie
     analitica. In quel caso servirà un **ADR successivo che specializza questo**, mai una modifica
     retroattiva del presente.
- Conseguenze: nessuna revision Alembic in F13. Il service layer di F6 si consolida come punto unico
  di aggregazione, il che paga oltre F13. Rischio residuo: la dashboard React e le card SQL di
  Metabase (F3) calcolano gli stessi indicatori con motori diversi — la verifica incrociata contro i
  totali noti del dataset F2 (331 transazioni, uscite 9937.70 €, entrate 19497.14 €) resta il
  controllo che li tiene allineati.

## ADR-0031 — Test di connettività Google Drive (F10): probe write→read→delete, credenziali lette solo da config, errori sanitizzati, cleanup best-effort (specializza ADR-0018 e ADR-0027)

- Status: Accepted — Fase: F10 — Data: 2026-07-21
- Contesto: il backup su Drive esiste da F4 ma è verificabile solo eseguendo un backup vero, e
  fallisce in modo silenzioso per scelta (best-effort, ADR-0018 p.3): l'utente scopre che la
  Service Account non è configurata bene solo leggendo `drive_error` in fondo alla risposta di un
  backup. Fatto tecnico determinante (`backend/app/drive.py:16`): lo scope OAuth usato è
  `drive.file`, che rende visibili alla Service Account **solo i file creati da lei**. Ne segue che
  una `files().list()` su una cartella condivisa ma vuota e una su una cartella **non** condivisa
  restituiscono lo stesso risultato: nessun file, nessun errore. Un test di sola lettura potrebbe
  quindi passare mentre il backup fallirebbe.
- Decisione:
  1. **`POST /backup/gdrive-test` esegue un probe reale**: crea un file di pochi byte nella cartella
     configurata, lo rilegge per id, lo cancella. Con scope `drive.file` è **l'unico test che
     dimostra il permesso effettivamente richiesto dal backup**, cioè la scrittura.
  2. **Credenziali lette solo internamente. Questo punto specializza ADR-0027 p.6** (blacklist):
     l'endpoint legge `GDRIVE_BACKUP_FOLDER_ID` e `GOOGLE_SA_KEY_PATH` da `config.py`, **non li
     accetta nel body** della richiesta e **non li restituisce** nella risposta, nemmeno
     parzialmente. Il valore circola solo dentro il processo backend.
  3. **Sanitizzazione degli errori, con meccanismo fissato** — due implementazioni diverse qui
     divergono subito, e l'errore Drive per una cartella inesistente contiene proprio l'id
     blacklistato: (a) il messaggio si costruisce dai **campi strutturati** di
     `googleapiclient.errors.HttpError` (`resp.status`, `reason`), non da `str(exc)`, che è il posto
     dove l'id finisce; (b) qualunque stringa che esca comunque passa da **una sola** funzione di
     redazione che fa `str.replace` **letterale** dei valori noti letti da `config`, sostituendoli
     con segnaposto — **non** una regex euristica che indovina cosa somiglia a un id e sbaglia in
     entrambe le direzioni; (c) test che chiama l'endpoint con un folder_id fasullo e asserisce che
     quella stringa non compaia in nessun punto della risposta.
  4. **Esiti diagnostici distinti**, mai un generico "errore": Service Account non montata, JSON
     malformato, folder id mancante, cartella non condivisa (404), permesso insufficiente (403),
     quota superata, timeout. Un messaggio che nomina la causa rimanda alla procedura di condivisione
     cartella già documentata in `docs/SECURITY.md`.
  5. **Cleanup best-effort, non garanzia.** Nome deterministico
     `portfolio_gdrive_probe_<YYYYMMDD_HHMMSS>.probe`, con prefisso **distinto** da `BACKUP_PREFIX`
     così che la retention dei backup non lo tocchi mai e viceversa. Se la creazione riesce e la
     lettura va in timeout (rete caduta, i 30s di `DRIVE_TIMEOUT_SECONDS` scaduti) il backend
     potrebbe non riuscire nemmeno a cancellare: il test **fallisce con l'errore reale** e non lo
     maschera dichiarando successo, la cancellazione è tentata comunque in un `finally`, e **ogni
     esecuzione inizia rimuovendo gli orfani** che matchano il prefisso. Un residuo su Drive non è
     un fallimento dell'app — stesso spirito non-bloccante di ADR-0018 p.3/p.4.
  6. **Il pulsante in UI non espone nulla**: mostra esito e dettaglio diagnostico, mai il folder id,
     che non è né visibile né modificabile (ADR-0027 p.6).
- Conseguenze: nessuna modifica di schema, nessuna dipendenza nuova (riusa `get_drive_service` di
  F4). La configurazione Drive diventa verificabile **prima** di scoprirla rotta durante un backup.
  Trade-off accettato e dichiarato in `docs/SECURITY.md`: il test **scrive davvero** nel Drive
  dell'utente, sia pure un file effimero di pochi byte.

## ADR-0032 — Persistenza chat AI (F14): `chat_sessions`/`chat_messages`, finestra di contesto troncata nell'adapter, scrittura solo dal router, modello sempre read-only (specializza ADR-0023)

- Status: Accepted — Fase: F14 — Data: 2026-07-21
- Contesto: ADR-0023 p.6 ha scelto per F6 un layer AI **stateless**: nessuna memoria fra chiamate,
  nessuna tabella, nessuna revision. La conseguenza pratica è che una domanda di follow-up ("e il
  mese prima?") non è rispondibile, perché il modello non sa a cosa si riferisca. L'utente chiede
  storicità delle conversazioni e memoria. Fatti dal codice: `AIProvider.answer(question, session)`
  è una classe astratta con un solo adapter concreto (`gemini.py`) e un fake usato nei test via
  `dependency_overrides`; `POST /ai/query` restituisce già una lista `tools_used` nella forma
  `[{name, args, result_summary}]` (`backend/app/routers/ai.py:82-85`). Il registry
  (`backend/app/ai/tools.py`) contiene 4 tool **tutti read-only**, con guardrail testato.
  L'utente ha scelto la memoria conversazionale **senza RAG**: i tool esistenti coprono già le query
  sui dati, e un retrieval vettoriale porterebbe una dipendenza nativa da compilare per arm64
  (rischio diretto su F7) per un beneficio non dimostrato su poche centinaia di righe.
- Decisione:
  1. **Due tabelle**: `chat_sessions (id, title, created_at, updated_at)` e `chat_messages (id,
     session_id FK, role, content, tools_json, created_at)`, con indice su `(session_id,
     created_at)`. Questo **specializza** ADR-0023 p.6, che dichiarava l'assenza di tabelle: lo
     stateless era una scelta di scope della fase, non un invariante di architettura.
  2. **Formato di `tools_json` fissato ora**, prima dell'implementazione: è il tipo di dettaglio
     che, deciso implicitamente da chi scrive per primo, diventa costoso da cambiare perché i dati
     storici sono già nel formato sbagliato. Colonna **TEXT** contenente una stringa JSON
     (`json.dumps`) il cui contenuto è **la stessa lista già restituita da `POST /ai/query`**:
     `[{"name": …, "args": {…}, "result_summary": …}]`. Un solo shape in tutto il sistema — risposta
     API, riga di DB e rendering della traccia leggono la stessa struttura. `NULL` per i messaggi
     `role="user"`. Nessuna tabella `chat_tool_calls`: sarebbe normalizzare un payload che non viene
     mai interrogato per campo, solo riletto intero.
  3. **Contratto provider**: `AIProvider.answer(question, session, history=None)`. È un **breaking
     change** su una classe astratta, e `history=None` con default fa compilare tutto senza fallire
     — una regressione sarebbe silenziosa. **Ordine dei task obbligatorio**: (1) aggiornare il fake
     provider perché registri la history ricevuta **e il suo numero di elementi**, e scrivere il
     test che asserisce l'arrivo delle ultime N coppie — **il test deve fallire qui**, ed è l'unico
     momento in cui si vede che sta misurando qualcosa; (2) solo dopo cambiare la firma su
     `AIProvider` e sull'adapter; (3) infine router, persistenza e UI. Criterio di merge del blocco:
     evidenza documentata del passaggio rosso→verde **più** suite verde dopo il cambio di firma —
     la sola suite verde non dimostrerebbe nulla.
  4. **Il troncamento vive nell'adapter, non nel router.** Il router carica dal DB e passa la
     conversazione; l'adapter applica il cap `ai_history_max_turns` (default 6, configurabile da
     `/settings`, ADR-0027) prima di chiamare il provider. Il limite di contesto è una proprietà del
     provider e del modello, non del dominio: metterlo nel router lo imporrebbe a ogni adapter
     futuro. Due test distinti lo verificano: sul fake, la history arriva **completa** dal router;
     sull'adapter in isolamento, una history lunga viene **troncata** prima della chiamata.
  5. **Endpoint e cancellazioni distinte**, con la cautela applicata dove serve — precedenti:
     ADR-0018 p.5 (`confirm: true` obbligatorio sulle operazioni distruttive) e ADR-0019 p.6
     (conferma a 2 step in UI):
     - `POST /ai/query` accetta un `session_id` opzionale (assente → nuova sessione);
     - `GET /ai/sessions` (elenco), `GET /ai/sessions/{id}` (messaggi);
     - `DELETE /ai/sessions/{id}` — **una sola** conversazione, **senza `confirm`**: la perdita è
       circoscritta e l'utente ha appena indicato quale riga colpire;
     - `DELETE /ai/sessions` — **azzera tutto lo storico**, `confirm: true` **obbligatorio**. È
       l'endpoint dietro il pulsante "Azzera storico", e qui la conferma serve perché non esiste
       modo di ricostruire cosa è andato perso.
  6. **Il modello resta read-only, senza eccezioni.** La persistenza è scritta **dal router**, mai
     da un tool: nessun tool di scrittura entra nel registry, e ADR-0023 p.4 resta invariato. Test
     di regressione che scandisce il registry dopo l'introduzione della persistenza — è
     esattamente il momento in cui la tentazione di "un tool che salva" sarebbe più forte.
  7. **Nessun RAG.** Scartati sia il retrieval vettoriale (dipendenza nativa, rischio arm64 su F7,
     costo di embedding a ogni import) sia, per ora, un tool di ricerca testuale. Nota: l'indice
     FTS5 introdotto da ADR-0029 renderebbe banale un `search_transactions` read-only — registrato
     come evoluzione futura, **fuori scope qui**.
  8. **Conseguenza privacy, da documentare in `docs/SECURITY.md`**: la finestra di contesto viene
     **rispedita al provider a ogni domanda successiva**, quindi il volume di dati in egress cresce
     con la lunghezza della conversazione, e le conversazioni restano **persistite in locale** fino
     a cancellazione esplicita. "Azzera storico" è anche una leva di privacy, non solo di pulizia.
     ADR-0023 p.9 resta valido e si estende: l'egress avviene sempre e solo su submit esplicito.
- Conseguenze: una revision Alembic (due tabelle nuove, rischio nullo). Il costo per domanda cresce
  con la lunghezza della conversazione — il cap del punto 4 è la leva che lo governa, ed è
  configurabile senza rilascio. Rischio residuo accettato: una conversazione lunga può far uscire
  dalla rete locale più dati di quanti l'utente ricordi di aver inviato; mitigato dal cap, dalla
  traccia dei tool sempre visibile (ADR-0023 p.11) e dal pulsante di azzeramento.
