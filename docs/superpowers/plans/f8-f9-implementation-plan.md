# Blocco A — F8 dark mode + F9 settings — piano implementativo

- **Status**: Approvato per l'esecuzione — 2026-07-21 (7 giri di review, esiti nelle sezioni
  "Rettifiche" in coda)
- **Spec di dettaglio**: `docs/superpowers/specs/2026-07-21-f8-f9-detail-spec.md`
- **Branch**: `f8-f9-theme-settings` (aperto, T0 eseguito)
- **Esecuzione**: subagent-driven-development — un task per subagent, review dopo ciascuno,
  3 checkpoint umani

## Context

Il Blocco A (`f8-f9-theme-settings`) è la prima fase di codice della roadmap F8-F14. F0-F6 e F-DEBT
sono chiuse, F7 è parcheggiata in attesa hardware e non va toccata. La roadmap approvata
(`docs/superpowers/specs/2026-07-21-f8-f14-roadmap-design.md`, ADR-0026/0027) fissa cosa fare; la
sessione di pianificazione ha prodotto la spec di dettaglio, e sette giri di review dell'utente
hanno raffinato il piano (correzioni C1-C5, F1-F3, rettifiche puntuali successive).

Il progetto oggi non ha alcun tema scuro (`tailwind.config.js` senza `darkMode`, `index.css` di 3
righe, 0 CSS custom properties) e nessun punto di configurazione in UI. Durante l'esplorazione è
emerso un difetto **già in produzione**, verificato sul container attivo:

```
GET /backup      (Accept: text/html) -> 200 application/json   <- SPA rotta
GET /transazioni (Accept: text/html) -> 200 text/html          <- ok
```

`GET /backup` API e pagina SPA `/backup` condividono il path esatto; FastAPI matcha il router prima
del catch-all, quindi un hard-refresh mostra JSON grezzo. DEBT-04/ADR-0022 avevano corretto solo il
dev server Vite. La pagina `/settings` prevista da ADR-0027 nascerebbe con lo stesso difetto.

Esito atteso: dark mode completa e verificabile per esaurimento, configurazione centralizzata su
`/impostazioni` con secret non esfiltrabili, e la classe di difetti di routing chiusa da un test.

## Deliverable documentali (prima del codice)

1. `docs/superpowers/specs/2026-07-21-f8-f9-detail-spec.md` — spec di dettaglio
2. `docs/superpowers/plans/f8-f9-implementation-plan.md` — questo piano
3. **ADR-0033** in `docs/DECISIONS.md` — nuovo
4. Rettifiche in coda ad ADR-0026 e ADR-0027 (sezione "Rettifica 2026-07-21, spec di dettaglio
   Blocco A"), non ADR nuovi: sono correzioni di dettaglio implementativo, non cambi di decisione

### ADR-0033 — Nessuna route SPA condivide un path esatto con un endpoint API

Regola: per ogni path servito, o è un endpoint API o è una route SPA, mai entrambi. Le pagine restano
in italiano (`/transazioni`, `/conti`, `/impostazioni`, `/backup-restore`), gli endpoint in inglese.
Verificata da un test di regressione, non dalla disciplina. Supera ADR-0022, che aggirava il sintomo
nel solo dev server con un bypass su header `Accept`.

### Rettifiche dichiarate agli ADR esistenti

| ADR | Punto | Rettifica |
|---|---|---|
| 0026 | p.2 | l'elenco token è incompleto: aggiunti `--primary-foreground`, `--destructive-foreground`, `--success-foreground`, `--warning`, `--warning-foreground` (C4) |
| 0026 | p.6 | `chart-config.ts` esporta stringhe `hsl(var(--chart-N))`, **non** legge `getComputedStyle`: quest'ultimo si valuta al mount e lascia i grafici col colore vecchio dopo il toggle |
| 0026 | M8.4 | `ChartContainer`/`ChartTooltip` shadcn **non** si portano: il loro compito (iniettare var per serie, avvolgere `ResponsiveContainer`) è già coperto. Serve solo `contentStyle` in `chart-config.ts` |
| 0026 | contesto | gli esadecimali sono **6**, non 5: `Dashboard.tsx:71` ne ha due sulla stessa riga (`stroke="#7c3aed" fill="#ddd6fe"`) |
| 0027 | M9.5 | la pagina è `/impostazioni`, l'endpoint `/settings` (ADR-0033). Il vincolo di prodotto "unico punto di configurazione" resta identico |
| 0027 | p.8 | il test blacklist si riformula: `secrets_status` **deve** contenere i nomi delle chiavi (p.6 lo impone), quindi si asseriscono i **valori**, non i nomi (vedi T3) |

---

## Vincoli permanenti

- Blocco B, Blocco C, F7, ADR-0024/0025 e `docker-compose.yml`: **non toccare**.
- Alembic: numero revision e `down_revision` si fissano **al merge**. `alembic heads` = 1 riga.
  Blocco A mergia per primo, quindi `0003` su `down_revision = "0002"` è l'ipotesi, da riconfermare.
- Nessun valore di secret attraversa un endpoint o l'UI (ADR-0027 p.6).
- Metabase, ingestion, dedup, AI: logica invariata. L'unica firma toccata fuori da F8/F9 è quella di
  `parse_master_sheet_xlsx` (T4), e solo per togliergli la lettura di `settings`.

---

## Task

Ordine backend-first (decisione D4): nessun componente scritto due volte. Agente indicato per task;
esecuzione in subagent-driven-development, un task per subagent, review dopo ciascuno.

### Fase 0 — Prerequisiti operativi

**T0 — Apertura branch** · `main` · dip: nessuna
- `git checkout master && git pull` (se remoto configurato), poi `git checkout -b
  f8-f9-theme-settings` — il nome è quello fissato dalla roadmap (sezione 4 della spec F8-F14).
  **Nessun commit fuori dal branch.**
- Verifica hook attivo: `git config core.hooksPath` -> `.githooks` (ADR-0011); se vuoto,
  riattivarlo prima del primo commit.

### Fase 1 — Backend settings (F9)

**T1 — Modello `Settings` + revision Alembic** · `schema-agent` · dip: T0
- `backend/app/models.py`: classe `Settings` (`key` TEXT PK, `value` TEXT, `updated_at`). Rimuovere
  dalla docstring del modulo la nota "`settings` (F4) sarà aggiunta in una fase successiva".
- `backend/alembic/versions/0003_settings.py` sul modello di `0002_category_raw_and_pending.py`.
- Accettazione: `upgrade head` e `downgrade` fino a `0002` su DB di prova; `alembic heads` = 1 riga.

**T2 — Registro e accessor** · `schema-agent` · dip: T1
- Nuovo `backend/app/services/settings.py`:
  - `WHITELIST`: `key -> {type, default, env_attr, applies_when}` per `theme`, `metabase_url`,
    `ai_history_max_turns`, `import_min_year`, `backup_retention`, `backup_on_startup`.
    `applies_when` è una **stringa libera in italiano** (es. `"immediato"`, `"solo al boot
    successivo"`, `"immediato, dalla domanda successiva"` — i testi della tabella ADR-0027 p.4):
    T13 la rende come testo secondario (`text-muted-foreground`) accanto al campo, senza badge
    colorati — valore informativo, non enum a stati. Se in futuro servirà distinguere visivamente
    "immediato" da "solo al boot", si aggiungerà `applies_when_type:
    Literal["immediate","restart"]` con una rettifica ad ADR-0027; per ora la stringa basta.
  - `BLACKLIST`: `frozenset({"ai_api_key", "google_sa_key_path", "gdrive_backup_folder_id"})`.
  - `get_effective(key, session=None) -> (value, source)` con precedenza **DB > env > default**.
    **`session=None` apre una `SessionLocal()` propria e la chiude in `finally`**: `run_backup()` e
    `import_historical_dry_run` girano senza sessione iniettata (T4, T5).
  - `set_values(session, mapping)` — solo whitelist, coercizione di tipo, transazione unica.
- `ai_history_max_turns` entra in whitelist ora ma **non ha consumatore fino a F14**: dichiarato in
  spec e in un commento, non nascosto.
- Accettazione: test precedenza DB > env > default per ogni chiave; test coercizione tipi;
  `set_values` su chiave non-whitelist non scrive nulla (rollback completo); test del ramo
  `session=None` (la sessione interna viene chiusa anche in caso di eccezione).

**T3 — Router `/settings`** · `schema-agent` · dip: T2
- `backend/app/routers/settings.py`, incluso nel **blocco `app.include_router(...)` esistente di
  `main.py:33-39`**, in coda agli altri sette. Nessun punto di inserimento speciale: tutto il blocco
  sta già prima dell'`if os.path.isdir(FRONTEND_DIST)` che registra il catch-all, quindi l'ordine
  richiesto da ADR-0021 è garantito dalla struttura attuale.
- **Import del router — obbligatorio l'alias.** `main.py` ha già `from app.config import settings`
  (riga 11), usato da `if settings.backup_on_startup:` nel lifespan e da `settings.db_path` in
  `/health`. Aggiungere `settings` nudo alla riga
  `from app.routers import accounts, ai, backup, categories, imports, insights, transactions`
  **shadowerebbe** `app.config.settings` (l'import dei router viene dopo) → `AttributeError` al
  primo boot. Forma corretta, in ordine alfabetico tra `insights` e `transactions`:
  `from app.routers import accounts, ai, backup, categories, imports, insights, settings as settings_router, transactions`
  e `app.include_router(settings_router.router)`. Prima di ogni altra modifica al file: verificare
  che l'import sia presente in questa forma; se assente, aggiungerlo.
  - `GET /settings` -> `{settings: [{key, value, source, applies_when}], secrets_status: {<nome>: {configured: bool}}}`
  - `PUT /settings` -> body dict di chiavi, applicate in una sola transazione; chiave illegale
    rifiuta l'intero body con **400**.
- **Test blacklist a 3 asserzioni** (riformulazione di ADR-0027 p.8):
  1. iniettate sentinelle in `config.settings` (`ai_api_key`, `google_sa_key_path`,
     `gdrive_backup_folder_id`), nessuna delle tre stringhe compare nel JSON serializzato di `GET /settings`;
  2. nessuna chiave blacklistata compare dentro l'array `settings[]`;
  3. `PUT` su chiave blacklistata e `PUT` su chiave inesistente ritornano **400 con messaggio
     identico** — un messaggio diverso permetterebbe di enumerare la blacklist.

**T4 — `import_min_year`: parser puro + passaggio dal router** · `schema-agent` · dip: T2

Correzione di due difetti insieme, entrambi verificati sul codice. `settings` compare in
`backend/app/ingestion/master_sheet_parser.py` in **cinque punti**; i numeri di riga sotto sono
indicativi (la docstring di modulo è lunga ~40 righe e sposta tutto) — **l'ancora è la citazione,
e il comando di individuazione è il grep di accettazione**, che non dipende dai numeri:

- **Due ruoli semantici nel codice**, non due posizioni della stessa cosa:
  - `sheet = sheet_name or str(settings.import_min_year)` (~126, prima riga eseguibile della
    funzione) -> **nome del tab Excel**;
  - `current_year = settings.import_min_year` (~151, dentro il blocco
    `if isinstance(marker, str) and marker in ITALIAN_MONTHS:`) -> **anno attribuito alle righe**
    che seguono un marcatore mese italiano (`Gennaio`..`Dicembre`) privo di data esplicita.

  I due ruoli oggi coincidono per caso. Passando `sheet_name="2027"` il parser aprirebbe il tab 2027
  e daterebbe al 2026 le righe interessate: **bug latente già presente**, non introdotto da questa
  fase. **Scope preciso del bug** (per non generare aspettative sbagliate nei test): l'assegnazione
  scatta **solo** nel ramo `ITALIAN_MONTHS`, e i marcatori mese esistono — dice la docstring stessa —
  "solo per i blocchi Luglio-Dicembre". Nei blocchi gennaio-giugno `current_year` arriva dalle
  righe-data reali (`datetime`) ed è sempre corretto. Il mis-dating colpisce quindi le sole righe la
  cui data discende da un marcatore: le "Entrate" e l'attribuzione mese/anno dei "Totale %" nei
  blocchi con marcatore, non l'intero tab.
- **Due menzioni in docstring** — modulo e funzione ("default `str(settings.import_min_year)`,
  ADR-0012") — più l'**import** `from app.config import settings`: dopo il refactor le docstring
  documentano `sheet_year` e l'import muore. Il grep di accettazione copre tutti e cinque i punti
  automaticamente.
- `backend/app/routers/imports.py` **non legge affatto** `import_min_year`: le righe 258 e 293
  chiamano `parse_master_sheet_xlsx(io.BytesIO(content))` senza argomenti e lasciano leggere al
  parser. Non c'è una lettura da riagganciare: c'è un passaggio da **aggiungere**.

Punto di partenza esatto — `sheet_name` **esiste già**, è `sheet_year` che manca:

```
master_sheet_parser.py:110  def parse_master_sheet_xlsx(file: str | BinaryIO, sheet_name: str | None = None) -> dict:
imports.py:258              parsed = parse_master_sheet_xlsx(io.BytesIO(content))
imports.py:293              parsed = parse_master_sheet_xlsx(io.BytesIO(content))
```

I due call site non passano `sheet_name`, quindi cade sul default `None`: **è quel default a
innescare la lettura di `settings`**, in entrambi i ruoli.

Intervento:
- In `backend/app/routers/imports.py`: aggiungere
  `from app.services.settings import get_effective` agli import di modulo, dopo gli import interni
  esistenti (`from app.` ...), in ordine alfabetico con gli altri import locali. Import di sola
  funzione: nessun rischio di shadowing (a differenza di T3). È prerequisito dei due call site
  modificati sotto.
- `sheet_name` passa da **opzionale a obbligatorio**; `sheet_year: int` è un **parametro nuovo**.
  Questo implica due modifiche al parametro `sheet_name` rispetto alla firma attuale
  `(file, sheet_name: str | None = None)`:
  1. rimuovere `| None` dal type hint -> `sheet_name: str`
  2. rimuovere `= None` -> parametro posizionale obbligatorio.
  Un diff che modifica solo il nome senza rimuovere il default lascerebbe il parametro ancora
  opzionale e non romperebbe i call site, mascherando il bug.
  Firma risultante `parse_master_sheet_xlsx(file, sheet_name: str, sheet_year: int)`.
- **Le 5 occorrenze di `settings` da eliminare, nell'ordine in cui compaiono nel file** (istruzioni
  complete qui, indipendenti dal grep di accettazione che fa da gate finale):
  1. docstring di **modulo** — **una sola occorrenza** (verificata: 5 match totali di `settings`
     nel file, non 6), la frase nel paragrafo "Tracciamento mese corrente": sostituire
     "(year sempre `settings.import_min_year` per questo tab)" con
     "(year sempre `sheet_year` per questo tab)";
  2. rimuovere `from app.config import settings` (import morto dopo il refactor);
  3. docstring di **funzione** `parse_master_sheet_xlsx`: sostituire "default
     `str(settings.import_min_year)`, ADR-0012" con "parametro obbligatorio `sheet_year: int`";
  4. `sheet = sheet_name or str(settings.import_min_year)` -> `sheet = sheet_name`
     (niente fallback: `sheet_name` è ora obbligatorio);
  5. `current_year = settings.import_min_year` -> `current_year = sheet_year`
     (blocco `ITALIAN_MONTHS` — anno attribuito alle righe che seguono un marcatore mese italiano).
- `imports.py`: entrambi i call site risolvono il valore con `get_effective("import_min_year")` —
  **riga 258 senza sessione** (`import_historical_dry_run` non ha `Depends(get_session)`, lavora su
  DB effimero), riga 293 con la sessione iniettata — e passano `sheet_name=str(min_year)`,
  `sheet_year=min_year`.
- **Breaking change contenuto e verificato**: i call site di `parse_master_sheet_xlsx` in tutto il
  repo sono **esattamente due** (`imports.py:258,293`), entrambi aggiornati da questo task.
  **Nessun test esistente chiama il parser né gli endpoint `/import/historical/*`** (grep repo-wide
  su `backend/`, incluso `backend/tests/`: zero match) — non c'è nessun chiamante di terze parti da
  aggiornare.
- Accettazione:
  1. `grep -n "settings" backend/app/ingestion/master_sheet_parser.py` -> **0 match**
     (copre codice, entrambe le docstring e l'import in un colpo solo);
  2. `grep -rn "parse_master_sheet_xlsx(" backend/` -> solo la definizione e i due call site di
     `imports.py`, entrambi con `sheet_name` e `sheet_year` espliciti;
     `grep -n "from app.services.settings import" backend/app/routers/imports.py` -> esattamente
     1 match;
  3. nuovo `backend/tests/test_master_sheet_parser.py` (oggi il parser **non ha alcun test**), con
     il ramo marcatori coperto **separatamente**: `sheet_year=2025` con un marcatore mese italiano
     nel foglio produce `current_year=2025` **indipendentemente dal nome del tab** — è l'asserzione
     che fissa il contratto e impedisce il ritorno del bug latente.

**T5 — `backup_retention` e `backup_on_startup`** · `schema-agent` · dip: T2

| File | Chiave | Punto | Nota |
|---|---|---|---|
| `backend/app/routers/backup.py` | `backup_retention` | righe 43 e 48, dentro `run_backup()` | `run_backup()` è chiamato anche dal thread di avvio: nessuna sessione disponibile -> `get_effective(..., session=None)` |
| `backend/app/main.py` | `backup_on_startup` | lifespan, riga `if settings.backup_on_startup:` (ancora testuale, nessun numero: le review hanno contato 25 vs 26 — la citazione è inequivocabile) | letto **al boot**, coerente con "solo al boot successivo" della whitelist |

- **L'import `config.settings` in `main.py` non va rimosso**: `main.py:11` lo usa anche per altro
  (`settings.db_path` in `/health`, riga 45 — verificato). T5 sostituisce **solo** l'occorrenza
  `settings.backup_on_startup` con `get_effective("backup_on_startup")` e lascia intatto ogni altro
  riferimento a `config.settings`.
- Accettazione: test che scrive la chiave nel DB e verifica il cambio di comportamento per entrambi;
  `grep -rn "settings\.\(import_min_year\|backup_retention\|backup_on_startup\)" backend/app` non
  restituisce match fuori da `services/settings.py`.
- **Coordinamento con l'altro task su `main.py`**: T5 modifica la riga del lifespan
  (`if settings.backup_on_startup:`); T6b estrae il blocco SPA (righe 50-70). Righe diverse, nessuna
  sovrapposizione, ma **T5 si committa prima di T6b** per evitare rebase conflict — l'ordine è
  dichiarato come dipendenza nell'intestazione di T6b.

> **CHECKPOINT UMANO 1** — suite completa verde (100 esistenti + nuovi), `alembic heads` = 1 riga,
> `GET /settings` ispezionata a mano.

### Fase 2 — Routing (ADR-0033, C1, F3)

**T6a — Rinomine di route (frontend)** · `react-ui-agent` · dip: nessuna (parallelizzabile con
Fase 1)
- `frontend/src/App.tsx:23`: `path="/backup"` -> `path="/backup-restore"`; nuova
  `<Route path="/impostazioni" element={<Settings />} />` (pagina placeholder, riempita in T13).
  A fine T6a le route SPA in `App.tsx` sono **8** — è l'input di T6b.
- `frontend/src/components/Sidebar.tsx:10`: `to: '/backup-restore'`, **label resta `'Backup'`**;
  ottava voce `{ to: '/impostazioni', label: 'Impostazioni' }`.
- `frontend/vite.config.ts` righe 24-38 — blocco verificato in sessione di pianificazione (lettura
  integrale del file), è quello descritto da ADR-0022. **Primo passo di T6a**: ri-verifica lampo
  `grep -n "bypass" frontend/vite.config.ts` — se il blocco non c'è più, fermarsi e riallineare il
  piano prima di toccare il file:
  ```js
  '/backup': {
    target: 'http://localhost:8000',
    bypass: (req) => { if (req.headers.accept?.includes('text/html')) { return req.url } },
  },
  ```
  Torna proxy semplice (`'/backup': 'http://localhost:8000'`) — la collisione non esiste più.
  Aggiungere `'/settings': 'http://localhost:8000'`. Il commento ADR-0022 (righe 24-30) è sostituito
  dal riferimento a ADR-0033.
- **Non si toccano** `frontend/src/pages/Backup.tsx:23,27,32` né `backend/tests/test_backup_router.py`:
  sono chiamate all'**endpoint** `/backup`, non alla route SPA. Verificato.
- **Nessun redirect** da `/backup` a `/backup-restore`: app single-user su rete locale, nessun link
  esterno o bookmark condiviso da preservare (ADR-0009). Dichiarato, non dimenticato.

**T6b — `mount_spa()` e `SPA_ROUTES` (backend)** · `schema-agent` · dip: **T6a (bloccante:
`SPA_ROUTES` si deriva dall'`App.tsx` già modificato), T3, T5 (ordine su `main.py` dichiarato
in T5)**

La dipendenza da T6a è ciò che rende **meccanicamente impossibile** scrivere una `SPA_ROUTES` a 7
voci: quando T6b parte, `App.tsx` contiene già `/backup-restore` e `/impostazioni`, e l'accettazione
sotto la vincola comunque.

- `backend/app/main.py:50-65`: oggi il blocco è **inline** dentro `if os.path.isdir(FRONTEND_DIST):`
  e contiene **tre** elementi, tutti da spostare nella nuova funzione `mount_spa(app, dist_dir)`:
  1. `app.mount("/assets", StaticFiles(...), name="frontend-assets")` (riga 53)
  2. `@app.get("/favicon.svg")` -> `favicon()` (righe 59-61, DEBT-02)
  3. `@app.get("/{full_path:path}")` -> `serve_frontend()` (righe 63-65, catch-all)

  La funzione è chiamata a import time se la directory esiste: comportamento di produzione
  **identico**, ma invocabile su un'app di prova. Il ramo `else` (righe 66-70, fallback JSON su `/`
  per dev locale) **resta inline dov'è**: `mount_spa()` contiene solo i tre elementi del ramo `if`,
  non l'`else`.

  Nel codice attuale il ramo `else:` è l'immediato successore del blocco
  `if os.path.isdir(FRONTEND_DIST):`, senza righe vuote o separatori tra i due. `mount_spa()`
  estrae i soli tre elementi del ramo `if`; la riga `else:` e la funzione `root()` che contiene
  non vengono toccate né spostate. L'agente deve assicurarsi che dopo il refactor la struttura sia:
  ```python
  if os.path.isdir(FRONTEND_DIST):
      mount_spa(app, FRONTEND_DIST)
  else:
      @app.get("/")
      def root():
          return {"app": "Personal Portfolio", "docs": "/docs"}
  ```
  senza orphan di `else:` né perdita della funzione `root()`.
- **`SPA_ROUTES`**: `frozenset[str]`, definita in `backend/app/main.py` a livello di modulo — fuori
  dall'`if`, così esiste anche senza `frontend_dist` (T7 test 1 ne dipende in entrambi gli ambienti).
  Commento incrociato che nomina `frontend/src/App.tsx` come sorgente da tenere allineata.
- Accettazione T6b (chiude il rischio "costante parziale" anche se qualcuno ignorasse la
  dipendenza): `SPA_ROUTES` contiene esattamente le 8 voci `/`, `/transazioni`, `/import`,
  `/categorie-pending`, `/conti`, `/backup-restore`, `/assistente-ai`, `/impostazioni`;
  `"/backup" not in SPA_ROUTES`. Queste asserzioni entrano nel test 1 di T7 come contenuto, non
  restano prosa di piano.

**T7 — Test di routing (due test, deterministici)** · `schema-agent` · dip: T3, T6b

Il test esistente `backend/tests/test_ai_router.py:169-198` ispeziona `app.routes` **proprio per non
dipendere** da `frontend_dist`, e per questo non può da solo provare che una route SPA venga servita.
Servono due test distinti:

1. **Invariante ADR-0033** (funziona con e senza `frontend_dist`, perché `SPA_ROUTES` è definita a
   livello di modulo in `main.py`, fuori dall'`if`): l'intersezione fra `SPA_ROUTES` e l'insieme dei
   path esatti degli endpoint API registrati è **vuota**; più le asserzioni di contenuto ereditate
   da T6b (`SPA_ROUTES` == le 8 voci attese, `"/backup" not in SPA_ROUTES`). È il test che rende la
   regola verificabile invece che dichiarata, e fallisce sia il giorno in cui qualcuno aggiunge
   `GET /impostazioni`, sia se la costante nasce parziale.
2. **Comportamento HTTP**: il test costruisce una `FastAPI()` di prova, include i router reali, chiama
   `mount_spa(app, tmp_dist)` su una directory temporanea con `index.html` e `assets/`, e interroga
   con `TestClient` mandando `Accept: text/html`:

   | Richiesta | Atteso |
   |---|---|
   | `GET /settings` | JSON (endpoint API) |
   | `GET /impostazioni` | `text/html` (SPA) |
   | `GET /backup` | JSON (endpoint API) |
   | `GET /backup-restore` | `text/html` (SPA) |

   Nessun `importlib.reload`, nessuna directory creata nel repo, nessuna dipendenza dall'ordine di
   esecuzione della suite.

> **CHECKPOINT UMANO 2** — hard-refresh reale del browser sulle 4 URL, sul container di produzione.

### Fase 3 — Tema (F8)

**T8 — Token e config Tailwind** · `react-ui-agent` · dip: nessuna
- `frontend/src/index.css`, `@layer base`, `:root` e `.dark`, HSL triplo. **Elenco definitivo** (C4):

  `--background --foreground --card --card-foreground --muted --muted-foreground --border --input
  --ring --primary --primary-foreground --destructive --destructive-foreground --warning
  --warning-foreground --success --success-foreground --chart-1 --chart-2 --chart-3 --chart-4 --chart-5`

  `--warning` / `--warning-foreground` stanno **dopo** `--destructive-foreground`. Servono al banner
  di troncamento `AiAssistant.tsx:61` (`border-amber-300 bg-amber-50 text-amber-800`) e a ogni banner
  di attenzione futuro.
- Due regole globali che fanno da sole metà della conversione:
  ```css
  * { @apply border-border; }   /* i `border`/`border-b`/`border-r` nudi ereditano gray-200 dal preflight */
  body { @apply bg-background text-foreground; }
  ```
- `frontend/tailwind.config.js`: `darkMode: 'class'` + `theme.extend.colors` con
  `hsl(var(--x) / <alpha-value>)` — l'`<alpha-value>` è ciò che rende legale `bg-success/10`.

**T9 — ThemeProvider e anti-FOUC** · `react-ui-agent` · dip: T3, T8
- `frontend/src/components/theme-provider.tsx`: stato `light|dark|system`, classe su
  `document.documentElement`, listener `matchMedia`, persistenza su **`PUT /settings`** e localStorage.
- Degradazione: se l'API fallisce il tema si applica lo stesso e localStorage resta la verità locale;
  l'errore è visibile ma non blocca. Il tema non dipende mai dalla disponibilità del backend.
- Script inline in `frontend/index.html` prima del bundle: legge localStorage, risolve `system` con
  `matchMedia`, applica la classe. Cambiare anche `<title>` (oggi `frontend`).

**T10 — chart-config e grafici** · `react-ui-agent` · dip: T8
- Nuovo `frontend/src/lib/chart-config.ts`: `chartColors`, `chartGrid`, `chartAxis`, `chartTooltip`
  (`contentStyle` per il tooltip, unico nodo HTML e non SVG).
- **Primo passo del task**: convertire **un solo** grafico e verificare a schermo che Recharts risolva
  `hsl(var(--chart-N))`, prima di convertire gli altri tre (rischio 5).
- Mappa dei 6 esadecimali di `Dashboard.tsx`: `#16a34a`->chart-2, `#dc2626`->chart-1,
  `#2563eb`->chart-3, `#7c3aed`->chart-4 con fill `hsl(var(--chart-4) / 0.2)`, `#0891b2`->chart-5.

**T11 — Conversione dei file strutturali (C2)** · `react-ui-agent` · dip: T8, T6a (per `App.tsx`)

> **Nota per il sub-agent**: `App.tsx` viene modificato anche da T6a (routing). Prima di applicare
> le conversioni di colore, recuperare lo stato del file **dal branch corrente dopo il commit di
> T6a**, non da `master`. Se T6a non è ancora committato, T11 è bloccato da questa dipendenza.

Ordine vincolante: `button.tsx` -> `alert-dialog.tsx` -> **`App.tsx` -> `Sidebar.tsx`**.

> **Nessuna pagina è leggibile in dark finché `App.tsx` e `Sidebar.tsx` non usano token semantici**:
> `App.tsx:14` porta `bg-gray-50` sul wrapper radice e `Sidebar.tsx` porta `bg-white`,
> `text-gray-700`, `bg-gray-900`, `text-white`, `bg-gray-100`, cioè la cornice di ogni pagina.
> Sono prerequisito bloccante di T12, non lavoro parallelo.

- `button.tsx:11-13`: `bg-gray-900 text-white hover:bg-gray-800` -> `bg-primary text-primary-foreground
  hover:bg-primary/90`; `bg-red-600 text-white hover:bg-red-700` -> `bg-destructive
  text-destructive-foreground hover:bg-destructive/90`; `border-gray-300 bg-white hover:bg-gray-50`
  -> `border-input bg-background hover:bg-muted`.
- `alert-dialog.tsx` (C5): riga 22 `bg-white` del pannello Content -> **`bg-background`** (opzione a).
  In dark un pannello bianco su fondo scuro è il difetto più evidente possibile.
- **Unica eccezione dichiarata in tutto F8**: `alert-dialog.tsx:19` `bg-black/50` **resta**. È il velo
  dell'overlay, non una superficie: corretto in entrambi i temi. Nessun'altra eccezione è ammessa.
- `App.tsx` viene toccato due volte nel piano (T6a routing, T11 colori): cambi ortogonali, dichiarato.

**T12 — Conversione delle 7 pagine** · `react-ui-agent` · dip: T10, T11
`Dashboard.tsx` (già fatta in T10 per i grafici, restano le classi), `Transactions.tsx`, `Import.tsx`,
`CategoriesPending.tsx`, `Accounts.tsx`, `Backup.tsx`, `AiAssistant.tsx`.
Mapping ricorrente: `bg-white`->`bg-card` · `text-gray-500`->`text-muted-foreground` ·
`text-red-600`->`text-destructive` · `text-green-600|700`->`text-success` · `bg-gray-100`->`bg-muted` ·
`bg-green-50`->`bg-success/10` · banner amber -> `border-warning bg-warning/10 text-warning-foreground`.

> **CHECKPOINT UMANO 3** — palette valutata a schermo (i valori HSL concreti si giudicano solo così),
> **7 pagine** × 2 temi, nessun flash al reload. `/impostazioni` è ancora il placeholder di T6a:
> entra nella verifica visiva solo al checkpoint finale, dove le pagine diventano 8.

### Fase 4 — Pagina e chiusura

**T13 — Pagina `/impostazioni`** · `react-ui-agent` · dip: T3, T9, T11
Sezioni: Aspetto · Dashboard esterne · Parametri ETL · Backup · AI · Secret.
Ogni campo mostra **quando ha effetto** e **da dove viene il valore** (DB/env/default). I secret sono
badge "configurato / non configurato" con la riga `.env` da usare, mai campi di input.

**T14 — Chiusura** · `main` · dip: tutti
- Versioning — convenzione esistente confermata sul codice (`main.py:31` `version="0.1.0-phase7"`,
  `main.py:45` `phase: "7"`): il suffisso è **l'ultima fase chiusa**, non il nome del blocco.
  Il Blocco A chiude F8 **e** F9, quindi entrambi i valori puntano a 9:
  `version="0.1.0-phase9"` nell'header FastAPI e `phase: "9"` in `/health`. La notazione
  `"0.1.0-bloccoA"` è **scartata**: romperebbe la serie phase7 -> phase9 senza guadagno.
- Aggiornamento di `CLAUDE.md` (fase corrente, ADR-0033), `docs/ARCHITECTURE.md` (righe F8/F9 con
  evidenze), `docs/DECISIONS.md` (ADR-0033 + rettifiche a 0026/0027).

---

## Verifica

**Automatica** — suite esistente (100 test) invariata, più i nuovi:
round-trip Alembic · precedenza DB > env > default (incluso il ramo `session=None`) · coercizione tipi ·
blacklist a 3 asserzioni · shape `GET /settings` · contratto `sheet_year` del parser · riaggancio dei
consumatori · invariante ADR-0033 · comportamento HTTP delle 4 route.

**Per esaurimento** — il grep colore entra nella spec come comando di accettazione, zero match residui
sui file frontend salvo `bg-black/50`:

```
(bg|text|border|ring|fill|stroke|from|to|via|divide|placeholder|outline|shadow|accent|caret)-(white|black|slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)(-\d{2,3})?|#[0-9a-fA-F]{3,8}
```

**Manuale, sul container di produzione** (non dev server):
- `docker compose build backend && docker compose up -d`, entrambi i servizi healthy
- 8 pagine × 2 temi, console pulita, nessun elemento illeggibile
- hard-refresh su `/settings`, `/impostazioni`, `/backup`, `/backup-restore` -> esiti della tabella T7
- reload ripetuti senza flash bianco; toggle tema persistente dopo cambio browser (prova che il DB,
  non localStorage, è la fonte di verità)
- import storico dopo aver cambiato `import_min_year` da `/settings`: il tab aperto è quello nuovo
- `docker compose config` valido, `/health` con `phase: "9"`
- `alembic heads` -> una sola riga, immediatamente prima del merge

## Rischi

| # | Rischio | Mitigazione |
|---|---|---|
| 1 | conversione a campione lascia elementi illeggibili | criterio per esaurimento col grep, non ispezione visiva |
| 2 | `border` nudo dimenticato in dark | regola globale `* { @apply border-border }` |
| 3 | consumatore backend che continua a leggere `config` -> impostazione inerte | T4 e T5 dedicati, con grep di accettazione |
| 4 | revision con `down_revision` sbagliato | Blocco A mergia per primo; `alembic heads` come ultimo gate |
| 5 | Recharts non risolve `hsl(var(--x))` in qualche nodo | T10 verifica **un** grafico prima di convertirne quattro |
| 6 | `run_backup()` e il dry-run girano senza sessione -> accessor che esplode nel thread di avvio | `get_effective(session=None)` apre e chiude la propria sessione; test su quel ramo |
| 7 | `SPA_ROUTES` diverge da `App.tsx` e l'invariante di T7 diventa una bugia | T6b dipende da T6a (la costante si deriva dall'`App.tsx` già a 8 route); asserzioni di contenuto nel test 1 di T7; commento incrociato in entrambi i file |
| 8 | il refactor della firma del parser tocca codice F2 senza copertura | il test del parser si scrive **in** T4, non dopo; il contratto `sheet_year` è la prima asserzione |

---

## Rettifiche post-review 2026-07-21 (giro finale)

Esiti dell'ultimo giro di review, ognuno verificato sul codice prima dell'applicazione:

- **C-CRIT-1 applicata** — T6b ora dichiara esplicitamente che il ramo `else` di `main.py`
  (righe 66-70, fallback JSON su `/` per dev locale) resta inline: `mount_spa()` contiene solo i
  tre elementi del ramo `if`.
- **C-CRIT-2 applicata in forma corretta** — la docstring di modulo di `master_sheet_parser.py`
  contiene `settings.import_min_year` **una volta sola** (frase "(year sempre
  `settings.import_min_year` per questo tab)", paragrafo "Tracciamento mese corrente"; grep: 5
  match totali nel file, non 6). I punti (a) e (b) della review erano la stessa occorrenza.
  L'elenco di T4 ora ancora l'occorrenza alla citazione esatta, eliminando il riferimento ambiguo
  al "terzo paragrafo".
- **C-WARN-1 chiusa rimuovendo il numero** — due conteggi indipendenti hanno dato 25 e 26 per la
  stessa riga (`if settings.backup_on_startup:` nel lifespan). Invece di arbitrare, T5 ora ancora
  il punto alla **citazione testuale**, che è inequivocabile comunque si conti; nessun numero di
  riga residuo per quel punto.
- **Piano approvato 2026-07-21.** Primo atto esecutivo: T0 + scaffolding documentale
  (deliverable 1-4: spec, piano nel repo, ADR-0033, rettifiche 0026/0027, aggiornamento
  CLAUDE.md e prompt di ripresa in ARCHITECTURE.md), commit
  `docs: rettifica piano f8-f9 post-verifica codice (C-WARN-1, SHA T11)`.

## Rettifiche post-review 2026-07-21 (validazione codebase)

- **CRIT-1 applicata** — T6b: aggiunta precisazione sulla struttura `if/else` di `main.py` per
  prevenire orphan del ramo `else` durante l'estrazione di `mount_spa()`.
- **WARN-1 applicata** — T4: esplicitata la rimozione di `| None` e `= None` dal parametro
  `sheet_name` nella firma refactorizzata.

**Piano approvato per l'esecuzione 2026-07-21.**

## Rettifiche post-verifica import 2026-07-21

- **OMISSIONE 1 applicata con correzione** — T3: istruzione esplicita per l'import del router in
  `main.py`. La forma proposta in review (`settings` nudo nella riga
  `from app.routers import ...`) avrebbe **shadowato** `from app.config import settings` (riga 11),
  rompendo `if settings.backup_on_startup:` (lifespan) e `settings.db_path` (`/health`) con
  `AttributeError` al primo boot — l'import dei router viene dopo quello di config. Forma adottata:
  `settings as settings_router` + `app.include_router(settings_router.router)`, in ordine
  alfabetico tra `insights` e `transactions`.
- **OMISSIONE 2 applicata** — T4: `from app.services.settings import get_effective` aggiunto come
  primo punto dell'intervento in `imports.py` (import di sola funzione, nessuno shadowing);
  accettazione estesa con `grep -n "from app.services.settings import"
  backend/app/routers/imports.py` -> esattamente 1 match.

**Piano approvato per l'esecuzione 2026-07-21 (conferma finale).**
