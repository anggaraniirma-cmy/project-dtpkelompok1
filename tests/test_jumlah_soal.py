"""Uji pilihan jumlah soal (5 / 7 / 10) di halaman pengunjung.

Yang diuji:
  * endpoint /api/info/jumlah-soal mengumumkan pilihan yang sama dengan config;
  * permintaan 5/7/10 dihormati (total_soal sesuai, selama bank soal cukup);
  * bank soal lebih sedikit dari permintaan TIDAK error, tetapi dilaporkan
    lewat `permintaan_soal` (diminta / dipakai / kurang);
  * nilai di luar jangkauan tetap ditolak validasi (1..20);
  * berlaku juga di mode battle.
"""
from __future__ import annotations

import os
import tempfile

import pytest

_tmpdir = tempfile.mkdtemp(prefix="skomda_jumlah_")
os.environ.setdefault("SKOMDA_DB", os.path.join(_tmpdir, "jumlah.db"))
os.environ.setdefault("SKOMDA_SECRET", "test-secret-jumlah-soal-1234567890")

from fastapi.testclient import TestClient  # noqa: E402

from app import config, database  # noqa: E402
from app.main import app  # noqa: E402

JUMLAH_SOAL_BANK = 12


@pytest.fixture(scope="module")
def client():
    database.init_db()
    # Pastikan bank soal cukup untuk menguji 5/7/10.
    with database.get_conn() as conn:
        ada = conn.execute("SELECT COUNT(*) n FROM pertanyaan WHERE aktif=1").fetchone()["n"]
        for i in range(JUMLAH_SOAL_BANK - ada):
            conn.execute(
                "INSERT INTO pertanyaan (pertanyaan, pilihan_a, pilihan_b, pilihan_c,"
                " pilihan_d, jawaban, kategori, durasi, aktif, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,1,?,?)",
                (f"Soal uji jumlah {i}", "A1", "B1", "C1", "D1", "A", "Uji", 30,
                 database.now_iso(), database.now_iso()),
            )
    with TestClient(app) as c:
        yield c


def test_pilihan_diumumkan_dari_backend(client):
    d = client.get("/api/info/jumlah-soal").json()
    assert d["pilihan"] == list(config.JUMLAH_SOAL_PILIHAN) == [5, 7, 10]
    assert isinstance(d["default"], int)
    assert d["tersedia"] >= JUMLAH_SOAL_BANK


def test_info_utama_juga_memuat_pilihan(client):
    d = client.get("/api/info").json()
    assert d["jumlah_soal"]["pilihan"] == [5, 7, 10]


@pytest.mark.parametrize("n", [5, 7, 10])
def test_permintaan_jumlah_soal_dihormati(client, n):
    st = client.post("/api/game/start", json={"jumlah_soal": n}).json()
    assert st["total_soal"] == n
    assert st["permintaan_soal"] == {"diminta": n, "dipakai": n, "kurang": 0}


@pytest.mark.parametrize("n", [5, 7, 10])
def test_permintaan_jumlah_soal_battle(client, n):
    st = client.post("/api/battle/start", json={"jumlah_soal": n}).json()
    assert st["total_soal"] == n
    assert st["permintaan_soal"]["kurang"] == 0
    client.post("/api/battle/reset")


def test_bank_soal_kurang_tidak_error_tapi_dilaporkan(client):
    """Minta 10 padahal hanya 3 aktif: pakai 3, laporkan kekurangannya."""
    with database.get_conn() as conn:
        conn.execute("UPDATE pertanyaan SET aktif = 0")
        ids = [r["id"] for r in conn.execute("SELECT id FROM pertanyaan LIMIT 3")]
        conn.execute(
            f"UPDATE pertanyaan SET aktif = 1 WHERE id IN ({','.join('?' * len(ids))})",
            ids,
        )
    try:
        st = client.post("/api/game/start", json={"jumlah_soal": 10}).json()
        assert st["total_soal"] == 3
        assert st["permintaan_soal"] == {"diminta": 10, "dipakai": 3, "kurang": 7}
    finally:
        with database.get_conn() as conn:
            conn.execute("UPDATE pertanyaan SET aktif = 1")


def test_tanpa_jumlah_soal_pakai_pengaturan_panitia(client):
    st = client.post("/api/game/start", json={}).json()
    default = int(database.get_pengaturan()["jumlah_soal"])
    assert st["permintaan_soal"]["diminta"] == default


def test_nilai_di_luar_batas_ditolak(client):
    assert client.post("/api/game/start", json={"jumlah_soal": 0}).status_code == 422
    assert client.post("/api/game/start", json={"jumlah_soal": 21}).status_code == 422
    assert client.post("/api/battle/start", json={"jumlah_soal": 99}).status_code == 422


def test_tidak_ada_soal_aktif_tetap_error_jelas(client):
    with database.get_conn() as conn:
        conn.execute("UPDATE pertanyaan SET aktif = 0")
    try:
        r = client.post("/api/game/start", json={"jumlah_soal": 5})
        assert r.status_code == 400
        assert "pertanyaan aktif" in r.json()["detail"].lower()
    finally:
        with database.get_conn() as conn:
            conn.execute("UPDATE pertanyaan SET aktif = 1")
