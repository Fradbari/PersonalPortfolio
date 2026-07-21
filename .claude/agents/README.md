# Sottoagenti di progetto

Indice dei sottoagenti specializzati di Personal Portfolio: attivarli quando parte la fase relativa.

## ingestion-agent.md
Parser export My Finance (.xlsx), adapter un-pivot master Google Sheet, category mapper e dedup idempotente.
**Fasi**: F1, F2. **Vincoli**: dedup solo su campi stabili (ADR-0005); dry-run obbligatorio in F2;
da F11 l'importer confronta sempre l'**hash base**, mai il suffisso `#n` delle ripetizioni manuali (ADR-0028).

## schema-agent.md
Modelli SQLAlchemy, Alembic revision, integrità schema SQLite (WAL).
**Fasi**: ogni fase che modifica lo schema — F1, F9 (`settings`), F12 (FTS5 `transactions_fts` + trigger), F14 (`chat_sessions`/`chat_messages`).
**Vincoli**: ogni cambio schema = una alembic revision versionata (ADR-0003), mai ALTER manuale non tracciato;
**numero e `down_revision` si fissano al merge, non alla scrittura** — `alembic heads` deve dare una sola riga.

## dashboard-agent.md
Setup Metabase, replica read-only atomica, dashboard trend/categorie/saldo; da F13 anche i pannelli React complementari.
**Fasi**: F3, a supporto di F5, F13. **Vincoli**: Metabase legge solo la replica, mai il DB live (ADR-0004);
`services/insights.py` si **estende**, mai si duplica; la parola "patrimonio" è vietata in UI (ADR-0030).

## backup-agent.md
Dump SQLite + export .xlsx, upload Google Drive via Service Account, backup locale, retention, restore; da F10 il test di connettività Drive.
**Fasi**: F4, F10. **Vincoli**: Service Account mai nel repo (ADR-0011); restore richiede conferma esplicita;
il probe `gdrive-test` **scrive davvero** e non espone mai folder id o path SA (ADR-0031);
dopo un restore va ricostruito l'indice FTS5 (ADR-0029).

## react-ui-agent.md
Frontend React+Vite+TS (TanStack Query, Tailwind/shadcn, Recharts), endpoint FastAPI read+write, pagine dashboard/transazioni/import/categorie pending/conti/backup/assistente AI; da F8 anche temi, settings, form manuale, filtri e pannelli.
**Fasi**: F5, F8, F9, F11, F12, F13. **Vincoli**: affianca Metabase, non lo sostituisce (ADR-0004);
nessuna Alembic revision per questo layer; nessun colore fuori dal `chartConfig` condiviso;
Tailwind resta v3 e la CLI shadcn resta non inizializzata (ADR-0026);
ogni impostazione esposta passa da `/settings` (ADR-0027).

## ai-agent.md
Layer AI: adapter provider-agnostico (unico adapter Gemini), tool registry read-only, loop tool-use manuale, `POST /ai/query`, service layer insights con filtri; da F14 persistenza conversazioni e finestra di contesto.
**Fasi**: F6, F14. **Vincoli**: **mai** scrittura sul DB da parte del modello — nessun tool di scrittura, mai
(ADR-0023); la persistenza è scritta dal router, mai da un tool (ADR-0032).

## Blocchi roadmap F8-F14

| Blocco | Branch | Fasi | Agenti |
|---|---|---|---|
| **A — Fondamenta UI** | `f8-f9-theme-settings` | F8, F9 | react-ui-agent, schema-agent |
| **B — Superficie transazioni** | `f11-f12-f13-transactions` | F11, F12, F13 | react-ui-agent, schema-agent, dashboard-agent |
| **C — Integrazioni** | `f10-f14-drive-chat` | F10, F14 | backup-agent, ai-agent, schema-agent |

Ordine vincolante: **A prima di B**. C è indipendente funzionalmente, ma **non** nella catena Alembic.

## Note
- Attivarli quando parte la fase relativa. Collegati alla skill superpower generale.
- Fase corrente (2026-07-21): **Blocco A (F8 dark mode + F9 settings)**. F7 ◐ parcheggiata in attesa
  hardware, non bloccante — nessun agente dedicato, gestita da subagent-driven-development generico.
- Guida funzionale (cosa fa ogni fase per l'utente finale): [../../docs/USER_GUIDE.md](../../docs/USER_GUIDE.md)
