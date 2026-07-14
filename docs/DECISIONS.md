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
