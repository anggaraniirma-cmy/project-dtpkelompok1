"""Uji penegakan waktu server-side: jawaban terlambat ditolak, sesi tidak menggantung.

Fokus: keputusan waktu diambil dari jam server (monotonic), bukan dari timer
JavaScript pengunjung. Semua waktu dipercepat dengan memundurkan `mulai` soal.
"""
from __future__ import annotations

import time

import pytest

from app.routers.game import engine   # instance GameEngine (satu-satunya)


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c


def _mundurkan_waktu(detik: float) -> None:
    """Buat soal aktif seolah sudah berjalan `detik` detik."""
    sesi = engine.sesi
    assert sesi is not None and sesi.soal is not None
    sesi.soal.mulai = time.monotonic() - detik


def test_jawaban_setelah_waktu_habis_ditolak(client):
    client.post("/api/game/reset")
    st = client.post("/api/game/start", json={"jumlah_soal": 2}).json()
    durasi = st["soal"]["durasi"]

    _mundurkan_waktu(durasi + 1)

    r = client.post("/api/game/answer", json={"pilihan": "A"})
    assert r.status_code == 400
    assert "habis" in r.json()["detail"].lower()

    # dan tercatat sebagai timeout, bukan jawaban
    state = client.get("/api/game/state").json()
    assert state["skor"] == 0


def test_jawaban_tepat_sebelum_habis_tetap_diterima(client):
    client.post("/api/game/reset")
    st = client.post("/api/game/start", json={"jumlah_soal": 2}).json()
    durasi = st["soal"]["durasi"]

    _mundurkan_waktu(durasi - 1.0)   # masih sisa ~1 detik

    r = client.post("/api/game/answer", json={"pilihan": "A"})
    assert r.status_code == 200, r.text


def test_tick_menandai_timeout_dan_memajukan_soal(client):
    client.post("/api/game/reset")
    st = client.post("/api/game/start", json={"jumlah_soal": 3}).json()
    durasi = st["soal"]["durasi"]

    _mundurkan_waktu(durasi + 1)

    ev = engine.tick()
    assert ev is not None and ev["event"] == "timeout"

    # soal belum maju saat itu juga (ada jeda untuk feedback)
    assert engine.sesi.indeks == 0

    # setelah jeda lewat, tick memajukan soal
    engine._pending_advance_at = time.monotonic() - 0.01
    ev2 = engine.tick()
    assert ev2 is not None and ev2["event"] == "berjalan"
    assert ev2["state"]["nomor"] == 2


def test_tick_menyelesaikan_permainan_tanpa_browser(client):
    """Sesi harus selesai sendiri walau browser tidak pernah memanggil /next."""
    client.post("/api/game/reset")
    client.post("/api/game/start", json={"jumlah_soal": 2})

    events = []
    for _ in range(6):   # cukup iterasi untuk kedua soal
        _mundurkan_waktu(999)
        engine._pending_advance_at = time.monotonic() - 0.01
        ev = engine.tick()
        if ev:
            events.append(ev["event"])
        if engine.sesi and engine.sesi.status != "berjalan":
            break

    # Sesi yang ditinggal jauh melewati batas ditutup (timeout + dibatalkan),
    # bukan menggantung sebagai "berjalan".
    assert engine.sesi is not None
    assert engine.sesi.status != "berjalan"
    assert "selesai" in events
    hasil = engine.result()
    assert hasil["benar"] == 0            # semua kena timeout
    assert hasil["total_soal"] == 2


def test_sesi_ditinggal_dibatalkan_bukan_menggantung(client):
    """Pengunjung pergi > SESI_TELANTAR_DETIK: sesi ditutup, tidak menggantung."""
    from app import config, database
    client.post("/api/game/reset")
    client.post("/api/game/start", json={"jumlah_soal": 3})
    sesi_id = engine.sesi.id

    durasi = engine.sesi.soal.durasi
    _mundurkan_waktu(durasi + config.SESI_TELANTAR_DETIK + 5)
    ev = engine.tick()
    assert ev is not None and ev["event"] == "selesai"
    assert ev.get("dibatalkan") is True
    assert engine.sesi.status == "selesai"

    with database.get_conn() as conn:
        row = conn.execute(
            "SELECT status FROM sesi_permainan WHERE id=?", (sesi_id,)
        ).fetchone()
    assert row["status"] == "dibatalkan"
    # hanya soal yang sempat habis yang dicatat, bukan semua soal
    assert len(engine.result()["riwayat"]) == 1


def test_next_diabaikan_bila_soal_belum_dijawab(client):
    """Mencegah soal terlewat hanya karena /next terpanggil dua kali."""
    client.post("/api/game/reset")
    client.post("/api/game/start", json={"jumlah_soal": 3})

    r = client.post("/api/game/next")
    assert r.status_code == 200
    assert r.json().get("diabaikan") is True
    assert r.json()["state"]["nomor"] == 1     # tetap di soal pertama

    client.post("/api/game/answer", json={"pilihan": "A"})
    r2 = client.post("/api/game/next")
    assert r2.json()["state"]["nomor"] == 2


def test_next_setelah_selesai_mengembalikan_hasil(client):
    client.post("/api/game/reset")
    client.post("/api/game/start", json={"jumlah_soal": 1})
    client.post("/api/game/answer", json={"pilihan": "A"})
    r = client.post("/api/game/next")
    assert r.json()["lanjut"] == "selesai"

    # panggilan kedua tidak error 400, tetap memberi hasil
    r2 = client.post("/api/game/next")
    assert r2.status_code == 200
    assert r2.json()["lanjut"] == "selesai"
    assert r2.json()["hasil"]["total_soal"] == 1


def test_state_endpoint_ikut_menjalankan_tick(client):
    client.post("/api/game/reset")
    client.post("/api/game/start", json={"jumlah_soal": 2})
    durasi = engine.sesi.soal.durasi
    _mundurkan_waktu(durasi + 1)   # baru saja lewat, klien masih ada
    data = client.get("/api/game/state").json()
    assert data.get("game_event", {}).get("event") == "timeout"
