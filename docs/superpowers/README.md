# Superpowers — Archivio Spec & Piani

Archivio storico di spec e piano implementativo per fase, prodotto dal workflow
Subagent-Driven Development (SDD).

## Convenzione naming

- **Spec**: `{data}-{fase}-{nome}-design.md` (`docs/superpowers/specs/`)
- **Piano implementativo**: `{data}-{fase}-{nome}.md` (`docs/superpowers/plans/`)

## Indice per fase

| Fase | Spec | Piano | Stato |
|------|------|-------|-------|
| F4 — Backup automation | [2026-07-14-backup-automation-design.md](specs/2026-07-14-backup-automation-design.md) | [2026-07-14-backup-automation.md](plans/2026-07-14-backup-automation.md) | ☑ |
| F5 — UI React | [2026-07-15-f5-react-ui-design.md](specs/2026-07-15-f5-react-ui-design.md) | [2026-07-15-f5-react-ui.md](plans/2026-07-15-f5-react-ui.md) | ☑ |
| F6 — AI NL query | [2026-07-18-f6-ai-nl-query-design.md](specs/2026-07-18-f6-ai-nl-query-design.md) | [2026-07-18-f6-ai-nl-query.md](plans/2026-07-18-f6-ai-nl-query.md) | ☑ |
| F7 — Raspberry arm64 | [2026-07-20-f7-raspberry-arm64-design.md](specs/2026-07-20-f7-raspberry-arm64-design.md) | [2026-07-20-f7-raspberry-arm64.md](plans/2026-07-20-f7-raspberry-arm64.md) | ◐ in corso (2026-07-20), attesa hardware |

## Nota

Questi documenti sono lo storico immutabile della fase al momento della progettazione:
**non vanno aggiornati retroattivamente**. Lo stato vivo del progetto è mantenuto in
[docs/ARCHITECTURE.md](../ARCHITECTURE.md).

Per la guida funzionale d'uso di ogni fase (F1-F6) vedi [docs/USER_GUIDE.md](../USER_GUIDE.md); per
l'avvio del progetto [docs/GETTING_STARTED.md](../GETTING_STARTED.md).

Le fasi F0, F1, F2, F3 e F-DEBT non hanno spec/piano in questo archivio: sono fasi
precedenti all'adozione del workflow SDD o gestite con modalità diverse.
