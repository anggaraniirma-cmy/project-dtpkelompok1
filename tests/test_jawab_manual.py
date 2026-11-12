"""Uji jalur jawab manual (cadangan saat kamera bermasalah) + saklar env-nya."""
from __future__ import annotations

import pytest


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_jawab_manual_aktif_secara_default(client):
    h = client.get("/api/health").json()
    assert h["jawaban_manual"] is True


def test_jawab_manual_bisa_jawab_soal(client):
    client.post("/api/game/reset")
    st = client.post("/api/game/start", json={"jumlah_soal": 2}).json()
    assert st["aktif"] is True
    r = client.post("/api/game/answer", json={"pilihan": "A"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["benar"] in (True, False)
    assert body["jawaban"] == "A"


def test_jawab_manual_dimatikan_menolak_dengan_403(client, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "ALLOW_MANUAL_ANSWER", False)
    client.post("/api/game/reset")
    client.post("/api/game/start", json={"jumlah_soal": 2})
    r = client.post("/api/game/answer", json={"pilihan": "A"})
    assert r.status_code == 403
    assert "manual" in r.json()["detail"].lower()
    # health juga melaporkan status ini supaya UI bisa menyembunyikan tombol
    assert client.get("/api/health").json()["jawaban_manual"] is False
