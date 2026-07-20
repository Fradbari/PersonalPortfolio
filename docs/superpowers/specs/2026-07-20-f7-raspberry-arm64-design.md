# F7 — Portabilità Raspberry Pi arm64 — design spec

Data: 2026-07-20 · Fase: F7 · Riferimenti: ARCHITECTURE.md §3 Fase 7 (N-NF2), ADR-0004/0016
(Metabase pinnata v0.62.4, multi-arch verificato, alternativa skip già prevista), ADR-0023 p.2
(dipendenze AI = client HTTP, impatto arm64 atteso trascurabile, da confermare qui).

## Contesto e vincoli di realtà

F0-F6 + F-DEBT complete e mergiate su master. Milestone F7 (ARCHITECTURE.md): **stesso
`docker compose up` gira su Raspberry Pi**.

Fatti raccolti dall'utente (2026-07-20):

- **Hardware target: Raspberry Pi 4, 4GB RAM.** CPU lenta (Cortex-A72), RAM stretta per una
  JVM + Python + OS.
- **Il Pi non è ancora pronto/disponibile.** La verifica su hardware reale è quindi
  **strutturalmente impossibile in questa sessione**: F7 si divide in una parte preparatoria
  (questa sessione, verificabile da desktop) e una parte di verifica su hardware (sessione
  futura, checklist già pronta). La fase resta **◐ in corso** finché la checklist hardware non
  è eseguita sul Pi reale.
- **Distribuzione immagini: build nativa sul Pi** (git clone + comando standard
  `docker compose up -d --build`, lo stesso di ogni aggiornamento). Nessun registry,
  nessun login, coerente con one-click (N-NF1) e no lock-in (N-NF3). Il costo è una build
  lenta una tantum sul Pi (accettato). La cross-build QEMU da desktop resta come
  **pre-verifica**, non come canale di distribuzione.
- **Metabase: misura-poi-decidi** (conferma dell'alternativa già aperta da ADR-0004/0016).
  Deploy completo sul Pi, misura di RAM/CPU/tempo di avvio, decisione keep/skip con dati.
- **Topologia compose: un solo `docker-compose.yml`, tuning universale.** I parametri
  calibrati per il Pi (limiti memoria, `start_period` lunghi, log rotation) sono innocui su
  desktop. Milestone rispettata alla lettera: stesso comando, stesso file, su entrambe le
  architetture. Scartati: override file (comando diverso sul Pi) e profiles (due percorsi da
  mantenere).

## Ricerca best practice (2026-07-20)

- **Metabase su Pi 4 4GB**: fattibile ma da governare. Doc ufficiale Metabase: lasciare 1-2GB
  al resto del sistema → `-Xmx1g` è il valore giusto su 4GB condivisi con backend+OS
  (via `JAVA_OPTS=-Xmx1g`). Il tag `v0.62.4` è multi-arch con `linux/arm64` (verificato via
  manifest Docker Hub in ADR-0016 il 2026-07-14; da ri-confermare in implementazione con
  `docker manifest inspect`). Fonti: metabase.com/docs (troubleshooting JVM), discourse
  Metabase (risorse minime).
- **Cross-build**: gerarchia 2026 = cross-compilation > runner nativi arm64 > QEMU (5-20x più
  lento). Per Python non serve cross-compilation (niente binari da compilare se esistono
  wheel `manylinux aarch64` — pandas/numpy/openpyxl/google-* le hanno); QEMU è adeguato come
  **verifica one-off** che l'immagine builda e parte su arm64. La build di produzione è
  nativa sul Pi (scelta utente). Fonti: docs.docker.com/build/building/multi-platform,
  docker.com blog cross-compilation.
- **SD card e log**: log Docker illimitati riempiono la SD e la usurano → cap espliciti
  `json-file` con `max-size`/`max-file` **dentro il compose** (per-servizio, così vale
  ovunque senza toccare `daemon.json` sul Pi — zero setup extra, one-click). Fonti:
  docs.docker.com/engine/logging, forum Raspberry Pi.
- **Healthcheck su hardware lento**: senza `start_period` adeguato, una JVM che su Pi 4
  impiega minuti ad avviarsi viene marcata `unhealthy` prima di finire il boot. Best
  practice: `start_period` misurato sull'ambiente più lento previsto (qui: minuti per
  Metabase, decine di secondi per il backend), `interval` 10-30s. Fonte: docs Docker
  HEALTHCHECK, guide 2026.

## Decisioni (da registrare in ADR prima del codice)

1. **ADR-0024 — Strategia arm64**: build **nativa sul Pi** come canale ufficiale
   (clone + `docker compose up -d --build` alla prima esecuzione); **pre-verifica QEMU** da
   desktop (`docker buildx build --platform linux/arm64`) come gate di fase — prova che il
   Dockerfile multi-stage (node:20-slim → python:3.12-slim) risolve su arm64 e che **tutte**
   le dipendenze Python installano da wheel aarch64 (se una compila da sorgente, sul Pi la
   build diventerebbe ore: va scoperto ora, da desktop). Un solo `docker-compose.yml` con
   tuning universale. Nessun registry.
2. **ADR-0025 — Metabase su Pi 4 4GB**: criterio **misura-poi-decidi** con soglie concrete e
   **protocollo di misura ripetibile** fissati prima della misura (niente decisione a
   sensazione):
   - `JAVA_OPTS=-Xmx1g` + limite memoria container 2GB (compose, universale);
   - **Protocollo di misura** (definizioni operative, nel runbook):
     - *Tempo di avvio*: dal `docker compose up -d --build` completato (comando ritornato)
       al container `metabase` marcato `healthy` dal healthcheck. Soglia: ≤ 10 minuti.
     - *RAM steady-state*: media di 3 letture `docker stats --no-stream` a 1 minuto di
       distanza, iniziate 5 minuti dopo il primo login completato, senza import in corso.
       Soglia: ≤ 1.5GB.
     - *Query dashboard*: load della dashboard F3 "Personal Portfolio - Overview" (4 card).
       Prima apertura post-avvio = cold (registrata, informativa); seconda apertura = warm.
       Soglia sul warm: < 10s.
     - *Stabilità*: nessun OOM-kill in 24h di uptime (check: `docker events --since 24h`
       filtrato su `oom`, più `dmesg | grep -i oom`).
   - **Modello di esito (Modello A — coerenza con "stesso compose, stesso comando")**: la
     milestone F7 si valida SEMPRE col full stack e col comando standard — lo skip non è una
     topologia alternativa né un file/comando diverso. Se una qualunque soglia sfora,
     l'esito è una **raccomandazione operativa post-validazione** documentata nel runbook:
     `docker compose stop metabase` dopo l'`up` (riattivabile con `docker compose start
     metabase`), UI React come dashboard quotidiana — architettura già prevista da
     ADR-0004/0016, nessun nuovo ADR per l'esito; l'esito va registrato nello Stato
     avanzamento.

## Interventi (questa sessione)

### 1. Pre-verifica cross-build QEMU (gate di fase, fail-fast)

Tre check deterministici, in ordine di costo — non ispezione di log a occhio:

1. **Wheel check fail-fast** (secondi, senza QEMU):
   `pip download --only-binary=:all: --platform manylinux2014_aarch64 --python-version 3.12
   -r backend/requirements.txt -d <tmp>` — fallisce con errore esplicito alla prima
   dipendenza (diretta o transitiva) priva di wheel aarch64. **Scelta conservativa
   intenzionale**: il criterio è più forte del requisito reale (un sdist puro-Python
   installerebbe comunque in tempi accettabili) — se il check fallisce su un pacchetto
   puro-Python, si valuta il caso e lo si documenta come eccezione, non si allenta il
   gate. Il rischio vero da intercettare è la compilazione nativa pesante (C/Rust), che
   sul Pi diventerebbe ore di build.
2. **Build arm64 eseguibile**: `docker buildx build --platform linux/arm64 --load` produce
   un'immagine arm64 caricata nel daemon locale (non un log da interpretare: o l'immagine
   esiste ed è taggata, o il gate fallisce).
3. **Smoke test emulato**: run dell'immagine del punto 2 via QEMU con DB effimero →
   `/health` risponde 200 e i moduli applicativi importano dentro il container emulato
   (`python -c "import app.main"`). Lento sotto QEMU: si valida l'avvio, non le
   performance.

### 2. Manifest check Metabase

- `docker manifest inspect metabase/metabase:v0.62.4` → conferma presenza `linux/arm64`
  (ri-verifica di ADR-0016, a costo zero).

### 3. Compose tuning universale (unico file)

- `metabase`: `JAVA_OPTS=-Xmx1g`; limite memoria 2GB; healthcheck completo atteso
  (tarabile nel piano senza nuovo ADR): `interval: 30s`, `timeout: 15s`, `retries: 10`,
  `start_period: 900s` — su Pi la JVM impiega minuti; su desktop `start_period` non
  ritarda un avvio sano, e `retries` alto evita falsi `unhealthy` sotto carico.
  **Margine intenzionale** rispetto alla soglia di accettazione ADR-0025 (avvio ≤ 10
  min): il healthcheck (tuning tecnico, 15 min) è più permissivo del criterio di qualità
  (10 min) — un avvio da 11 minuti viene misurato e bocciato dal protocollo, non ucciso
  dal healthcheck a metà misura. `logging` json-file `max-size: 10m`, `max-file: 3`.
- `backend`: healthcheck completo atteso: `interval: 30s`, `timeout: 10s`, `retries: 5`,
  `start_period: 90s`; `logging` cap analogo; nessun limite di memoria (Python leggero,
  non serve — YAGNI).
- Bump `version="0.1.0-phase7"` e `/health` → `{"phase": "7"}` in `main.py` (stesso pattern
  di chiusura fase di F5/F6; rende leggibile sul Pi quale build sta girando). Se un test
  esistente asserisce i valori version/phase correnti, va aggiornato nello stesso task.
- Valori concreti definitivi fissati nel piano implementativo, tarabili senza nuovo ADR
  (stesso principio di ADR-0023 p.7).
- Vincolo: `docker compose config` valido; stack desktop di produzione continua a
  funzionare identico dopo il tuning (verifica live).

### 4. Runbook `docs/RASPBERRY-PI.md`

Documento operativo per la sessione-Pi futura, scritto ora perché la conoscenza è fresca:

- Prerequisiti: Raspberry Pi OS **64-bit** (Lite consigliato), alimentazione adeguata,
  storage: **minimo 10GB liberi** dopo l'install dell'OS (immagini ~2GB + build cache
  ~2-3GB + margine; in pratica: SD ≥ 32GB, meglio ad alta resistenza o SSD USB — nota
  non bloccante).
- Setup: install Docker (script ufficiale get.docker.com), utente nel gruppo docker,
  `git clone`, `git config core.hooksPath .githooks`, `.env` da `.env.example` (chiavi AI
  opzionali, mai committate).
- **Comando standard** (unico, niente varianti ambigue): prima esecuzione e ogni
  aggiornamento = `docker compose up -d --build` (la build è no-op quando nulla è
  cambiato — mai immagini stale; prima volta sul Pi: build nativa lunga, quantificata a
  spanne nel runbook).
- **Checklist in due parti, separate di proposito** (il criterio di milestone non deve
  contraddire l'esito della misura):
  1. *Validazione full-stack* (= milestone F7): entrambi i container healthy col comando
     standard, 7 pagine React funzionanti da un client LAN, `POST /ai/query` con chiave
     reale, backup manuale. Restore di prova NON eseguito su dati veri senza backup
     esterno preventivo.
  2. *Modo operativo raccomandato* (post-validazione): esito della misura Metabase
     (ADR-0025) → keep, oppure raccomandazione `docker compose stop metabase`
     (riattivabile con `start`). La milestone resta validata in entrambi i casi.
- **Procedura di misura Metabase** (protocollo ADR-0025): comandi (`docker stats
  --no-stream`, `docker events`, timer avvio→healthy), tabella soglie keep/skip con le
  definizioni operative (steady-state, cold/warm), procedura di stop/riattivazione.
- Troubleshooting: JVM lenta al boot (start_period), OOM (dmesg/docker events), build
  lenta, spazio disco esaurito.

### 5. Fuori scope (YAGNI)

- Registry di immagini, CI/CD, GitHub Actions multi-arch: nessun bisogno per single-dev
  con build nativa.
- Watchtower/auto-update sul Pi.
- Tuning scheduler oltre a quanto già esiste (`BACKUP_ON_STARTUP` è già opzionale e
  thread-based; nessun cron aggiuntivo).
- Migrazione storage (SD→SSD), overclock, raffreddamento: hardware, fuori dal repo.
- Esposizione fuori LAN (ADR-0009 invariato).

## Test / verifica

- **Questa sessione (desktop)**: wheel check `--only-binary` passa; buildx arm64 `--load`
  produce immagine eseguibile; container emulato risponde su `/health`; `docker manifest
  inspect` Metabase mostra arm64; `docker compose config` valido; suite pytest completa
  verde — **nessuna logica di business toccata**, l'unico cambiamento applicativo è il
  metadata version/phase in `main.py` (eventuali test che lo asseriscono vengono
  aggiornati nello stesso task); stack desktop rebuild + smoke test live (pagine +
  /health).
- **Sessione-Pi (futura, checklist nel runbook)**: milestone vera e propria — comando
  standard `docker compose up -d --build` sul Pi, checklist parte 1 (validazione
  full-stack), poi protocollo di misura Metabase e raccomandazione operativa (parte 2)
  con esito registrato nello Stato avanzamento.

## Stato finale atteso di questa sessione

ARCHITECTURE.md: F7 **◐ in corso** — preparazione completa e verificata in emulazione,
riga di stato con evidenze e rimando alla checklist runbook; prompt di ripresa → "F7:
eseguire verifica su hardware reale col runbook". CLAUDE.md: fase corrente aggiornata di
conseguenza. La fase si chiude ☑ solo dopo la sessione-Pi.
