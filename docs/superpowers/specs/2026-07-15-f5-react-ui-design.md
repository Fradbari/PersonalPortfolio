# F5 — UI React: design spec

Data: 2026-07-15 · Fase: F5 · Riferimenti: ADR-0019, react-ui-agent.md, ARCHITECTURE.md §3 Fase 5

## Contesto

F4 (backup automatico) completata e verificata E2E. Prossima fase: UI React custom
prevista fin dal piano architetturale (§Frontend/dashboard: "Ibrido — Metabase subito,
UI React in fase successiva"). Verificato lo stato reale del backend prima di
progettare: router esistenti (`imports.py`, `categories.py`, `backup.py`) non
coprono lettura aggregata né CRUD transazioni/conti — servono nuovi endpoint, non
solo nuovo frontend.

## Decisioni (confermate dall'utente)

1. **Scope**: React copre lettura **e** scrittura in modo completo (dashboard
   equivalente a Metabase + gestione transazioni/pending/conti/backup). Non è un
   affiancamento parziale limitato alle sole azioni write.
2. **Metabase**: resta attiva, invariata, come UI separata — non sostituita né
   ridotta. Due frontend indipendenti sullo stesso backend FastAPI.
3. **Deploy**: valutato dall'assistente su richiesta esplicita dell'utente ("nessun
   requisito di produzione, valuta tu per compatibilità Raspberry e semplicità") →
   container singolo, build statico servito da FastAPI. Nessun servizio nuovo in
   `docker-compose.yml`.
4. **Stack frontend**: scelto tra 3 opzioni proposte (minimale / consigliata /
   pesante) → **consigliata**: React + Vite + TypeScript + TanStack Query +
   React Router + Tailwind CSS/shadcn/ui + Recharts.

## Architettura

```
┌───────────────────────────┐
│   Container FastAPI        │
│  ┌───────────────────────┐ │
│  │ backend/app/           │ │
│  │  routers/               │ │
│  │   imports · categories  │ │  (riusati as-is)
│  │   backup                │ │  (riusato as-is)
│  │   transactions (NUOVO)  │ │
│  │   accounts (NUOVO)      │ │
│  │   insights (NUOVO)      │ │
│  └──────────┬──────────────┘ │
│             │ query DB live   │
│             │ (WAL, stesso    │
│             │  processo)      │
│  ┌──────────▼──────────────┐ │
│  │ StaticFiles → frontend/  │ │
│  │  dist/ (build Vite)      │ │
│  └───────────────────────────┘
└───────────────────────────┘
        ▲                    ▲
        │ fetch (stessa origin, no CORS)
┌───────┴────────┐   ┌───────┴────────────┐
│ React (browser) │   │ Metabase (container│
│ dashboard+CRUD   │   │  separato, replica │
└─────────────────┘   │  read-only)         │
                       └─────────────────────┘
```

Nessuna modifica di schema DB — nessuna Alembic revision per F5.

### Nuovi endpoint backend

- **`GET /transactions`** — lista paginata/filtrabile (mese, categoria, conto,
  tipo). **`PUT /transactions/{id}`** — edit `comment`/`tag`/`category_id` (mai
  campi dell'hash: `date`/`amount`/`category_raw`/`account`/`type` restano
  immutabili post-import, ADR-0005/ADR-0013). **`DELETE /transactions/{id}`** —
  correzioni manuali.
- **`GET /accounts`** — lista conti. **`PATCH /accounts/{id}`** — rename
  `display_name` (N-F6, oggi non esposto da alcun router).
- **`GET /insights`** — aggregazioni: trend mensile entrate/uscite, breakdown per
  categoria (`category_raw`), saldo cumulato mensile, saldo per conto. Stessa
  logica delle 4 card SQL native di Metabase (F3), riscritta via SQLAlchemy.
  Legge il DB **live** (non la replica): il meccanismo di replica read-only
  (ADR-0004/ADR-0017) esiste solo per isolare Metabase, che gira in un container
  separato e non può condividere il file SQLite in WAL. FastAPI è già l'unico
  writer nello stesso processo — WAL garantisce reader concorrenti sicuri senza
  bisogno di replica per i propri endpoint.

### Frontend

- **Build tool**: Vite. **Linguaggio**: TypeScript — tipi derivabili dallo schema
  OpenAPI generato da FastAPI, contratto API/UI verificato a compile time.
- **Data fetching**: TanStack Query — cache, invalidation automatica post-mutation,
  stato loading/error dichiarativo. Scelto per eliminare boilerplate manuale dato
  il requisito di scrittura piena (molte mutation: edit, delete, resolve, rename,
  backup, restore).
- **Routing**: React Router, sidebar nav fissa.
- **Styling**: Tailwind CSS + shadcn/ui — look moderno (N-NF5) senza design-system
  pesante da mantenere in solo-dev (N-NF4).
- **Charting**: Recharts — dichiarativo, React-native, sufficiente per trend/
  breakdown/saldo (nessun bisogno di d3 grezzo).

### Pagine

| Pagina | Endpoint usati | Note |
|---|---|---|
| Dashboard | `GET /insights` | Card trend, breakdown categoria, saldo cumulato, saldo per conto |
| Transazioni | `GET/PUT/DELETE /transactions` | Tabella filtrata, edit inline, delete con conferma |
| Import | `imports.py` (esistente) | Upload My Finance + storico dry-run/commit, riuso as-is |
| Categorie pending | `categories.py` (esistente) | Lista + assegna mapping, riuso as-is |
| Conti | `GET/PATCH /accounts` | Lista + rename |
| Backup | `backup.py` (esistente) | Trigger, lista, restore con conferma 2 step |

### Operazioni distruttive

Delete transazione e restore backup: dialog di conferma esplicita (shadcn
`AlertDialog`) prima della chiamata. Per il restore rispecchia lato UI lo stesso
`confirm: true` obbligatorio già imposto lato backend (ADR-0018 punto 5).

## Test

- **Backend**: nuova suite pytest per `transactions`/`accounts`/`insights`
  (stesso pattern F4 — `backend/tests/`, seed dati → verifica risposta/side-effect).
- **Frontend**: nessuna suite automatica in questa fase (nessun requisito di
  produzione dichiarato dall'utente, N-NF4). Verifica E2E manuale in browser a
  fine implementazione — coerente col pattern F1-F4 (backend testato, dashboard
  verificata a mano).

## Documentazione aggiornata in questa sessione

- `docs/DECISIONS.md` — ADR-0019 (scope, deploy, endpoint, stack, testing).
- `CLAUDE.md` — sottoagente `react-ui-agent` aggiunto, riga "Fase corrente" → F5.
- `docs/ARCHITECTURE.md` — stato avanzamento F5 (◐ in corso), prompt di ripresa,
  elenco sottoagenti trasversali.
- `.claude/agents/react-ui-agent.md` — nuovo agente.

## Documentazione da aggiornare a fine implementazione

- `docs/ARCHITECTURE.md` — stato avanzamento F5 → ☑ fatto con evidenze E2E, riga
  "Fase corrente" → F6, prompt di ripresa.
- `CLAUDE.md` — riga "Fase corrente" → F6.

## Fuori scope (YAGNI)

- Autenticazione/reverse proxy: esposizione resta solo LAN (ADR-0009 invariato).
- Tabella `settings` DB per toggle runtime (`BACKUP_ON_STARTUP`, ecc.): resta
  env var finché non emerge un bisogno concreto in UI.
- Multi-valuta piena in UI: colonne già presenti in DB ma fuori scope F5.
- Suite di test frontend automatica: rivedibile con nuovo ADR se emergono
  requisiti di produzione.
