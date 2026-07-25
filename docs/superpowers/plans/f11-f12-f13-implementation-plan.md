# Blocco B — F11 + F12 + F13 — piano implementativo

- **Status**: Approvato per l'esecuzione — 2026-07-25 (8 giri di review, esiti incorporati nei
  criteri di accettazione)
- **Spec di dettaglio**: `docs/superpowers/specs/2026-07-25-f11-f12-f13-detail-spec.md`
- **Branch**: `f11-f12-f13-transactions` (aperto da `master` `1a283e4` = `origin/master`)
- **Esecuzione**: subagent-driven-development — un task per subagent, review dopo ciascuno,
  **tre checkpoint umani** (CP1 · CP1b · CP2) più un go/no-go implicito dopo T0
- **Ledger**: `.superpowers/sdd/progress.md`

## Context

Il Blocco B è la seconda fase di codice della roadmap F8-F14. Il Blocco A (F8 dark mode + F9
settings) è chiuso, mergiato e pushato: `master` = `1a283e4`, 148 test verdi, `alembic heads` = 1
riga (`0003`). F0-F6 e F-DEBT sono chiuse; F7 è ◐ parcheggiata in attesa hardware e **non va
toccata**.

La roadmap (ADR-0028/0029/0030) fissa cosa fare. La sessione di pianificazione ha prodotto la spec di
dettaglio e ha trovato, leggendo il codice, **sei difetti che la roadmap dava per scontati** — cinque
strutturali più uno di sintassi FTS5. Sono la ragione per cui diversi criteri di accettazione qui
sotto sembrano pedanti: ognuno chiude un fallimento che sarebbe stato **silenzioso**.

| # | Difetto | Perché è pericoloso |
|---|---|---|
| **D1** | 1 dei 5 test F5 (`test_insights.py:117-118`) asserisce con `==` sul body intero | Aggiungere chiavi a `GET /insights` lo rompe; ADR-0030 p.3 lo usa come criterio di merge |
| **D2** | Nessun `conftest.py`; i 148 test usano `create_all()`, mai Alembic | Una virtual table creata in migration è invisibile a ogni test |
| **D3** | `api.ts:9` scarta status e resto del body | Il 409 con la gemella non arriverebbe al form; con `detail` dict → `"[object Object]"` |
| **D4** | `render_as_batch=True` (`env.py:25`, `:42`) | Un `batch_alter_table('transactions')` dopo la migration FTS **droppa i 3 trigger** senza ricrearli. L'indice smette di aggiornarsi in silenzio |
| **D5** | `POST /backup/restore` non fa girare Alembic | Restore di un backup vecchio → schema vecchio sotto codice nuovo. Vale **già oggi** per `settings` di F9 |
| **D6** | Trigger su contenuto esterno richiedono il comando `'delete'` con i **vecchi** valori | `DELETE FROM …fts WHERE rowid=…` non fa ciò che sembra; l'indice si desincronizza |

## Ordine e checkpoint

```
T0 gate arm64/FTS5  →  [go/no-go implicito]
T1 branch + ADR
T2 indici  →  T3 FTS5 + conftest  →  T4 fixture FTS  →  T5 search.py
T6 filtri + q + group_by  →  T7 POST + ordinale + 409
                                   →  [CP1: contratto transazioni]
T8 ApiError  →  T9 primitive UI  ∥  T12 token chart
T10 form + UX 409  →  T11 filtri in URL
T13 service + /insights/panels   →  [CP1b: contratto pannelli]
T14 sei pannelli                 →  [CP2: giudizio visivo]
T15 restore: upgrade + rebuild
T16 chiusura blocco
```

**T2 e T3 mai in parallelo**: due migration scritte da subagent che non conoscono il rispettivo
`down_revision` producono `alembic heads` a due righe.

**T9 e T12 parallelizzabili solo se T9 non tocca `index.css`** — condizione verificata da un criterio
esplicito, non assunta. Entrambi graviterebbero altrimenti sullo stesso file.

---

## T0 — Gate M12.0 arm64 + FTS5

**Agente**: main (controller). **Nessun file toccato.**

Il gate è prerequisito bloccante del merge, ma si esegue **per primo**: se FTS5 mancasse, cadrebbero
T3/T4/T5/T15 e T6 andrebbe riscritto su `LIKE` — cinque task su diciassette.

```bash
docker buildx build --platform linux/arm64 -f backend/Dockerfile -t pp-backend:arm64-verify --load .
docker image inspect pp-backend:arm64-verify --format '{{.Architecture}}'   # atteso: arm64
```

Poi, **dentro il container emulato** (QEMU è 5-20x più lento, attendere con generosità):

```bash
MSYS_NO_PATHCONV=1 docker run --rm --platform linux/arm64 pp-backend:arm64-verify \
  python -c "import sqlite3; c=sqlite3.connect(':memory:'); print(c.execute('select fts5_version()').fetchone()); \
             print([r[0] for r in c.execute(\"pragma compile_options\") if 'FTS5' in r[0]]); \
             c.execute('create virtual table t using fts5(x)'); c.execute(\"insert into t(t) values('rebuild')\"); print('fts5-ok')"
```

**Criterio**: `fts5_version()` risponde, `compile_options` contiene `ENABLE_FTS5`, la virtual table si
crea e il `'rebuild'` non solleva. Output reale incollato nel ledger.

`MSYS_NO_PATHCONV=1` è obbligatorio su questa macchina: Git Bash converte i path in `-e VAR=/path`
(incidente già capitato nel gate F7).

**Se fallisce**: stop. Si torna a `LIKE`, si riapre la decisione con l'utente, il blocco non si
mergia con FTS5.

---

## T1 — Branch + ADR di blocco

**Agente**: main. **File**: `docs/DECISIONS.md`. **Zero codice.**

**Primo passo operativo**: `grep "^## ADR-" docs/DECISIONS.md` per confermare che **0034** sia il
numero libero successivo (verificato al momento della pianificazione: l'ultimo è 0033, più un
template `ADR-XXXX`). Se fosse occupato, rinumerare di conseguenza.

Poi scrivere:

- **ADR-0034** (nuovo) — restore porta il DB a head, con la clausola sullo schema più nuovo del
  backup (testo integrale in spec §3 D6). Specializza ADR-0018.
- **Rettifica ADR-0028 p.5** — l'ordinale `#n` non usa `BEGIN IMMEDIATE`, arbitra il UNIQUE con
  retry. Motivazione in spec §3 D5.
- **Rettifica ADR-0029 p.6** — `group_by` restituisce solo subtotali.
- **Rettifica ADR-0030 p.3** — i pannelli escono da `GET /insights/panels`; il divieto è su un
  secondo *service layer*, non su un secondo *endpoint*.
- **Rettifica additiva ADR-0026** — `--chart-6`/`--chart-7`.
- Regola `category_raw` per il manuale, formato `#n`, shape del 409, shape di `group_by`,
  non-propagazione ad `ai/tools.py`, F11 come dialog senza nuove route SPA.

---

## T2 — Migration indici su `transactions`

**Agente**: schema-agent. **File**: `backend/alembic/versions/000X_*.py`.

Indici su `date`, `account`, `category_id`, `type` — oggi non ne esiste **nessuno** esplicito
(`models.py`), e F12 introduce filtri su tutte e quattro le colonne.

**Criterio**: round-trip `upgrade` → `downgrade` → `upgrade` pulito; `alembic heads` = 1 riga; 148
test invariati. **Questo è l'ultimo `batch_alter_table` consentito nel blocco** (D4): dopo T3
nessun ALTER su `transactions`. Corollario: se si volesse aggiungere il `CheckConstraint` mancante su
`source`, va fatto qui o non si fa.

---

## T3 — Migration FTS5 + 3 trigger + popolamento + primo `conftest.py`

**Agente**: schema-agent. **File**: `backend/alembic/versions/000Y_*.py`, `backend/tests/conftest.py`,
test dei trigger.

Tabella virtuale a contenuto esterno (`content='transactions'`, `content_rowid='id'`) su `comment`,
`tag`, `category_raw`, `account`. Tre trigger con la sintassi obbligata di spec §5, `op.execute()`
SQL raw — **mai** API batch. Popolamento iniziale (`'rebuild'`) in coda all'upgrade.

**Il `conftest.py` nasce qui**, non in T4: il test dei trigger ha bisogno di girare in isolamento, e
la fixture che isola il DB era programmata dopo — dipendenza circolare. T3 crea il file con la sola
fixture che gli serve (engine su `tmp_path` + `alembic upgrade head` via `EnvironmentContext`, vedi
T4 per il vincolo sulla strategia); T4 lo **estende**.

**Criteri di accettazione:**

1. **`'integrity-check'` non solleva** dopo insert + update + delete.
2. **D6**: un UPDATE che modifica `comment` o `tag`, seguito da `'integrity-check'`, non solleva —
   verifica che il trigger DELETE usi valori **identici** a quelli indicizzati dall'INSERT
   (`COALESCE` coerente).
3. **Test permanente dei trigger**, committato con la migration e parte della suite di regressione —
   non una verifica di setup. Sequenza obbligata **sulla stessa connessione** su cui Alembic ha fatto
   `upgrade head` (mai su `create_all()`, dove i trigger non esisterebbero affatto e l'asserzione
   sarebbe un falso positivo che passa anche senza il fix):
   a. `alembic upgrade head` sul DB in `tmp_path`;
   b. `SELECT name FROM sqlite_master WHERE type='trigger'` → **3 righe** (è questo passo a rendere
      significativo il passo d);
   c. `batch_alter_table('transactions', recreate="always")` sulla stessa connessione —
      `recreate="always"` è obbligatorio: con `"never"` la tabella non viene ricreata, i trigger
      sopravvivrebbero comunque e il test **non riprodurrebbe D4**;
   d. i 3 trigger esistono **ancora**.
4. **Round-trip completo**: upgrade → `'integrity-check'` OK → downgrade → `SELECT name FROM
   sqlite_master WHERE type IN ('table','trigger') AND name LIKE 'transactions_fts%'` → **0 righe**
   → re-upgrade → 3 trigger e `'integrity-check'` OK.
5. `data/portfolio.db` **intatto** dopo il run.

---

## T4 — Estende `conftest.py` con la fixture FTS completa

**Agente**: schema-agent. **File**: `backend/tests/conftest.py`.

**Estende** il file nato in T3, non lo riscrive. Fixture function-scoped, **no autouse**, nessuna
mutazione di env a livello di modulo.

**Strategia A, obbligata**: engine su `tmp_path` + `EnvironmentContext` esplicito
(`context.configure(connection=conn, …)` + `context.run_migrations()`), bypassando la lettura di
`sqlalchemy.url` da `config.main_option`. **`config.attributes['connection']` non è
un'alternativa**: `run_migrations_online()` costruisce sempre il proprio engine con
`engine_from_config(config.get_section(...))` e non esamina mai `config.attributes` — quella strada
fallirebbe in silenzio.

Perché non basta il monkeypatch di `settings.db_path`: `env.py` rigira a ogni invocazione, quindi il
patch *verrebbe* raccolto — ma dipenderebbe da un ordine di import globale che nessuna asserzione
sorveglia. Se un `conftest.py` futuro importasse `app.db` per primo, l'engine di produzione nascerebbe
su `/data/portfolio.db` prima del patch e la fixture migrerebbe il DB sbagliato **senza fallire**.

**Limite da scrivere accanto al criterio**: `env.py` importa `app.db` direttamente (riga 8) e
`app.db` costruisce l'engine **all'import** (`db.py:12`, livello di modulo). La Strategia A impedisce
ad Alembic di *usare* quell'URL, non impedisce all'engine di *nascere*. Oggi è innocuo perché
`app.db` non esegue DDL all'import; se lo acquisisse, la fixture andrebbe rivista.

**Criterio**: i 148 esistenti verdi e **invariati**; `data/portfolio.db` non esiste / non è stato
toccato dopo il run.

---

## T5 — `backend/app/services/search.py`

**Agente**: main.

- `build_match_expression(q) -> str | None` — token quotati, `"` → `""`, prefix `*`, `None` su
  stringa vuota o soli spazi. Unit test su input ostili: `"`, `*`, `-x`, `NEAR(a b)`, `AND`, `()`,
  `'`, emoji, stringa vuota.
- `fts_available(session) -> bool`.
- `rebuild_fts_index(engine: Engine) -> None`.

**Firma con `engine` esplicito, mai `from app.db import engine`**: nei test punterebbe al DB reale.
Convenzione già seguita da `backup.py`.

---

## T6 — `GET /transactions`: filtri + `q` + `group_by`

**Agente**: main. **File**: `backend/app/routers/transactions.py`.

Nuovi parametri `date_from`, `date_to`, `amount_min`, `amount_max`, `tag`, `q`, `group_by`.
`year_month` resta. Ordinamento invariato `date desc, id desc` (ADR-0020).

`group_by` è un **ramo separato a short-circuit**: ignora `page`/`page_size` e ritorna
`{groups:[{key,count,total}]}`. Senza short-circuit il `LIMIT/OFFSET` si applicherebbe ai gruppi e i
subtotali sarebbero parziali senza alcun errore.

**`_serialize()` invariato**: `q` filtra e basta, nessun campo nuovo nel payload.

**Test obbligatorio**: con `fts_available()` che ritorna `False`, `GET /transactions?q=…` → **503**,
asserzione sullo **status**, non sul messaggio. Senza, il guard è un failure mode silenzioso: se
venisse rotto o rimosso, la ricerca darebbe 500 e la suite resterebbe verde.

---

## T7 — `POST /transactions` + ordinale `#n` + 409

**Agente**: main. **File**: `backend/app/routers/transactions.py`.

Ordine obbligatorio: Pydantic → **lookup `category_id` → 404** → derivazione `category_raw` → hash →
insert con retry. Invertire i due passi centrali produce `category_raw = None` su NOT NULL, cioè un
500 opaco invece di un 404 che dice quale categoria manca.

Prima manuale → hash **base**. Forzatura (`allow_duplicate: true`) → `#1`, poi `#2`. Retry su
`IntegrityError` discriminato per `UNIQUE constraint failed: transactions.hash_dedup`, max 8 giri,
poi 409. **`category_id` validato prima del loop**: con `foreign_keys=ON` (`db.py:24`) una FK
violation è un `IntegrityError` indistinguibile, e il loop girerebbe otto volte per poi dare un 409
fuorviante al posto del 404 corretto.

**Test obbligatori:**

1. `category_id` inesistente → **404**, `SELECT COUNT(*) FROM transactions` **invariato**; il 404
   arriva **prima** di qualunque tentativo di insert, non come conseguenza di un `IntegrityError`.
2. Dopo un `POST` valido con 200: `SELECT source, import_batch_id FROM transactions WHERE
   hash_dedup = '<hash calcolato>'` → esattamente `source='manual'` e `import_batch_id IS NULL`.
   Assert **diretto sul DB**, non derivato dal JSON (i due campi non devono per forza comparire nel
   body). L'importer deduplica con `.in_()` su `hash_dedup`; se una branch futura filtrasse per
   `source`, un valore errato causerebbe re-import silenzioso delle manuali.
3. L'importer con `.in_()` **non** matcha `#1`.
4. Ramo di retry: ordinale già occupato → successo al secondo giro; costante → 409 e non loop
   infinito.

**Copertura di concorrenza dichiarata, non simulata**: la garanzia di assenza di 500 sotto
concorrenza è best-effort su pysqlite serializzato; la suite copre **solo il path sequenziale**.
Nessun test a due thread — la fixture in-memory con `StaticPool` ha una connessione sola e non può
avere un secondo writer; su quella file-based introdurrebbe `database is locked` intermittente.

### ▸ CHECKPOINT UMANO 1 — contratto API delle transazioni

Congela: shape del 409, semantica di `allow_duplicate`, shape di `group_by`, nomi dei parametri.
Tutto T8-T12 ci si appoggia. Verifica: `curl` reali sui tre casi (normale, duplicato, forzatura),
`alembic heads` = 1 riga, `downgrade` e `upgrade` su un DB con righe, suite verde.

---

## T8 — `ApiError` con `status` e `body`

**Agente**: react-ui-agent. **File**: `frontend/src/lib/api.ts`.

Classe `ApiError extends Error` con `.status` e `.body`; `message` = `detail` se stringa, altrimenti
fallback leggibile (mai `"[object Object]"`). Applicata **anche** a `uploadFile`, che oggi duplica lo
stesso difetto.

**Criterio**: grep di tutti i `catch` esistenti — `err.message` continua a funzionare ovunque;
`tsc` pulito.

---

## T9 — Primitive UI mancanti

**Agente**: react-ui-agent. **File**: `frontend/src/components/ui/`.

`input`, `label`, `select` in **HTML nativo** con classi Tailwind, come ogni altro form del progetto.
Sono già coperti dalla regola globale del commit `7157e97` (`index.css @layer base`), quindi non
serve alcun token nuovo. **Nessun `react-hook-form`, nessun `zod`**: assenti dal progetto, non si
introducono per un form di otto campi.

**Vincolo: T9 non tocca `index.css`.** Verifica prima di chiudere: `git diff --name-only` **non**
include `frontend/src/index.css`. Se lo include, la parallelizzazione con T12 decade e i due task
vanno in sequenza, T9 prima di T12.

---

## T10 — Form manuale + UX del 409

**Agente**: react-ui-agent. **File**: `frontend/src/pages/Transactions.tsx`, nuovo
`components/TransactionForm.tsx`.

**Dialog, non route nuova.** Aperto da un `<button>` dentro `/transazioni` via **React state**, senza
toccare `window.location.pathname` né `window.location.hash`: **niente hash-routing**
(`/transazioni#nuovo` non romperebbe `test_spa_routing.py` ma introdurrebbe navigazione non voluta).

**Criteri:**

- aprire il dialog **non cambia l'URL**; il back button del browser **non** lo chiude;
- `SPA_ROUTES` in `main.py` **invariata**: `test_spa_routing.py` non richiede modifiche;
- il catch usa `ApiError` (T8, **non** `Error` nativo): `err.status === 409` mostra "Inserisci
  comunque", `err.body` contiene la gemella. Verificato che tornando a `Error` nativo il pulsante
  **non** compare — così la dipendenza da T8 è rumorosa, non silenziosa;
- la mutation invalida `['transactions']` **e** `['insights']`. Oggi **nessuna** mutation invalida
  `['insights']`: senza, la dashboard resterebbe ferma dopo un inserimento.

---

## T11 — Filtri avanzati + stato nell'URL

**Agente**: react-ui-agent. **File**: `frontend/src/pages/Transactions.tsx`, `vite.config.ts`.

`useSearchParams` (prima volta nel progetto). **`queryKey` estesa a tutti i filtri nello stesso
commit**: aggiungerne uno allo state senza aggiungerlo alla chiave fa servire la cache del filtro
precedente — dati vecchi, nessun refetch, nessun errore.

**Verifica del proxy dev con query string**, con output nel ledger:

```bash
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' -H 'Accept: text/html' 'http://localhost:5173/transazioni?date_from=2026-01&q=parola'
```

Deve servire la SPA; `GET /transactions?...` deve continuare a raggiungere il backend. Nota:
`/transazioni` non inizia per `/transactions` (divergono alla settima lettera), quindi oggi non
collide — la verifica serve a documentarlo, non a sospettarlo.

**Debito ancorato nel codice**: commento alla riga del bypass in `vite.config.ts` —

```
// TODO(Blocco-C): req.url === '/backup-restore' non copre query string — se /backup-restore acquisisce filtri, aggiornare il bypass
```

più una riga nel ledger fra i punti da riaprire all'apertura del Blocco C. `req.url` include la query
string, e T11 è il commit che rende quel pattern desiderabile altrove: è lì che il promemoria deve
nascere.

---

## T12 — Token `--chart-6` e `--chart-7`

**Agente**: react-ui-agent. **File**: `frontend/src/index.css`, `tailwind.config.js`,
`frontend/src/lib/chart-config.ts`.

`chartColors` da 5 a 7 elementi, **indici 0-4 invariati byte per byte**. Token in `:root` **e**
`.dark`: mancarne uno produce un difetto visibile in un solo tema — la classe di bug del commit
`7157e97`. Contrasto verificato su entrambi i temi, come nell'audit del Blocco A.

---

## T13 — Service + `GET /insights/panels`

**Agente**: dashboard-agent. **File**: `backend/app/services/insights.py`,
`backend/app/routers/insights.py`.

Funzioni nuove **keyword-only**, stesso stile delle 4 esistenti, nello **stesso modulo**. Implementa
il contratto congelato in spec §7, **alla lettera**.

**Criteri:**

- `GET /insights` **non toccato**; i 5 test F5 verdi e **invariati**.
  `test_insights_empty_db_returns_empty_lists` è **il più fragile dei cinque**: asserisce sul body
  intero, non su singole chiavi.
- `ai/tools.py` **non toccato** — scelta dichiarata, non dimenticanza.
- **Prescrizione di review**: il reviewer verifica che nessuna funzione nuova sia richiamata dal
  router `GET /insights` né modifichi variabili di modulo condivise. Diff su `services/insights.py`
  letto **riga per riga**, diff su `routers/insights.py` confermato **vuoto**.
- Output di `test_insights_empty_db_returns_empty_lists` **copiato nel ledger** come evidenza: il
  conteggio verde non basta.

### ▸ CHECKPOINT UMANO 1b — contratto `/insights/panels`

Verifica su **risposta reale**, prima che T14 lo consumi: forma delle chiavi, `delta_pct` a `null`
quando il mese precedente è zero, donut ≤ 7 elementi con `"Altro"` aggregato dal backend, e
soprattutto il **troncamento della finestra `months`** — array più corti di 12 con il dataset che
parte dal 2026.

CP1b esiste perché CP1 congela solo il contratto delle transazioni; spostare CP1 dopo T13 avrebbe
lasciato tutto il frontend T8-T12 senza alcun checkpoint.

---

## T14 — Sei pannelli dashboard

**Agente**: dashboard-agent. **File**: `frontend/src/pages/Dashboard.tsx` + componenti.

Saldo cumulato · cash flow mensile · donut categorie · trend risparmio · confronto mese su mese ·
4 KPI card. Tutti su `chartColors`; **mai** `getComputedStyle`, **mai** esadecimali (ADR-0026).
`queryKey: ['insights','panels', …params]`.

**Il frontend non assume 12 punti**: gli array sono di lunghezza variabile per il troncamento di
`months`.

**Zero occorrenze di "patrimoni"**: il dato è un **saldo cumulato**, non un patrimonio netto — quello
richiederebbe un modello asset/passività che non esiste.

### ▸ CHECKPOINT UMANO 2 — giudizio visivo

Ultimo punto in cui la UI è modificabile a costo basso. Leggibilità dark dei sei pannelli, wording,
che il dialog del 409 mostri davvero la gemella, che i colori 6 e 7 non collidano con i primi 5.
Dopo questo, T15 e T16 sono hardening.

---

## T15 — Restore: `alembic upgrade head` + rebuild FTS

**Agente**: main. **File**: `backend/app/backup.py` (nuova `upgrade_schema_to_head()`),
`backend/app/routers/backup.py`.

Ordine obbligato: **copia → upgrade → rebuild → replica**. Invertire copia e upgrade migrerebbe il DB
pre-restore, che la copia sovrascriverebbe subito dopo: migration persa, nessun errore.

La logica di schema vive in `backend/app/backup.py`, **non** dentro `restore_from_backup()` — quella
è filesystem-pura ed è testata come tale in `test_backup_core.py` su un engine senza FTS. Il router
orchestra.

**Struttura dei blocchi.** L'endpoint ha oggi **due `try/except` separati e indipendenti** — restore
(che rilancia `HTTPException` su `FileNotFoundError`) e replica (best-effort) — con **nulla in
mezzo**. I due nuovi si inseriscono lì, ciascuno nel **proprio** `try/except` autonomo: quattro
blocchi distinti. Un `except` condiviso collasserebbe i messaggi in uno.

| Cosa fallisce | Stato reale | Messaggio |
|---|---|---|
| `alembic upgrade head` | file già sovrascritto, schema incoerente | "Restore completato ma migration fallita: il DB potrebbe essere incoerente. Ripetere il restore da un backup valido." |
| rebuild FTS, dopo migration OK | schema integro, manca solo l'indice | "Restore e migration OK, ma rebuild indice FTS fallito: la ricerca testuale non funzionerà. Riavviare il backend per un rebuild automatico." |
| refresh replica | tutto integro | già best-effort, non blocca |

**`threading.Lock` di modulo** che avvolge tutti e quattro i blocchi nella loro interezza, non i
singoli step. Due restore paralleli sono già distruttivi oggi (`engine.dispose()` + `shutil.copy2`
senza protezione): il lock chiude anche quel difetto pre-esistente.

**Body del 200**: `migrations_applied: N` e, quando `N > 0`, `schema_note` (ADR-0034).

**Test obbligatori:**

1. **D5 già attivo oggi**: restore di un backup con schema `0002` (pre-`settings`) → dopo copia e
   upgrade la tabella `settings` esiste e il backend si avvia, smoke `/health` → 200.
2. **Migration sul file giusto**: `SELECT version_num FROM alembic_version` letto **sul file di
   `settings.db_path`** dà la head corrente. Asserzione sul **DB**, non su `migrations_applied` nel
   body — altrimenti passerebbe un 200 con schema fermo a quello del backup, senza errori né log.
3. **Failure path caso 2**: rebuild che solleva dopo una migration riuscita → il 500 porta il
   messaggio del caso 2, **non** quello del caso 1. Senza questa asserzione i due rami sono
   indistinguibili da fuori.

---

## T16 — Chiusura blocco

**Agente**: main. **File**: `backend/app/main.py`, test relativo, `CLAUDE.md`,
`docs/ARCHITECTURE.md`.

- `version` / `phase` → **13**, insieme al test che li asserisce. Il test porta un **commento
  inline**, testo esatto:

  > Convenzione: `phase` = numero dell'ultima fase del **branch corrente** al merge, non il massimo
  > globale. Il Blocco B porta phase da "9" a "13" perché F11/F12/F13 completano tutte in questo
  > branch. Il salto da 9 a 13 è atteso: F10 appartiene al Blocco C e non è stata completata qui.
  > Chiudendo il Blocco C per intero il valore diventerà "14". Se Blocco C chiudesse solo F10,
  > phase resterebbe "13" perché "14" (F14) non è ancora mergiata.

- `git grep -i "patrimon" -- "*.tsx" "*.ts"` → **zero occorrenze**. Radice della parola, così copre
  `patrimonio`/`patrimoniale`/`patrimoni` in tooltip, `aria-label`, `title` e stringhe interpolate.
- `alembic heads` = **1 riga**; `upgrade head` e `downgrade` fino a `0002` su DB di prova.
- Suite completa verde (148 invariati + i nuovi).
- **Re-run del gate T0** sull'immagine finale.
- Documenti allineati.

---

## Verifica finale, prima del merge

Oltre ai criteri per task:

- Build del **container di produzione** e navigazione reale delle pagine — non solo dev server — in
  **dark e light**, console pulita.
- Ogni numero dei sei pannelli incrociato contro i totali noti del dataset F2: **331 transazioni,
  uscite 9937.70 €, entrate 19497.14 €**.
- `docker compose config` valido, `/health` con `phase` aggiornata.
- **Suite permanente dei trigger FTS** (T3) inclusa nel run di regressione — l'unica cosa che
  impedisce a un task futuro di riaprire D4 senza accorgersene.
- **Failure path del restore** (T15) eseguito davvero, con output del 500 e del suo messaggio nel
  ledger. Un failure mode dichiarato ma mai eseguito è documentazione, non una garanzia.
