"""Ancora `version`/`phase` al Blocco C (T10). Un bump dimenticato fa fallire questo
test invece di passare inosservato in produzione."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_phase_14():
    # Convenzione: `phase` = numero dell'ultima fase del branch corrente al merge, non il
    # massimo globale. Il Blocco B ha portato phase da "9" a "13" perche' F11/F12/F13
    # completavano tutte in quel branch. Il Blocco C chiude F10 **e** F14 per intero: il
    # valore diventa "14".
    client = TestClient(app)

    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["phase"] == "14"


def test_app_version_matches_phase():
    assert app.version == "0.1.0-phase14"
