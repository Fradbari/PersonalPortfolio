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
