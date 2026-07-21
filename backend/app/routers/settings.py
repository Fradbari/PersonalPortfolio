"""`/settings` — GET/PUT impostazioni utente (F9, ADR-0027).

Router HTTP puro: nessuna logica di whitelist/blacklist/precedenza qui, tutto
delegato ad `app.services.settings` (T2, gia' testato). Questo modulo si limita
a serializzare `get_effective`/`set_values` in JSON e a mappare gli errori su
status HTTP.

Anti-enumerazione della blacklist (ADR-0027, rettifica 2026-07-21 p.8, punto
(c) della spec di dettaglio Blocco A): su `PUT`, una chiave blacklistata e una
chiave del tutto inesistente devono produrre lo **stesso** messaggio 400 —
altrimenti un messaggio diverso permetterebbe di scoprire quali chiavi sono
blacklistate per tentativi. Per questo la validazione qui sotto controlla solo
`key not in WHITELIST` (che e' vero in entrambi i casi, dato che le chiavi di
`BLACKLIST` non compaiono mai in `WHITELIST`) e solleva un messaggio fisso,
mai il messaggio di `ValueError` del service layer (che include il nome della
chiave e quindi differirebbe da una chiamata all'altra).

Nessun valore di `BLACKLIST` esce mai da `GET /settings`: `secrets_status`
riporta solo `{"configured": bool(...)}` per nome (ADR-0027 p.6).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.db import get_session
from app.services.settings import BLACKLIST, WHITELIST, get_effective, set_values

router = APIRouter(tags=["settings"])

_INVALID_KEY_MESSAGE = "Una o più chiavi non sono impostazioni valide."


def _settings_payload(session: Session) -> dict[str, Any]:
    settings_list = []
    for key, spec in WHITELIST.items():
        value, source = get_effective(key, session=session)
        settings_list.append(
            {"key": key, "value": value, "source": source, "applies_when": spec["applies_when"]}
        )

    # Solo bool(configured), mai il valore reale (ADR-0027 p.6) — la chiave e'
    # sempre presente su app.config.settings (attributo pydantic dichiarato).
    secrets_status = {
        name: {"configured": bool(getattr(app_settings, name, None))} for name in BLACKLIST
    }

    return {"settings": settings_list, "secrets_status": secrets_status}


@router.get("/settings")
def get_settings(session: Session = Depends(get_session)):
    return _settings_payload(session)


@router.put("/settings")
def update_settings(body: dict[str, Any] = Body(...), session: Session = Depends(get_session)):
    if any(key not in WHITELIST for key in body):
        # Messaggio fisso e identico indipendentemente da QUALE chiave e' illegale
        # (blacklist o sconosciuta) — vedi nota anti-enumerazione in cima al file.
        raise HTTPException(status_code=400, detail=_INVALID_KEY_MESSAGE)

    try:
        set_values(session, body)
    except ValueError as exc:
        # Difensivo: a questo punto le chiavi sono gia' validate sopra, quindi un
        # ValueError qui puo' venire solo da una coercizione di tipo fallita
        # (es. valore non convertibile a int), non da una chiave illegale.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _settings_payload(session)
