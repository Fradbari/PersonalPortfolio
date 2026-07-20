# Getting Started — Personal Portfolio

Guida avvio da zero. Per la guida funzionale (cosa fare una volta avviato) vedi
[USER_GUIDE.md](USER_GUIDE.md). Per architettura/decisioni vedi [README.md](README.md).

## Prerequisiti

- **Docker** + **Docker Compose** (v2, comando `docker compose`, non `docker-compose`).
- **Git**.
- **Credenziali Google Drive (opzionali)** — solo se vuoi il backup automatico su Drive
  (Fase 4). Senza, il backup locale funziona comunque (degradazione graceful, ADR-0018 p.3).
  Serve una Service Account (JSON key) con una cartella Drive condivisa in ruolo Editor —
  procedura completa in [SECURITY.md § Backup su Google Drive](SECURITY.md#backup-su-google-drive-condivisione-cartella-con-la-service-account-fase-4-adr-0018).
- **Chiave AI (opzionale)** — solo per la query in linguaggio naturale (Fase 6). Senza,
  l'endpoint `/ai/query` risponde 4xx esplicito, il resto dell'app resta invariato.

## 1. Clone e configurazione

```bash
git clone <url-repo>
cd PersonalPortfolio

# attiva il pre-commit hook che blocca i secret (ADR-0011) — fallo subito, prima del primo commit
git config core.hooksPath .githooks

# copia il template env (opzionale: l'app parte anche senza .env, usa i default)
cp .env.example .env
```

Variabili rilevanti in `.env` (vedi `.env.example` per l'elenco completo commentato):
- `BACKEND_PORT` (default 8000), `METABASE_PORT` (default 3000)
- `GOOGLE_SA_KEY_PATH` + `GDRIVE_BACKUP_FOLDER_ID` — solo se vuoi backup su Drive
- `AI_PROVIDER` + `AI_API_KEY` + `AI_MODEL` — solo se vuoi la query AI (**mai** `GEMINI_API_KEY`,
  la config è provider-agnostica, ADR-0023)

Se usi la Service Account Google, salva il JSON in `./secrets/service_account.json` sull'host
(montato read-only nel container, mai committato — la cartella `secrets/` è gitignored).

## 2. Avvio

```bash
docker compose up -d --build
```

`--build` serve al primo avvio e dopo ogni `git pull` che tocca codice; se non è cambiato nulla
il rebuild è no-op. Per riavvii successivi senza modifiche basta `docker compose up -d`.

Verifica health:
```bash
curl http://localhost:8000/health
```
Risposta attesa: `200` con la fase corrente del progetto. Entrambi i container devono risultare
`healthy` (`docker compose ps`) — il backend tipicamente entro ~90s (`start_period`), Metabase
può impiegare diversi minuti al primo avvio (JVM, `start_period: 900s`, più lento su Raspberry
Pi che su desktop, ADR-0024).

## 3. Primo accesso

| Servizio | URL | Note |
|---|---|---|
| **Backend API** | `http://localhost:8000` | Anche Swagger UI su `/docs` |
| **UI React** | `http://localhost:8000` | **Stessa porta del backend** — build statico servito dal container FastAPI (ADR-0019), nessun servizio separato in produzione |
| **Metabase** | `http://localhost:3000` | Dashboard "Personal Portfolio - Overview"; primo accesso richiede setup account Metabase (a parte, non gestito da questo repo) |

**Nota sulla porta 5173**: esiste solo in modalità sviluppo (`npm run dev` dentro `frontend/`,
Vite dev server con hot-reload). In produzione (il `docker compose up` sopra) non è esposta:
la UI React è servita insieme al backend sulla 8000. Vedi [frontend/README.md](../frontend/README.md)
per lo sviluppo locale del frontend fuori Docker.

## 4. Verifica pre-commit hook

Già attivato al passo 1 (`git config core.hooksPath .githooks`). Test rapido — vedi
[SECURITY.md § Test del hook](SECURITY.md#test-del-hook) per il comando completo: crea una
fake Service Account key e prova a committarla, il commit deve essere **bloccato**.

## 5. Risoluzione problemi comuni

**Porta occupata** (`8000` o `3000` già in uso): cambia `BACKEND_PORT`/`METABASE_PORT` in `.env`,
poi `docker compose up -d --build`.

**Secrets mancanti**: l'app parte comunque. Drive e AI restano disattivi con errore esplicito
sulle rispettive funzionalità (degradazione graceful) — nessun crash, nessun impatto sul resto.

**Migrazione DB non applicata / schema disallineato**: le migrazioni Alembic girano dentro il
container backend, non servono comandi manuali per il normale avvio. Se serve intervenire a mano:
```bash
docker compose exec backend alembic upgrade head
```
Non modificare mai lo schema a mano (`ALTER TABLE` diretto) — ogni cambio richiede una
`alembic revision -m "descrizione"` (ADR-0003, regola non negoziabile in CLAUDE.md).

**Metabase resta `unhealthy` a lungo**: normale nei primi minuti (JVM lenta ad avviarsi,
specie su Raspberry Pi). Il `start_period: 900s` in `docker-compose.yml` è intenzionalmente
alto per non uccidere un avvio lento — se supera i 10 minuti vedi il protocollo di misura in
[RASPBERRY-PI.md](RASPBERRY-PI.md) (ADR-0025).

**Replica Metabase vuota/non aggiornata**: la replica si rigenera solo al completamento di un
import (`import_batch`), non in continuo — è un meccanismo a snapshot, non realtime (ADR-0004).
