# Personal Portfolio — Debito Tecnico

Registro dei debiti tecnici noti, non bloccanti per il funzionamento corrente. Ogni voce riporta
origine, severità, impatto e stato. Risolti nella fase **F-DEBT** (vedi `docs/ARCHITECTURE.md`).

## Registro

### DEBT-01 — Pagination senza tiebreaker (ordinamento non deterministico)
- **Origine**: F5 Task 1 (review finale), `backend/app/routers/transactions.py`.
- **Label**: [NON-BLOCCANTE] · Severity: bassa.
- **Descrizione**: `list_transactions` ordina solo per `Transaction.date.desc()`. Con più righe che
  condividono la stessa data, l'ordine relativo tra loro non è garantito stabile tra due chiamate
  (dipende dall'ordine fisico su disco/query plan) — righe possono duplicarsi o saltare tra pagine
  consecutive in casi limite.
- **Impatto**: cosmetico/UX (paginazione instabile su date ripetute), nessun rischio di perdita dati.
- **Stato**: aperto.

### DEBT-02 — Favicon non servita in produzione
- **Origine**: F5 review finale whole-branch, `frontend/index.html` + `backend/app/main.py` (fallback SPA).
- **Label**: [NON-BLOCCANTE] · Severity: bassa.
- **Descrizione**: `index.html` referenzia `/favicon.svg`; nel container di produzione questo path
  non è sotto il mount `/assets`, quindi il catch-all SPA ritorna `index.html` (200, `text/html`)
  invece dell'icona — l'icona fallisce silenziosamente. `frontend/public/icons.svg` committato ma
  non referenziato da nessuna parte (asset morto).
- **Impatto**: cosmetico (tab browser senza icona).
- **Stato**: aperto.

### DEBT-03 — React 18→19 non documentato nel piano di sviluppo
- **Origine**: F5 Task 5 (scaffold), review finale whole-branch.
- **Label**: [NON-BLOCCANTE] · Severity: bassa.
- **Descrizione**: il piano `docs/superpowers/plans/2026-07-15-f5-react-ui.md` e la narrativa di
  design fanno riferimento a "React 18", ma `frontend/package.json` pinna `react@^19.2.7` (scaffold
  Vite generato con i default correnti al momento dell'esecuzione: Vite 8, TS ~6.0.2, `oxlint`).
  A differenza del pin Tailwind v3 e dell'omissione di `baseUrl` (entrambi esplicitamente segnalati
  e confermati in review), il salto di versione React 18→19 non è stato disclosurato come deviazione
  nel piano.
- **Impatto**: nessun impatto funzionale osservato (build verificata, E2E live verificato); solo
  disallineamento documentale piano/codice.
- **Stato**: aperto.

### DEBT-04 — Bug dev-only: proxy Vite su `/import` non riproducibile in produzione
- **Origine**: F5 Task 8 (verifica live browser), confermato non-riproducibile in Task 10.
- **Label**: [NON-BLOCCANTE] · Severity: bassa.
- **Descrizione**: il proxy Vite dev (`frontend/vite.config.ts`, `server.proxy`) fa match per
  **prefisso** sul path `/import`, quindi una navigazione diretta o un reload su
  `http://localhost:5173/import` (non un click sidebar, che è client-side) viene intercettata dal
  proxy e inoltrata al backend, che ritorna `{"detail":"Not Found"}` invece di servire la SPA.
  **Non riproducibile in produzione**: FastAPI fa match per path esatto, non per prefisso — il
  fallback SPA (`main.py`, catch-all registrato dopo tutti i router) funziona correttamente, come
  confermato dal test hard-refresh su `/transazioni` in Task 10 (stesso meccanismo, path diverso).
- **Impatto**: solo ambiente di sviluppo locale (`npm run dev`); nessun impatto in produzione.
- **Stato**: aperto (accettabile come limite noto dell'ambiente dev, non richiede fix per lo shipping).

### DEBT-05 — Worktree stale `.git/worktrees/f4-backup`
- **Origine**: sessione F4 (backup), riscontrato per la prima volta durante F5.
- **Label**: [NON-BLOCCANTE] · Severity: bassa.
- **Descrizione**: `.git/worktrees/f4-backup` è una directory di worktree amministrativa stale
  (il worktree stesso non è più attivo, non compare in `git worktree list`) che genera un warning
  innocuo `error: failed to delete '.git/worktrees/f4-backup': Permission denied` ad ogni commit
  (probabile lock del filesystem OneDrive, stesso pattern osservato su `frontend/node_modules/.vite`).
- **Impatto**: nessuno — il warning non impedisce il commit, è puramente rumore in output.
- **Stato**: **chiuso (2026-07-16)**. `git worktree prune` da solo non bastava (stesso lock OneDrive
  di `frontend/node_modules/.vite`, la directory sopravviveva al prune). Risolto con `rm -rf
  .git/worktrees/f4-backup` manuale + `git worktree prune`; `git worktree list` ora pulito, nessun
  worktree residuo. Verificato: nessun warning `Permission denied` al prossimo commit.

## Legenda severità
- **bassa**: nessun impatto funzionale/dati, cosmetico o solo-dev.
- **media**: impatto UX reale ma non distruttivo.
- **alta**: rischio dati/sicurezza — non applicabile a nessuna voce corrente.
