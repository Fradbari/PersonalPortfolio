"""Registro whitelist/blacklist e accessor per le impostazioni utente (F9, ADR-0027).

`settings` (la tabella, `app.models.Settings`) e' key/value: il tipo si applica qui,
in lettura, non nello schema. Questo modulo non conosce l'HTTP: router e UI
(`GET`/`PUT /settings`, T3) e riaggancio dei consumer esistenti (`import_min_year`,
`backup_retention`, `backup_on_startup`, T4/T5) sono fuori scope.

Precedenza di lettura (`get_effective`): DB > env > default (ADR-0027 p.3). Le tre
chiavi senza equivalente in `app.config` (`theme`, `metabase_url`,
`ai_history_max_turns`) usano un default letterale; le altre tre usano il valore
gia' esistente su `app.config.settings` come bootstrap env.

Nota: `ai_history_max_turns` entra in whitelist ora ma non ha ancora nessun
consumatore — verra' letto dall'adapter AI solo con la persistenza chat di F14.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.db import SessionLocal
from app.models import Settings

WHITELIST: dict[str, dict[str, Any]] = {
    "theme": {
        "type": str,
        "default": "system",
        "env_attr": None,
        "applies_when": "immediato",
    },
    "metabase_url": {
        "type": str,
        "default": "http://localhost:3000",
        "env_attr": None,
        "applies_when": "immediato (solo destinazione link)",
    },
    "ai_history_max_turns": {
        "type": int,
        "default": 6,
        "env_attr": None,
        "applies_when": "immediato, dalla domanda successiva",
    },
    "import_min_year": {
        "type": int,
        "default": None,  # inutilizzato: env_attr e' sempre valorizzato da app.config
        "env_attr": "import_min_year",
        "applies_when": "immediato, dal prossimo import",
    },
    "backup_retention": {
        "type": int,
        "default": None,
        "env_attr": "backup_retention",
        "applies_when": "immediato, dal prossimo backup",
    },
    "backup_on_startup": {
        "type": bool,
        "default": None,
        "env_attr": "backup_on_startup",
        "applies_when": "solo al boot successivo",
    },
}

BLACKLIST: frozenset[str] = frozenset(
    {"ai_api_key", "google_sa_key_path", "gdrive_backup_folder_id"}
)


def _coerce(value: Any, type_: type) -> Any:
    """Applica il tipo dichiarato in whitelist a un valore letto da stringa (DB/env)
    o gia' tipizzato (env pydantic). `bool("false")` in Python vale `True`: per questo
    il caso bool va gestito esplicitamente invece di chiamare `type_(value)`."""
    if value is None:
        return None
    if type_ is bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    return type_(value)


def _to_storage_string(value: Any) -> str | None:
    """Inverso di `_coerce` per bool: rappresentazione canonica "true"/"false",
    non lo str() di Python ("True"/"False"), per restare coerente con quanto
    `_coerce` sa poi rileggere da DB."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def get_effective(key: str, session: Session | None = None) -> tuple[Any, str]:
    """Valore effettivo di `key` e sua provenienza (`"db"` | `"env"` | `"default"`).

    Con `session=None` apre una `SessionLocal()` propria e la chiude in `finally`:
    serve al thread di avvio e a un futuro dry-run, che non hanno una sessione da
    passare (T4/T5).
    """
    if key not in WHITELIST:
        raise ValueError(f"chiave non in whitelist: {key}")

    spec = WHITELIST[key]
    type_ = spec["type"]

    owns_session = session is None
    if owns_session:
        session = SessionLocal()
    try:
        row = session.get(Settings, key)
        if row is not None and row.value is not None:
            return _coerce(row.value, type_), "db"

        env_attr = spec["env_attr"]
        if env_attr is not None:
            return _coerce(getattr(app_settings, env_attr), type_), "env"

        return _coerce(spec["default"], type_), "default"
    finally:
        if owns_session:
            session.close()


def set_values(session: Session, mapping: dict[str, Any]) -> None:
    """Scrive `mapping` (solo chiavi whitelist) in una singola transazione: se una
    sola chiave non e' whitelist, non scrive nulla."""
    for key in mapping:
        if key not in WHITELIST:
            raise ValueError(f"chiave non in whitelist: {key}")

    try:
        now = datetime.utcnow()
        for key, value in mapping.items():
            type_ = WHITELIST[key]["type"]
            str_value = _to_storage_string(_coerce(value, type_))
            row = session.get(Settings, key)
            if row is None:
                session.add(Settings(key=key, value=str_value, updated_at=now))
            else:
                row.value = str_value
                row.updated_at = now
        session.commit()
    except Exception:
        session.rollback()
        raise
