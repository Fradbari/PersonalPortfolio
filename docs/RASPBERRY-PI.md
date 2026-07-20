# Raspberry Pi — Runbook di deploy (Fase 7)

Copione operativo per portare "Personal Portfolio" su **Raspberry Pi 4 4GB (arm64)**. Il
hardware non era ancora disponibile al momento della scrittura (2026-07-20): questo documento
è lo script da seguire quando lo sarà, punto per punto, senza reinventare nulla sul momento.
Decisioni e motivazioni complete: **ADR-0024** (strategia arm64, comando unico) e **ADR-0025**
(Metabase su Pi, protocollo di misura) in [docs/DECISIONS.md](DECISIONS.md).

Vale la stessa regola del resto del progetto: **in caso di dubbi o incoerenze, fermarsi e
chiedere all'utente** prima di procedere.

---

## 1. Prerequisiti

- **Raspberry Pi 4, 4GB RAM.**
- **Raspberry Pi OS a 64 bit** (variante **Lite** consigliata — niente desktop, meno RAM
  sottratta ai container). Verifica dopo il primo boot:
  ```bash
  uname -m   # deve stampare: aarch64
  ```
  Se stampa `armv7l` o altro, l'immagine flashata è a 32 bit: reinstallare con la variante
  64 bit prima di continuare — nessuno dei passi successivi è valido su un kernel a 32 bit.
- **Alimentatore ufficiale** Raspberry Pi (un alimentatore sottodimensionato causa
  throttling/instabilità sotto il carico della build Docker, indistinguibile a occhio da un
  bug applicativo).
- **Storage con almeno 32GB**, e **almeno 10GB liberi dopo l'installazione dell'OS** prima di
  avviare la build. Il margine copre: immagini Docker (~2GB tra backend e Metabase),
  build cache (~2-3GB, cresce con `--build` ripetuti), più margine per log e dati applicativi
  (DB, replica, backup). Se lo spazio libero post-OS è inferiore, liberare spazio o usare
  supporto più capiente prima di procedere — non è un problema che si autorisolve durante
  la build (vedi Troubleshooting, §6).
- **Nota non bloccante**: una SD card standard è sufficiente per partire, ma è il componente
  più a rischio d'usura sotto scritture ripetute (immagini Docker, DB, log). Una SD
  **high-endurance** o, meglio, un **SSD USB** come storage primario è una scelta più robusta
  nel tempo — non un prerequisito per la milestone F7, ma una raccomandazione operativa.

---

## 2. Setup (una sola volta)

Da eseguire una volta sola su un Pi appena flashato, in ordine:

```bash
# 1. Installazione Docker Engine (script ufficiale Docker)
curl -fsSL https://get.docker.com | sh

# 2. Permessi: usare Docker senza sudo
sudo usermod -aG docker $USER
# poi RI-ACCEDERE (logout/login o riavvio) perché il nuovo gruppo sia effettivo nella shell corrente

# 3. Clone del repository
git clone <URL del repo>
cd PersonalPortfolio

# 4. Attivazione hook pre-commit (blocca secret nei commit, ADR-0011)
git config core.hooksPath .githooks

# 5. File di configurazione locale
cp .env.example .env
```

Il file `.env` copiato al passo 5 funziona già con i default (one-click). Le chiavi opzionali
(`AI_API_KEY`/`AI_PROVIDER` per Fase 6, `GOOGLE_SA_KEY_PATH`/`GDRIVE_BACKUP_FOLDER_ID` per
Fase 4) vanno valorizzate solo se si vogliono quelle funzionalità attive, e **non vanno mai
committate** — restano locali al Pi, coperte da `.gitignore` (dettagli:
[docs/SECURITY.md](SECURITY.md)).

---

## 3. Comando standard

Un solo comando, sempre lo stesso, sia per il primo avvio sia per ogni aggiornamento
successivo (ADR-0024 p.1):

```bash
docker compose up -d --build
```

Non esistono varianti autorizzate: né `docker compose build` seguito da `up -d`, né un plain
`docker compose up -d` come alternativa. Il `--build` rende il comando idempotente — se nulla
è cambiato la build è no-op (cache) e non produce mai un'immagine stale.

**Prima build sul Pi**: è una build **nativa** (niente QEMU, niente emulazione — il canale di
distribuzione è `git clone` + build locale, non un registry, ADR-0024 p.1), e comprende sia il
build del frontend (`npm ci && npm run build`) sia l'immagine Python del backend. È lecito
aspettarsi un tempo dell'ordine di **decine di minuti**, non secondi: il tempo esatto va
misurato sul hardware reale (nessun numero da spec preesistente — prima misura da registrare
qui o in ARCHITECTURE.md quando disponibile). Gli aggiornamenti successivi, a meno di modifiche
massicce alle dipendenze, sono molto più rapidi grazie alla cache dei layer.

---

## 4. Checklist parte 1 — Validazione full-stack (= milestone F7)

Questa è la milestone letterale di F7: **lo stesso comando, lo stesso file, funziona anche sul
Pi**. Va eseguita per intero, con il full stack (backend + Metabase) avviato tramite il comando
standard del §3 — indipendentemente dall'esito della misura Metabase del §5 (Modello A,
ADR-0025 p.3: nessuna topologia alternativa in questa fase).

- [ ] Entrambi i container risultano `healthy`:
  ```bash
  docker ps
  ```
  (colonna `STATUS` per `pp-backend` e `pp-metabase` deve riportare `healthy`, non solo `Up`.
  **Attenzione**: subito dopo l'avvio è normale vedere `health: starting` anche per molti
  minuti — non è un errore, vedi §6 "JVM lenta al primo avvio" prima di concludere che
  qualcosa è rotto)
- [ ] Endpoint di health del backend risponde con la fase corretta:
  ```bash
  curl http://localhost:8000/health
  # atteso: {"status": "ok", "phase": "7", ...}
  ```
- [ ] Le **7 pagine React** sono raggiungibili e funzionanti da un client sulla stessa LAN
  (non dal Pi stesso), puntando all'IP del Pi:
  `http://<ip-pi>:8000` — Dashboard, Transazioni, Import, Categorie pending, Conti, Backup,
  Assistente AI.
- [ ] `POST /ai/query` con una chiave AI reale (Fase 6) risponde correttamente e la pagina
  "Assistente AI" mostra la **traccia dei tool** chiamati accanto alla risposta.
- [ ] Backup manuale avviato dalla UI (pagina Backup, pulsante) completa con successo.
- [ ] **Restore di prova**: da eseguire **solo dopo** aver messo al sicuro un backup esterno
  preventivo (fuori dal Pi) — il restore sovrascrive il DB live in modo distruttivo
  (`POST /backup/restore` richiede comunque `confirm: true` esplicito, ma l'operazione resta
  irreversibile sui dati precedenti non salvati altrove).

---

## 5. Checklist parte 2 — Misura Metabase e modo operativo (ADR-0025)

Protocollo di misura **fissato prima** di eseguirlo, con definizioni operative esatte e soglie
già decise (ADR-0025 p.2) — non è a discrezione di chi esegue la misura interpretare "avvio
completato" o "carico stabile" al momento.

| Misura | Definizione operativa | Soglia | Comando/strumento |
|---|---|---|---|
| Tempo di avvio | Dal **ritorno** del comando standard (§3) al container `pp-metabase` riportato `healthy` | **≤ 10 min** (nota: margine intenzionale sotto lo `start_period` di 900s/15 min del healthcheck — il healthcheck non deve uccidere una misura borderline, che spetta al protocollo bocciare) | `docker ps` / `docker inspect --format='{{.State.Health.Status}}' pp-metabase` |
| RAM steady-state | Media di **3 letture** `docker stats --no-stream` per `pp-metabase`, distanziate **1 minuto** l'una dall'altra, con la prima lettura **5 minuti dopo il primo login** completato a Metabase e **nessun import in corso** sul backend | **≤ 1.5GB** | `docker stats --no-stream pp-metabase` |
| Dashboard F3 "Personal Portfolio - Overview" | **Cold**: primo caricamento della dashboard subito dopo l'avvio (JVM appena scaldata) — **registrata, solo informativa, nessuna soglia**. **Warm**: secondo caricamento della stessa dashboard, immediatamente dopo il cold | **Warm < 10s** | Cronometro manuale sul caricamento della pagina Metabase |
| Stabilità (24h) | Nessun OOM-kill del container Metabase nell'arco di 24h di funzionamento continuo | **Zero eventi OOM** | `docker events --since 24h \| grep -i oom` e `dmesg \| grep -i oom` |

> Nota per la misura: se durante le 24h si osserva swap attivo sul Pi (`free -h`, colonna
> Swap usata in crescita), segnalarlo nell'esito — con solo `mem_limit` impostato, Docker
> permette di default fino a 2x in swap, e su SD card il thrashing è sia lento sia usurante.
> Candidato fix (fuori scope F7, da valutare a misura fatta): `memswap_limit` nel compose.

### Esito e modo operativo (Modello A)

La milestone F7 (§4) si valida **sempre** col full stack e col comando standard, a prescindere
dall'esito di questa misura. Se **tutte** le soglie sono rispettate: **keep** — Metabase resta
attivo come dashboard principale, nessuna azione ulteriore.

Se una o più soglie sforano, l'esito è una **raccomandazione operativa post-validazione**, non
una topologia alternativa né un file o comando diverso (ADR-0025 p.3):

```bash
# Sospendere Metabase (il container resta definito nel compose, solo fermo)
docker compose stop metabase

# Riattivarlo in un secondo momento (es. hardware futuro più capace)
docker compose start metabase
```

In questo scenario la UI React diventa la dashboard quotidiana (copre già lettura e scrittura
sui dati, Fase 5). Metabase **non viene rimosso** dal `docker-compose.yml`: resta disponibile,
riattivabile con un comando, senza richiedere un nuovo ADR per questo esito (già coperto qui).

**L'esito di questa misura va riportato nella sezione "Stato avanzamento" di
[docs/ARCHITECTURE.md](ARCHITECTURE.md)** alla riga F7, con i numeri effettivi rilevati.

---

## 6. Troubleshooting

- **Metabase non diventa `healthy` entro pochi minuti** — non è necessariamente un errore: la
  JVM su Pi 4 impiega minuti ad avviarsi, e lo `start_period` del healthcheck è **900s (15
  min)** apposta (ADR-0024 p.4). Prima dei 15 minuti, un container ancora `starting` è
  atteso, non un guasto. Se supera i 15 minuti senza diventare `healthy`, allora è un problema
  reale da indagare (log: `docker logs pp-metabase`).
- **Sospetto OOM (container riavviato da solo, o sistema diventato lento/irraggiungibile)**:
  ```bash
  docker events --since 24h | grep -i oom
  dmesg | grep -i oom
  ```
  Se compaiono eventi OOM, vedi §5 per il modo operativo (stop Metabase).
- **Build lenta o spazio esaurito durante `docker compose up -d --build`**:
  ```bash
  docker system df          # quanto spazio occupano immagini/cache/volumi
  docker builder prune      # libera la build cache non più referenziata
  ```
  Verificare anche lo spazio libero sul filesystem host (§1 — margine minimo 10GB). Una build
  che si blocca o rallenta drasticamente a metà è quasi sempre un problema di spazio, non di
  CPU.
- **Backend non `healthy` nei primi 90 secondi**: lo `start_period` del backend è **90s**
  (interval 30s/timeout 10s/retries 5) — pensato per un avvio Python più lento sul Pi rispetto
  al desktop (ADR-0024 p.4). Entro i primi 90s un `pp-backend` ancora `starting` è normale;
  oltre, controllare `docker logs pp-backend`.

---

## 7. Nota egress

Le stesse regole di [docs/SECURITY.md](SECURITY.md) valgono identiche sul Pi: le chiamate
`POST /ai/query` (Fase 6) e il backup su Google Drive (Fase 4) fanno uscire dati verso
Internet anche dal Raspberry Pi, non solo dal desktop. Restano flussi **uscenti avviati
dall'utente**, non una nuova esposizione **entrante** — l'app continua a essere raggiungibile
solo dalla rete locale (ADR-0009): il deploy sul Pi non apre nessuna porta verso l'esterno che
non fosse già prevista dal compose.
