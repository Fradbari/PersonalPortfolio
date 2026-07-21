# Documentazione — Personal Portfolio

Indice dei documenti canonici del progetto.

| File | Descrizione | Quando consultarlo |
|------|-------------|---------------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Piano architetturale, mappa fasi, stato avanzamento vivo, prompt di ripresa sviluppo | Prima di riprendere il lavoro o capire il quadro d'insieme |
| [DECISIONS.md](DECISIONS.md) | Registro ADR (Architecture Decision Records, 32 al momento) — perché ogni scelta tecnica è stata presa | Quando serve capire il "perché" dietro una scelta tecnica |
| [SECURITY.md](SECURITY.md) | Policy secret/credenziali, hook pre-commit, **campi sensibili nella UI** (whitelist/blacklist `/settings`), egress verso il provider AI | Prima di gestire secret, esporre una configurazione in interfaccia o modificare l'enforcement |
| [RASPBERRY-PI.md](RASPBERRY-PI.md) | Runbook deploy Raspberry Pi 4 arm64 (Fase 7) | Quando si esegue il deploy/validazione su hardware Raspberry Pi |
| [GETTING_STARTED.md](GETTING_STARTED.md) | Guida avvio da zero: prerequisiti, docker compose, primo accesso, troubleshooting | Al primo setup del progetto |
| [USER_GUIDE.md](USER_GUIDE.md) | Guida funzionale completa: come usare ogni funzionalità (import, dashboard, backup, UI, AI) | Per capire come usare una funzionalità specifica |

## docs/superpowers/

Contiene i plans/specs storici, uno per fase. Non serve dettagliarli qui: vedi
[docs/superpowers/README.md](superpowers/README.md) per l'indice.

## Stato fase corrente (2026-07-21)

F0-F6 + F-DEBT completate.

**F7 (Raspberry Pi arm64): ◐ parcheggiata in attesa dell'hardware, non bloccante.** Gate arm64
verificato da desktop, runbook pronto; resta la validazione sul Pi 4 reale. Vedi anche i punti
aperti P1-P4 in [ARCHITECTURE.md](ARCHITECTURE.md).

**Fase corrente: Blocco A (F8 dark mode + F9 settings).** La roadmap F8-F14 è stata pianificata il
2026-07-21 in tre blocchi — spec
[2026-07-21-f8-f14-roadmap-design.md](superpowers/specs/2026-07-21-f8-f14-roadmap-design.md), ADR
0026 → 0032. Nessun codice F8-F14 ancora scritto.

| Blocco | Branch | Fasi |
|---|---|---|
| A — Fondamenta UI | `f8-f9-theme-settings` | F8 dark mode · F9 settings centralizzate |
| B — Superficie transazioni | `f11-f12-f13-transactions` | F11 inserimento manuale · F12 filtri e FTS5 · F13 dashboard |
| C — Integrazioni | `f10-f14-drive-chat` | F10 test connettività GDrive · F14 storicità chat AI |
