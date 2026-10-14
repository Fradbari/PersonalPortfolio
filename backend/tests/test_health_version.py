"""Ancora `version`/`phase` al Blocco B (T16). Un bump dimenticato fa fallire questo
test invece di passare inosservato in produzione."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_phase_13():
    # Convenzione: `phase` = numero dell'ultima fase del branch corrente al merge, non il
    # massimo globale. Il Blocco B porta phase da "9" a "13" perche' F11/F12/F13 completano
    # tutte in questo branch. Il salto da 9 a 13 e' atteso: F10 appartiene al Blocco C e non
    # e' stata completata qui. Chiudendo il Blocco C per intero il valore diventera' "14". Se
    # Blocco C chiudesse solo F10, phase resterebbe "13" perche' "14" (F14) non e' ancora
    # mergiata.
    client = TestClient(app)

    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["phase"] == "13"


def test_app_version_matches_phase():
    assert app.version == "0.1.0-phase13"
