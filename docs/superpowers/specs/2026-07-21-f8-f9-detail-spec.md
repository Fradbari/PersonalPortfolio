# Blocco A — F8 dark mode + F9 settings: spec di dettaglio

- **Status**: Approvata — 2026-07-21 (dopo 7 giri di review sul piano associato)
- **Branch**: `f8-f9-theme-settings`
- **Deriva da**: roadmap `2026-07-21-f8-f14-roadmap-design.md` (ADR-0026/0027)
- **Produce**: ADR-0033 (nuovo) + rettifiche dichiarate ad ADR-0026/0027
- **Piano associato**: `docs/superpowers/plans/f8-f9-implementation-plan.md` (task T0-T14,
  dipendenze, checkpoint umani)

---

## 1. Obiettivo

Tre risultati, verificabili singolarmente:

1. **F8 — dark mode completa**: token semantici CSS (`:root`/`.dark`, HSL triplo) su Tailwind v3
   `darkMode:'class'`, ThemeProvider `light|dark|system` con script inline anti-FOUC, conversione
   **per esaurimento** delle 31 classi colore hardcoded su 11 file e dei 6 esadecimali di
   `Dashboard.tsx` via `chart-config.ts` condiviso.
2. **F9 — configurazione centralizzata**: tabella `settings` key/value (prima revision Alembic dopo
   `0002`), `GET/PUT /settings` con whitelist/blacklist, precedenza **DB > env > default**, ottava
   pagina React su `/impostazioni`, consumatori backend riagganciati (il valore scritto in UI ha
   effetto reale).
3. **Routing sanato (ADR-0033)**: chiusura del difetto di produzione scoperto in pianificazione —
   `GET /backup` con `Accept: text/html` risponde JSON perché endpoint API e route SPA condividono
   il path esatto. Regola nuova: **nessuna route SPA condivide un path esatto con un endpoint API**,
   verificata da test di regressione. Pagina Backup → `/backup-restore`, pagina settings →
   `/impostazioni` (endpoint resta `/settings`).

Evidenza del difetto (container di produzione attivo, 2026-07-21):

```
GET /backup      (Accept: text/html) -> 200 application/json   <- SPA rotta
GET /transazioni (Accept: text/html) -> 200 text/html          <- ok
```

## 2. File toccati

| Area | File | Natura |
|---|---|---|
| Schema | `backend/app/models.py` | modello `Settings` nuovo |
| Schema | `backend/alembic/versions/0003_settings.py` | revision nuova (numero/`down_revision` da riconfermare al merge) |
| Backend | `backend/app/services/settings.py` | **nuovo** — registro WHITELIST/BLACKLIST, `get_effective`, `set_values` |
| Backend | `backend/app/routers/settings.py` | **nuovo** — `GET/PUT /settings` |
| Backend | `backend/app/main.py` | import router (con alias `settings_router`), lifespan su `get_effective`, estrazione `mount_spa()`, costante `SPA_ROUTES`, version/phase → 9 |
| Backend | `backend/app/ingestion/master_sheet_parser.py` | firma `(file, sheet_name: str, sheet_year: int)`, rimozione totale di `settings` |
| Backend | `backend/app/routers/imports.py` | i 2 call site passano `sheet_name`/`sheet_year` via `get_effective` |
| Backend | `backend/app/routers/backup.py` | `backup_retention` via `get_effective(session=None)` |
| Test | `backend/tests/test_settings*.py`, `test_master_sheet_parser.py`, `test_routing_spa.py` | **nuovi** |
| Frontend | `frontend/src/index.css` | token semantici `@layer base` |
| Frontend | `frontend/tailwind.config.js` | `darkMode:'class'` + `theme.extend.colors` |
| Frontend | `frontend/index.html` | script inline anti-FOUC + `<title>` |
| Frontend | `frontend/src/components/theme-provider.tsx` | **nuovo** |
| Frontend | `frontend/src/lib/chart-config.ts` | **nuovo** — stringhe `hsl(var(--chart-N))` |
| Frontend | `frontend/src/App.tsx` | route `/backup-restore` + `/impostazioni`; conversione colori |
| Frontend | `frontend/src/components/Sidebar.tsx` | voce Backup → `/backup-restore`, ottava voce Impostazioni; conversione colori |
| Frontend | `frontend/src/pages/Settings.tsx` | **nuovo** — pagina `/impostazioni` |
| Frontend | `frontend/vite.config.ts` | bypass ADR-0022 rimosso, proxy `/settings` aggiunto |
| Frontend | `button.tsx` · `alert-dialog.tsx` · 7 pagine | conversione classi per esaurimento |
| Docs | `docs/DECISIONS.md` | ADR-0033 + rettifiche 0026/0027 |
| Docs | `CLAUDE.md` · `docs/ARCHITECTURE.md` | stato fase, prompt di ripresa |

**Non toccati**: Blocco B/C, F7, ADR-0024/0025, `docker-compose.yml`, Metabase, logica
ingestion/dedup/AI (unica eccezione dichiarata: la firma di `parse_master_sheet_xlsx`).

## 3. Interfacce pubbliche modificate

### Nuove

- **`GET /settings`** →
  `{settings: [{key, value, source, applies_when}], secrets_status: {<nome>: {configured: bool}}}`.
  `source ∈ {db, env, default}`; `applies_when` stringa libera in italiano (testi ADR-0027 p.4).
  Nessun valore di secret, mai (ADR-0027 p.6).
- **`PUT /settings`** → body dict di chiavi whitelist; transazione unica; chiave illegale
  (non-whitelist **o** blacklist) → **400 con messaggio identico** nei due casi
  (anti-enumerazione della blacklist).
- **`services/settings.get_effective(key, session=None) -> (value, source)`** — precedenza
  DB > env > default; con `session=None` apre e chiude una `SessionLocal()` propria (chiamabile dal
  thread di avvio e dal dry-run, che non hanno sessione).
- **`main.mount_spa(app, dist_dir)`** — estrazione del blocco SPA (mount `/assets`, `favicon.svg`,
  catch-all); comportamento di produzione identico, invocabile su app di prova nei test.
- **`main.SPA_ROUTES: frozenset[str]`** — le 8 route SPA, a livello di modulo (esiste anche senza
  `frontend_dist`); commento incrociato con `App.tsx`.

### Modificate (breaking, contenute)

- **`parse_master_sheet_xlsx(file, sheet_name: str, sheet_year: int)`** — prima:
  `(file, sheet_name: str | None = None)`. `sheet_name` = nome tab; `sheet_year` = anno per le
  righe datate da marcatore mese italiano (ramo `ITALIAN_MONTHS`, blocchi luglio-dicembre).
  Call site nel repo: **esattamente 2** (`imports.py`), nessun test esistente coinvolto (verificato).
- **Route SPA**: `/backup` → `/backup-restore` (label sidebar resta "Backup"); nessun redirect
  (single-user rete locale, ADR-0009).

### Invariate

`GET /insights` e i 5 test F5 · `PUT /transactions/{id}` (solo comment/tag/category_id) ·
tool registry AI read-only · hash dedup (ADR-0005/0013) · Metabase e replica (ADR-0004/0017).

## 4. Token e tema (contratto F8)

Token in `:root` e `.dark` (elenco definitivo, C4):

```
--background --foreground --card --card-foreground --muted --muted-foreground
--border --input --ring --primary --primary-foreground --destructive
--destructive-foreground --warning --warning-foreground --success
--success-foreground --chart-1 --chart-2 --chart-3 --chart-4 --chart-5
```

- Regole globali: `* { @apply border-border; }` e `body { @apply bg-background text-foreground; }`.
- `tailwind.config.js`: `hsl(var(--x) / <alpha-value>)` (rende legale `bg-success/10`).
- `chart-config.ts` esporta **stringhe** `hsl(var(--chart-N))` — il browser le risolve al toggle,
  zero JS (rettifica di ADR-0026 p.6: `getComputedStyle` si valuta al mount e resta stantio).
  Tooltip via `contentStyle` (unico nodo HTML). `ChartContainer`/`ChartTooltip` shadcn **non** si
  portano (rettifica M8.4).
- Mappa esadecimali `Dashboard.tsx` (6, non 5): `#16a34a`→chart-2 · `#dc2626`→chart-1 ·
  `#2563eb`→chart-3 · `#7c3aed`→chart-4 (+ fill `hsl(var(--chart-4) / 0.2)` per `#ddd6fe`) ·
  `#0891b2`→chart-5.
- Tema: DB = fonte di verità (`PUT /settings`), localStorage = cache anti-FOUC (ADR-0027 p.9).
  API giù → tema si applica comunque, errore visibile, mai bloccante.
- **Unica eccezione di conversione in tutto F8**: `alert-dialog.tsx` overlay `bg-black/50`
  (velo, corretto in entrambi i temi). Il pannello Content `bg-white` → `bg-background`.

## 5. Whitelist iniziale (contratto F9)

| Chiave | Tipo | Default (env) | Quando ha effetto |
|---|---|---|---|
| `theme` | str | `system` (nessuna env) | immediato |
| `metabase_url` | str | `http://localhost:3000` (nessuna env) | immediato (solo destinazione link) |
| `ai_history_max_turns` | int | 6 (nessuna env) | immediato, dalla domanda successiva — **nessun consumatore fino a F14, dichiarato** |
| `import_min_year` | int | `settings.import_min_year` | immediato, dal prossimo import |
| `backup_retention` | int | `settings.backup_retention` | immediato, dal prossimo backup |
| `backup_on_startup` | bool | `settings.backup_on_startup` | **solo al boot successivo** |

Blacklist permanente: `ai_api_key` · `google_sa_key_path` · `gdrive_backup_folder_id`.

## 6. Criteri di accettazione

**Automatici** (suite: 100 esistenti invariati + nuovi):

1. Alembic: `upgrade head` + `downgrade` fino a `0002` su DB di prova; `alembic heads` = 1 riga.
2. Precedenza DB > env > default per ogni chiave whitelist; coercizione tipi; rollback completo su
   chiave illegale; ramo `session=None` (sessione chiusa anche su eccezione).
3. **Blacklist a 3 asserzioni** (riformula ADR-0027 p.8, che si contraddiceva con p.6):
   (a) sentinelle iniettate in config non compaiono nel JSON di `GET /settings`;
   (b) nessuna chiave blacklistata nell'array `settings[]`;
   (c) `PUT` su blacklistata e su inesistente → 400 con messaggio identico.
4. Parser: `grep -n "settings" backend/app/ingestion/master_sheet_parser.py` → **0 match**;
   `grep -rn "parse_master_sheet_xlsx(" backend/` → solo definizione + 2 call site espliciti;
   test nuovo: `sheet_year=2025` + marcatore italiano → `current_year=2025` indipendente dal tab.
5. Consumatori: `grep -rn "settings\.\(import_min_year\|backup_retention\|backup_on_startup\)"
   backend/app` → zero match fuori da `services/settings.py`.
6. **Routing (ADR-0033)**: (a) invariante — `SPA_ROUTES` ∩ path esatti API = ∅, più contenuto
   esatto (8 voci attese, `"/backup" not in`); (b) HTTP — app di prova + `mount_spa(tmp_dist)`:
   `GET /settings`→JSON, `GET /impostazioni`→html, `GET /backup`→JSON, `GET /backup-restore`→html.

**Per esaurimento** (F8): zero match residui del grep colore sui file frontend, sola eccezione
`bg-black/50`:

```
(bg|text|border|ring|fill|stroke|from|to|via|divide|placeholder|outline|shadow|accent|caret)-(white|black|slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)(-\d{2,3})?|#[0-9a-fA-F]{3,8}
```

**Manuali** (container di produzione, non dev server): 8 pagine × 2 temi con console pulita ·
hard-refresh sulle 4 URL della tabella routing · reload senza flash bianco · tema persistente al
cambio browser (prova DB) · import storico dopo cambio `import_min_year` da UI apre il tab nuovo ·
`/health` `phase: "9"` · `alembic heads` = 1 riga prima del merge.

## 7. Rischi

| # | Rischio | Mitigazione |
|---|---|---|
| 1 | conversione a campione lascia elementi illeggibili | criterio per esaurimento col grep |
| 2 | `border` nudo dimenticato in dark | regola globale `* { @apply border-border }` |
| 3 | consumatore che continua a leggere `config` → impostazione inerte | task dedicati (T4/T5) con grep di accettazione |
| 4 | revision con `down_revision` sbagliato | Blocco A mergia per primo; `alembic heads` ultimo gate |
| 5 | Recharts non risolve `hsl(var(--x))` | verifica su **un** grafico prima degli altri (T10) |
| 6 | accessor senza sessione esplode nel thread di avvio | `get_effective(session=None)` autonoma + test |
| 7 | `SPA_ROUTES` diverge da `App.tsx` | dipendenza T6a→T6b + asserzioni di contenuto nel test |
| 8 | refactor firma parser su codice F2 scoperto | test del parser scritto nel task stesso |
| 9 | shadowing di `config.settings` in `main.py` | import con alias `settings_router` (scoperto in review, evitato by design) |

## 8. Decisioni aperte

- **Valori HSL concreti della palette**: proposta base neutra (slate shadcn) + 5 tinte chart
  distinguibili; giudizio **a schermo al checkpoint umano 3**, non su carta.
- Evoluzione `applies_when_type: Literal["immediate","restart"]` se servirà distinguere
  visivamente: richiede rettifica ADR-0027, non ora.

Decisioni **chiuse** in questa spec (non riaprire): pagina `/impostazioni` vs endpoint `/settings`
(D1) · rinomina `/backup-restore` senza redirect (D2) · stringhe CSS var nei chart, no
`getComputedStyle` (D3) · backend-first (D4) · niente `ChartContainer` shadcn · `version` segue la
serie `phaseN`.
