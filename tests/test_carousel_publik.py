"""Uji carousel promosi hero: persetujuan publikasi & batas akses publik.

Fokus:
  * foto baru TIDAK otomatis tampil di publik (default publik = 0);
  * endpoint publik maksimal 5, terbaru lebih dulu, tanpa token admin;
  * berkas publik hanya bisa diambil bila statusnya publik;
  * nama berkas tidak sah / bukan foto publik -> 404 (bukan daftar galeri);
  * endpoint admin tetap menolak tanpa token.
"""
from __future__ import annotations

import os
import tempfile

import pytest

_tmpdir = tempfile.mkdtemp(prefix="skomda_carousel_")
os.environ.setdefault("SKOMDA_DB", os.path.join(_tmpdir, "carousel.db"))
os.environ.setdefault("SKOMDA_SECRET", "test-secret-carousel")

from fastapi.testclient import TestClient  # noqa: E402

from app import config, database, galeri  # noqa: E402
from app.main import app  # noqa: E402

# PNG 1x1 piksel (valid magic bytes) — cukup untuk menguji jalur berkas.
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


@pytest.fixture(scope="module")
def client():
    database.init_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def token(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "skomda2026"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture()
def direksi_foto(tmp_path, monkeypatch):
    """Folder foto sementara supaya uji tidak menyentuh data asli."""
    monkeypatch.setattr(config, "FOTO_DIR", tmp_path / "foto")
    monkeypatch.setattr(galeri, "_pangkas", lambda folder: None)
    return tmp_path / "foto"


def _unggah(client, nama_hint="uji") -> dict:
    r = client.post(
        "/api/galeri/foto",
        files={"file": (f"{nama_hint}.png", PNG_1PX, "image/png")},
        data={"mode": "single", "pemain_1": "Player 1", "skor_1": "10"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_foto_baru_belum_publik(client, token, direksi_foto):
    hasil = _unggah(client, "belum-publik")
    # Status default harus 0 -> tidak muncul di endpoint publik.
    daftar = client.get("/api/galeri/publik").json()
    assert all(it["nama_file"] != hasil["nama_file"] for it in daftar["items"])

    # Dan admin melihat kolom publik = 0 pada metadata.
    rows = client.get("/api/admin/galeri", headers={"Authorization": f"Bearer {token}"}).json()
    baris = next(i for i in rows["items"] if i["nama_file"] == hasil["nama_file"])
    assert baris["publik"] == 0


def test_setujui_lalu_tampil_di_publik(client, token, direksi_foto):
    hasil = _unggah(client, "disetujui")
    r = client.put(
        f"/api/admin/galeri/{hasil['id']}/publik",
        json={"publik": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["publik"] is True

    daftar = client.get("/api/galeri/publik").json()
    nama = {it["nama_file"] for it in daftar["items"]}
    assert hasil["nama_file"] in nama

    # Berkas publik bisa diambil tanpa token...
    img = client.get(f"/api/galeri/publik/{hasil['nama_file']}")
    assert img.status_code == 200
    assert img.headers["content-type"].startswith("image/")

    # ...tetapi endpoint daftar galeri penuh tetap wajib token.
    assert client.get("/api/admin/galeri").status_code == 401


def test_tarik_persetujuan_menghilangkan_dari_publik(client, token, direksi_foto):
    hasil = _unggah(client, "ditarik")
    client.put(f"/api/admin/galeri/{hasil['id']}/publik", json={"publik": True},
               headers={"Authorization": f"Bearer {token}"})
    client.put(f"/api/admin/galeri/{hasil['id']}/publik", json={"publik": False},
               headers={"Authorization": f"Bearer {token}"})

    daftar = client.get("/api/galeri/publik").json()
    assert all(it["nama_file"] != hasil["nama_file"] for it in daftar["items"])
    assert client.get(f"/api/galeri/publik/{hasil['nama_file']}").status_code == 404


def test_maksimal_lima_dan_terbaru_dulu(client, token, direksi_foto):
    for i in range(7):
        h = _unggah(client, f"urut-{i}")
        client.put(f"/api/admin/galeri/{h['id']}/publik", json={"publik": True},
                   headers={"Authorization": f"Bearer {token}"})

    daftar = client.get("/api/galeri/publik").json()
    assert daftar["maks"] == 5
    assert 1 <= len(daftar["items"]) <= 5
    tanggal = [it["created_at"] for it in daftar["items"]]
    assert tanggal == sorted(tanggal, reverse=True), "foto terbaru harus lebih dulu"


def test_tidak_mengekspos_seluruh_galeri_atau_data_sesi(client, direksi_foto):
    daftar = client.get("/api/galeri/publik").json()
    for item in daftar["items"]:
        # Hanya field yang aman; tidak ada sesi_id/nama pemain/skor.
        assert set(item) == {"id", "nama_file", "mode", "created_at", "publik_at",
                             "thumb_url", "url"}


def test_nama_berkas_tidak_sah_ditolak(client):
    for nama in ("../../quiz.db", "quiz.db", "bukan-foto.txt", "..%2f..%2fapp.py"):
        r = client.get(f"/api/galeri/publik/{nama}")
        assert r.status_code == 404, f"{nama} seharusnya 404, dapat {r.status_code}"


def test_set_publik_wajib_token_dan_validasi_id(client, direksi_foto):
    h = _unggah(client, "wajib-token")
    assert client.put(f"/api/admin/galeri/{h['id']}/publik",
                      json={"publik": True}).status_code == 401

    token = client.post("/api/auth/login",
                        json={"username": "admin", "password": "skomda2026"}
                        ).json()["access_token"]
    r = client.put("/api/admin/galeri/999999/publik", json={"publik": True},
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


def test_daftar_publik_tidak_menampilkan_berkas_hilang(client, token, direksi_foto):
    h = _unggah(client, "hilang")
    client.put(f"/api/admin/galeri/{h['id']}/publik", json={"publik": True},
               headers={"Authorization": f"Bearer {token}"})
    # Hapus berkas dari disk, baris DB tetap ada.
    (config.FOTO_DIR / h["nama_file"]).unlink()

    daftar = client.get("/api/galeri/publik").json()
    assert all(it["nama_file"] != h["nama_file"] for it in daftar["items"])
    assert client.get(f"/api/galeri/publik/{h['nama_file']}").status_code == 404
