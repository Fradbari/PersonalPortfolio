# Documentazione — Personal Portfolio

Indice dei documenti canonici del progetto.

| File | Descrizione | Quando consultarlo |
|------|-------------|---------------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Piano architetturale, mappa fasi, stato avanzamento vivo, prompt di ripresa sviluppo | Prima di riprendere il lavoro o capire il quadro d'insieme |
| [DECISIONS.md](DECISIONS.md) | Registro ADR (Architecture Decision Records, 25 al momento) — perché ogni scelta tecnica è stata presa | Quando serve capire il "perché" dietro una scelta tecnica |
| [SECURITY.md](SECURITY.md) | Policy secret/credenziali, hook pre-commit | Prima di gestire secret o modificare l'enforcement |
| [RASPBERRY-PI.md](RASPBERRY-PI.md) | Runbook deploy Raspberry Pi 4 arm64 (Fase 7) | Quando si esegue il deploy/validazione su hardware Raspberry Pi |

## docs/superpowers/

Contiene i plans/specs storici, uno per fase. Non serve dettagliarli qui: vedi
[docs/superpowers/README.md](superpowers/README.md) per l'indice.

## Stato attuale del progetto

F0-F6 + F-DEBT completate. F7 (Raspberry Pi arm64) in preparazione: gate arm64 verificato da
desktop, runbook pronto — resta in attesa dell'hardware Raspberry Pi 4 per la validazione finale.
