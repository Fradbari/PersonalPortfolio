# F7 — Portabilità Raspberry Pi arm64 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development`
> (raccomandata, stesso processo di F5/F6) oppure `superpowers:executing-plans`. Gli step usano
> checkbox (`- [ ]`). Task 1 e Task 4 sono task di verifica/chiusura condotti dal controller
> (comandi lunghi con QEMU e docs di fase); Task 2 e 3 vanno a sottoagenti (sonnet, escalation
> selettiva a modello superiore solo se bloccati).

**Goal:** lo stesso `docker compose up -d --build` dell'ambiente desktop è pronto a girare su
Raspberry Pi 4 4GB arm64, con gate di portabilità verificato da desktop e runbook completo per
la sessione di verifica su hardware reale (hardware oggi non disponibile).

**Architecture:** nessun servizio nuovo e nessuna logica di business toccata. Quattro
interventi: (1) gate fail-fast di portabilità arm64 eseguito da desktop (wheel check,
cross-build QEMU, smoke emulato); (2) tuning universale del `docker-compose.yml` unico
(healthcheck completi, log rotation, limiti JVM Metabase) + bump version/phase; (3) runbook
`docs/RASPBERRY-PI.md` con checklist in 2 parti e protocollo di misura Metabase; (4) chiusura
parziale di fase (◐ — resta pendente la sessione su hardware reale).

**Tech Stack:** Docker buildx + QEMU (pre-verifica), pip `--only-binary` (wheel check),
Docker Compose (tuning), FastAPI (solo metadata version/phase).

**Riferimenti obbligatori:** ADR-0024, ADR-0025 (vincolanti), spec
`docs/superpowers/specs/2026-07-20-f7-raspberry-arm64-design.md` (rev. 3).

## Global Constraints

- **Un solo `docker-compose.yml`**, nessun override/profile (ADR-0024 p.3). Comando standard
  unico: `docker compose up -d --build` (primo bootstrap e aggiornamenti, ADR-0024 p.1).
- **Nessuna logica di business toccata**: l'unico cambiamento applicativo ammesso è il
  metadata `version="0.1.0-phase7"` / `{"phase": "7"}` in `backend/app/main.py:31,45`.
  Verificato: nessun test asserisce i valori attuali (grep su `backend/` trova solo main.py).
- **Nessun cambio di schema, nessuna Alembic revision. Nessun secret committato** (hook attivo).
- Healthcheck target (ADR-0024 p.4, tarabili senza nuovo ADR): backend
  `interval: 30s, timeout: 10s, retries: 5, start_period: 90s`; metabase
  `interval: 30s, timeout: 15s, retries: 10, start_period: 900s`.
- Metabase: `JAVA_OPTS: -Xmx1g`, `mem_limit: 2g` (ADR-0025 p.1). Immagine resta
  `metabase/metabase:v0.62.4` pinnata (ADR-0016) — nessun bump di versione in F7.
- Log rotation per-servizio nel compose: `json-file`, `max-size: "10m"`, `max-file: "3"`
  (mai toccare `daemon.json`, ADR-0024 p.3).
- Suite pytest completa deve restare verde: 100 test attesi
  (`cd backend && PYTHONPATH=. python -m pytest`).
- Modello A (ADR-0025 p.3): il runbook non introduce topologie/comandi alternativi; lo skip
  Metabase è documentato solo come raccomandazione operativa post-validazione
  (`docker compose stop metabase` / `start`).
- Deviazione sostanziale dal piano → fermarsi, chiedere. Se il gate del Task 1 fallisce, la
  correzione del Dockerfile è una deviazione da concordare, non da improvvisare.

---

## Task 1: Gate di portabilità arm64 (fail-fast, condotto dal controller)

**Files:** nessuno da modificare se il gate passa — task di verifica pura. Evidenze nel
ledger. Eventuali fix emersi = deviazione da concordare con l'utente prima di implementare.

**Interfaces:**
- Produces: esito gate (pass/fail con evidenze) — prerequisito logico dei Task 2-4.

- [ ] **Step 1: Wheel check fail-fast (senza QEMU, secondi)**

```bash
cd backend
pip download --only-binary=:all: --platform manylinux2014_aarch64 \
  --python-version 3.12 --implementation cp --abi cp312 \
  -r requirements.txt -d "$TMP/wheelcheck-arm64"
```

Expected: exit 0, sole wheel scaricate. Se fallisce su un pacchetto: distinguere
compilazione nativa C/Rust (gate FAIL, fermarsi e concordare) da sdist puro-Python
(eccezione documentabile nel ledger, gate resta PASS — scelta conservativa ADR-0024 p.2a).
Nota: `--only-binary=:all:` con `--platform` richiede anche `--abi`/`--implementation`
espliciti per selezionare le wheel `cp312-manylinux2014_aarch64`.

- [ ] **Step 2: Cross-build arm64 eseguibile (QEMU, lento — run_in_background)**

```bash
docker buildx build --platform linux/arm64 -f backend/Dockerfile \
  -t pp-backend:arm64-verify --load .
docker image inspect pp-backend:arm64-verify --format '{{.Architecture}}'
```

Expected: build completa; inspect stampa `arm64`. Il gate è il risultato (immagine
caricata), non l'ispezione del log.

- [ ] **Step 3: Smoke test emulato**

```bash
docker run --rm --platform linux/arm64 -e DB_PATH=/tmp/smoke.db \
  pp-backend:arm64-verify python -c "import app.main; print('import-ok')"
docker run -d --rm --platform linux/arm64 --name pp-arm64-smoke \
  -e DB_PATH=/tmp/smoke.db -p 18000:8000 pp-backend:arm64-verify
# attesa generosa: QEMU è 5-20x più lento
curl -s http://localhost:18000/health
docker stop pp-arm64-smoke
```

Expected: `import-ok`; `/health` risponde `{"status":"ok",...}`. Solo avvio, non
performance (ADR-0024 p.2c).

- [ ] **Step 4: Manifest Metabase arm64 (ri-conferma ADR-0016)**

```bash
docker manifest inspect metabase/metabase:v0.62.4 | grep -A2 '"architecture": "arm64"'
```

Expected: presenza piattaforma `linux/arm64`.

- [ ] **Step 5: Registrare le evidenze nel ledger** (`.superpowers/sdd/progress.md`),
      incluse eventuali eccezioni sdist puro-Python. Nessun commit (nessun file di repo
      toccato).

---

## Task 2: Compose tuning universale + bump phase 7

**Files:**
- Modify: `docker-compose.yml` (healthcheck backend righe 22-27, blocco metabase righe 30-48)
- Modify: `backend/app/main.py:31` (version) e `backend/app/main.py:45` (phase)
- Test: nessun test nuovo (nessuna logica); la suite esistente (100) deve restare verde

**Interfaces:**
- Consumes: esito PASS del Task 1.
- Produces: compose finale usato da Task 3 (il runbook cita i valori reali) e Task 4.

- [ ] **Step 1: Tuning backend nel compose** — sostituire il blocco healthcheck del servizio
      `backend` (righe 22-27) e aggiungere `logging`:

```yaml
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 90s     # Pi 4: avvio Python piu' lento; innocuo su desktop (ADR-0024)
    logging:
      driver: json-file
      options:
        max-size: "10m"     # protezione SD card del Pi (ADR-0024 p.3)
        max-file: "3"
```

- [ ] **Step 2: Tuning metabase nel compose** — nel servizio `metabase`: aggiungere
      `JAVA_OPTS` all'`environment` esistente, `mem_limit`, healthcheck completo, `logging`:

```yaml
    environment:
      MB_DB_FILE: /metabase-data/metabase.db
      JAVA_OPTS: -Xmx1g          # 4GB totali sul Pi: 1-2GB al resto del sistema (ADR-0025)
    mem_limit: 2g                # tetto duro contro OOM di sistema sul Pi (ADR-0025)
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:3000/api/health || exit 1"]
      interval: 30s
      timeout: 15s
      retries: 10
      start_period: 900s   # JVM su Pi 4: minuti. Margine sopra la soglia di misura
                           # ADR-0025 (10 min): il healthcheck non uccide una misura
                           # borderline che spetta al protocollo bocciare.
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

- [ ] **Step 3: Bump metadata fase in `backend/app/main.py`**
      Riga 31: `version="0.1.0-phase6"` → `version="0.1.0-phase7"`.
      Riga 45: `{"status": "ok", "phase": "6", ...}` → `{"status": "ok", "phase": "7", ...}`.

- [ ] **Step 4: Validazione statica compose**

Run: `docker compose config --quiet && echo VALID`
Expected: `VALID` (nessun warning di sintassi/chiavi sconosciute).

- [ ] **Step 5: Suite completa**

Run: `cd backend && PYTHONPATH=. python -m pytest`
Expected: `100 passed` (6 warning preesistenti F4 ammessi, nessuno nuovo).

- [ ] **Step 6: Rebuild + smoke live desktop (comando standard)**

Run: `docker compose up -d --build`, attendere, poi `curl -s http://localhost:8000/health`
e `docker ps --format '{{.Names}} {{.Status}}'`.
Expected: `"phase": "7"`; entrambi i container `healthy`; Metabase su :3000 raggiungibile.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml backend/app/main.py
git commit -m "feat(F7): tuning compose universale per Pi 4 (healthcheck, log rotation, limiti JVM) e bump phase 7"
```

---

## Task 3: Runbook `docs/RASPBERRY-PI.md`

**Files:**
- Create: `docs/RASPBERRY-PI.md`

**Interfaces:**
- Consumes: valori reali del compose dal Task 2; protocollo e soglie ADR-0025; comando
  standard ADR-0024.

- [ ] **Step 1: Scrivere il runbook** con esattamente queste sezioni (contenuti vincolati da
      spec/ADR — niente invenzioni):

  1. **Prerequisiti**: Raspberry Pi 4 4GB; Raspberry Pi OS **64-bit** (Lite consigliato;
     `uname -m` deve dare `aarch64`); alimentatore ufficiale; storage ≥ 32GB con **≥ 10GB
     liberi** post-OS (immagini ~2GB + build cache ~2-3GB + margine); nota non bloccante su
     SD high-endurance / SSD USB.
  2. **Setup** (una sola volta): `curl -fsSL https://get.docker.com | sh`,
     `sudo usermod -aG docker $USER` + re-login, `git clone <repo>`,
     `git config core.hooksPath .githooks`, `cp .env.example .env` (chiavi AI/Metabase
     opzionali, mai committate).
  3. **Comando standard** (unico, primo bootstrap e ogni aggiornamento):
     `docker compose up -d --build`. Prima volta sul Pi: build nativa lunga — ordine di
     grandezza decine di minuti (frontend npm + immagine Python), da misurare.
  4. **Checklist parte 1 — Validazione full-stack (= milestone F7)**: entrambi i container
     `healthy` (`docker ps`); `/health` → `"phase": "7"`; le 7 pagine React da un client
     LAN (`http://<ip-pi>:8000`); `POST /ai/query` con chiave reale (risposta con traccia
     tool); backup manuale da UI. Restore di prova SOLO dopo backup esterno preventivo.
  5. **Checklist parte 2 — Misura Metabase e modo operativo (ADR-0025)**: tabella
     protocollo con le definizioni operative esatte (timer avvio = ritorno del comando →
     container `healthy`, soglia ≤ 10 min; RAM steady-state = media 3 letture
     `docker stats --no-stream` a 1 min di distanza da 5 min post-primo-login, soglia
     ≤ 1.5GB; dashboard F3 "Personal Portfolio - Overview" warm < 10s, cold registrata;
     nessun OOM in 24h via `docker events --since 24h` e `dmesg | grep -i oom`). Esito:
     keep, oppure raccomandazione `docker compose stop metabase` (riattivazione:
     `docker compose start metabase`). L'esito va riportato nello Stato avanzamento di
     ARCHITECTURE.md.
  6. **Troubleshooting**: JVM lenta (start_period 900s: non è un errore prima dei 15 min);
     OOM (`dmesg`, `docker events`); build lenta/spazio esaurito (`docker system df`,
     `docker builder prune`); healthcheck backend nei primi 90s.
  7. **Nota egress**: le chiamate AI (`/ai/query`) e il backup Drive escono verso Internet
     anche dal Pi — stesse regole di SECURITY.md, nessuna esposizione entrante nuova
     (ADR-0009).

- [ ] **Step 2: Verifica coerenza interna** — il comando nel runbook è SOLO
      `docker compose up -d --build`; i valori healthcheck/limiti citati combaciano col
      compose reale del Task 2; le soglie combaciano con ADR-0025.

- [ ] **Step 3: Commit**

```bash
git add docs/RASPBERRY-PI.md
git commit -m "docs(F7): runbook Raspberry Pi — setup, validazione full-stack, protocollo misura Metabase"
```

---

## Task 4: Chiusura parziale di fase (controller)

**Files:**
- Modify: `docs/ARCHITECTURE.md` (riga F7 dello Stato avanzamento → ◐ con evidenze; Prompt
  di ripresa → sessione-Pi col runbook)
- Modify: `CLAUDE.md` (riga "Fase corrente" → F7 in corso, preparazione fatta, attesa hardware)
- Modify: `.superpowers/sdd/progress.md` (ledger F7)

- [ ] **Step 1: ARCHITECTURE.md** — riga F7: ◐ con evidenze reali (esito gate Task 1, valori
      tuning, runbook, 100 test verdi, smoke desktop OK); esplicitare che la milestone si
      chiude solo con la checklist parte 1 sul Pi reale. Prompt di ripresa: sessione-Pi =
      "segui docs/RASPBERRY-PI.md, riporta esiti checklist 1 e 2, aggiorna stato".
- [ ] **Step 2: CLAUDE.md** — "Fase corrente: F7 — preparazione completata (gate arm64
      passato in emulazione), verifica su hardware Pi pendente."
- [ ] **Step 3: Ledger** — voci task-per-task F7 (formato F6).
- [ ] **Step 4: Commit**

```bash
git add docs/ARCHITECTURE.md CLAUDE.md
git commit -m "docs(F7): chiusura parziale — gate arm64 verificato, runbook pronto, attesa hardware"
```

---

## Note di esecuzione

- QEMU: se `docker buildx build --platform linux/arm64` fallisce con `exec format error`,
  installare gli emulatori: `docker run --privileged --rm tonistiigi/binfmt --install arm64`
  (Docker Desktop su Windows li include già di norma).
- La build QEMU può superare i 10 minuti: lanciarla con run_in_background, mai con timeout
  corti.
- Il tag `pp-backend:arm64-verify` e l'immagine emulata vanno rimossi a fine Task 1
  (`docker rmi pp-backend:arm64-verify`) — non devono restare a occupare disco.
- Dopo il Task 2 il desktop resta l'ambiente di produzione attivo: verificare sempre che lo
  stack riparta healthy prima di proseguire.
