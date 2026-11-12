"""Uji pengaturan permainan + ganti password admin (panel panitia)."""
from __future__ import annotations

import os
import tempfile

import pytest

# Jalankan dengan database sementara. setdefault (bukan hard-set) supaya bila
# seluruh suite dijalankan, test_api yang sudah memilih DB tetap dipakai.
os.environ.setdefault("SKOMDA_DB", os.path.join(tempfile.mkdtemp(prefix="skomda_peng_"), "test.db"))
os.environ.setdefault("SKOMDA_SECRET", "test-secret-key-for-pengaturan-suite")

from app import database  # noqa: E402

ADMIN = {"username": "admin", "password": "skomda2026"}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth(client):
    r = client.post("/api/auth/login", json=ADMIN)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ------------------------------------------------------------- pengaturan
def test_pengaturan_butuh_token(client):
    assert client.get("/api/admin/pengaturan").status_code == 401
    assert client.put("/api/admin/pengaturan", json={"jumlah_soal": 4}).status_code == 401


def test_pengaturan_default_terisi(client, auth):
    r = client.get("/api/admin/pengaturan", headers=auth)
    assert r.status_code == 200
    d = r.json()
    assert set(d["nilai"]) == {"jumlah_soal", "durasi_default", "hold_detik", "cooldown_detik"}
    assert d["batas"]["jumlah_soal"] == {"min": 1, "max": 20}
    assert isinstance(d["nilai"]["hold_detik"], float)
    assert isinstance(d["nilai"]["jumlah_soal"], int)


def test_pengaturan_tersimpan_permanen(client, auth):
    r = client.put("/api/admin/pengaturan", headers=auth, json={"jumlah_soal": 7})
    assert r.status_code == 200, r.text
    assert r.json()["nilai"]["jumlah_soal"] == 7

    # dibaca ulang dari database (bukan cache memori)
    assert database.get_pengaturan()["jumlah_soal"] == 7

    # dan benar-benar dipakai saat permainan dimulai
    client.post("/api/game/reset")
    st = client.post("/api/game/start", json={}).json()
    assert st["total_soal"] == min(7, _jumlah_soal_aktif())
    assert st["konfigurasi"]["jumlah_soal"] == 7


def _jumlah_soal_aktif() -> int:
    with database.get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) n FROM pertanyaan WHERE aktif=1"
        ).fetchone()["n"]


def test_pengaturan_di_luar_batas_ditolak(client, auth):
    # Pydantic menolak lebih dulu (422)
    assert client.put("/api/admin/pengaturan", headers=auth,
                      json={"jumlah_soal": 99}).status_code == 422
    assert client.put("/api/admin/pengaturan", headers=auth,
                      json={"hold_detik": 0.1}).status_code == 422
    # kunci tak dikenal -> 422 karena schema menolak field ekstra? tidak:
    # field ekstra diabaikan Pydantic, jadi dipastikan nilai lama tidak berubah
    before = database.get_pengaturan()
    client.put("/api/admin/pengaturan", headers=auth, json={"tidak_ada": 5})
    assert database.get_pengaturan() == before


def test_pengaturan_kembalikan_default(client, auth):
    r = client.put("/api/admin/pengaturan", headers=auth,
                   json={"jumlah_soal": 5, "durasi_default": 30,
                         "hold_detik": 1.0, "cooldown_detik": 1.5})
    assert r.status_code == 200
    assert database.get_pengaturan()["jumlah_soal"] == 5


def test_hold_detik_mempengaruhi_stabilizer(client, auth):
    """Pengaturan hold harus benar-benar dipakai pipeline kamera."""
    from app.routers import cv as cv_router
    client.put("/api/admin/pengaturan", headers=auth, json={"hold_detik": 2.0})
    pipe = cv_router._new_pipeline()
    try:
        assert pipe.stabilizer.hold_seconds == 2.0
    finally:
        pipe.close()
    client.put("/api/admin/pengaturan", headers=auth, json={"hold_detik": 1.0})


# -------------------------------------------------------- ganti password
def test_password_butuh_token(client):
    assert client.post("/api/admin/password", json={
        "password_lama": "skomda2026", "password_baru": "rahasia123",
    }).status_code == 401


def test_password_lama_salah_ditolak(client, auth):
    r = client.post("/api/admin/password", headers=auth, json={
        "password_lama": "salah-sekali", "password_baru": "rahasia123",
    })
    assert r.status_code == 400
    assert "lama" in r.json()["detail"].lower()


def test_password_baru_lemah_ditolak(client, auth):
    # terlalu pendek
    assert client.post("/api/admin/password", headers=auth, json={
        "password_lama": "skomda2026", "password_baru": "abc1",
    }).status_code == 422
    # tanpa angka
    assert client.post("/api/admin/password", headers=auth, json={
        "password_lama": "skomda2026", "password_baru": "tanpaangka",
    }).status_code == 422
    # tanpa huruf
    assert client.post("/api/admin/password", headers=auth, json={
        "password_lama": "skomda2026", "password_baru": "12345678",
    }).status_code == 422


def test_ganti_password_berhasil_dan_login_baru(client, auth):
    r = client.post("/api/admin/password", headers=auth, json={
        "password_lama": "skomda2026", "password_baru": "skomda2027x",
    })
    assert r.status_code == 200, r.text

    # password lama tidak berlaku lagi
    assert client.post("/api/auth/login", json={
        "username": "admin", "password": "skomda2026",
    }).status_code == 401
    # password baru berlaku
    assert client.post("/api/auth/login", json={
        "username": "admin", "password": "skomda2027x",
    }).status_code == 200

    # kembalikan agar test lain tidak terpengaruh
    new_auth = {"Authorization": "Bearer " + client.post(
        "/api/auth/login", json={"username": "admin", "password": "skomda2027x"},
    ).json()["access_token"]}
    assert client.post("/api/admin/password", headers=new_auth, json={
        "password_lama": "skomda2027x", "password_baru": "skomda2026",
    }).status_code == 200
