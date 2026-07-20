# Sottoagenti di progetto

Indice dei sottoagenti specializzati di Personal Portfolio: attivarli quando parte la fase relativa.

## ingestion-agent.md
Parser export My Finance (.xlsx), adapter un-pivot master Google Sheet, category mapper e dedup idempotente.
**Fasi**: F1, F2. **Vincoli**: dedup solo su campi stabili (ADR-0005); dry-run obbligatorio in F2.

## schema-agent.md
Modelli SQLAlchemy, Alembic revision, integrità schema SQLite (WAL).
**Fasi**: ogni fase che modifica lo schema (es. F1, F4). **Vincoli**: ogni cambio schema = una alembic revision versionata (ADR-0003), mai ALTER manuale non tracciato.

## dashboard-agent.md
Setup Metabase, replica read-only atomica, dashboard trend/categorie/saldo.
**Fasi**: F3, a supporto di F5. **Vincoli**: Metabase legge solo la replica, mai il DB live (ADR-0004).

## backup-agent.md
Dump SQLite + export .xlsx, upload Google Drive via Service Account, backup locale, retention, restore.
**Fasi**: F4. **Vincoli**: Service Account mai nel repo (ADR-0011); restore richiede conferma esplicita.

## react-ui-agent.md
Frontend React+Vite+TS (TanStack Query, Tailwind/shadcn, Recharts), endpoint FastAPI read+write, pagine dashboard/transazioni/import/categorie pending/conti/backup.
**Fasi**: F5. **Vincoli**: affianca Metabase, non lo sostituisce (ADR-0004); nessuna Alembic revision per questo layer.

## ai-agent.md
Layer AI: adapter provider-agnostico (unico adapter Gemini), tool registry read-only, loop tool-use manuale, `POST /ai/query`, service layer insights con filtri.
**Fasi**: F6. **Vincoli**: **mai** scrittura sul DB — nessun tool di scrittura, mai (ADR-0023).

## Note
- Attivarli quando parte la fase relativa. Collegati alla skill superpower generale.
- Fase corrente: **F7 in corso** — nessun agente dedicato F7, gestito da subagent-driven-development generico.
