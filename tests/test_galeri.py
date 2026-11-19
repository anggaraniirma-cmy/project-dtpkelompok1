"""Uji galeri dokumentasi foto: unggah pengunjung + akses panitia.

Semua berjalan tanpa kamera: PNG dibuat langsung di memori.
"""
from __future__ import annotations

import io
import os
import random
import tempfile
import zlib

import pytest

_tmp = tempfile.mkdtemp(prefix="skomda_galeri_")
os.environ["SKOMDA_DB"] = os.path.join(_tmp, "galeri.db")
os.environ["SKOMDA_SECRET"] = "test-secret-galeri-0123456789abcdef"
os.environ["SKOMDA_FOTO_DIR"] = os.path.join(_tmp, "foto")
os.environ.setdefault("SKOMDA_ADMIN_PASS", "skomda2026")

from fastapi.testclient import TestClient  # noqa: E402

from app import config, galeri  # noqa: E402
from app.main import app  # noqa: E402

ADMIN = {"username": "admin", "password": "skomda2026"}


def png_bytes(w: int = 8, h: int = 8, noisy: bool = False) -> bytes:
    """PNG minimal yang sah (tanpa Pillow).

    `noisy=True` mengisi piksel acak sehingga ukurannya realistis seperti foto
    kamera (berguna untuk menguji thumbnail).
    """
    if noisy:
        rnd = random.Random(1234)
        raw = b"".join(
            b"\x00" + bytes(rnd.randrange(256) for _ in range(w * 3))
            for _ in range(h)
        )
    else:
        raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (len(data).to_bytes(4, "big") + tag + data
                + zlib.crc32(tag + data).to_bytes(4, "big"))

    ihdr = (w.to_bytes(4, "big") + h.to_bytes(4, "big")
            + bytes([8, 2, 0, 0, 0]))          # 8-bit RGB
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth(client):
    r = client.post("/api/auth/login", json=ADMIN)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _unggah(client, **extra):
    data = {"mode": "battle", "pemain_1": "Rina", "pemain_2": "Budi",
            "skor_1": "42", "skor_2": "30", "pemenang": "Rina"}
    data.update(extra)
    return client.post(
        "/api/galeri/foto",
        files={"file": ("foto.png", png_bytes(), "image/png")},
        data=data,
    )


# ------------------------------------------------------------------ publik
def test_pengunjung_bisa_kirim_foto(client):
    r = _unggah(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["nama_file"].endswith(".png")
    # nama file dibuat server, bukan memakai nama kiriman klien
    assert "foto.png" != body["nama_file"]
    assert body["mode"] == "battle"


def test_pengunjung_tidak_bisa_melihat_galeri(client):
    """Endpoint baca harus 401 tanpa token panitia."""
    assert client.get("/api/admin/galeri").status_code == 401
    r = _unggah(client).json()
    assert client.get(f"/api/admin/galeri/{r['nama_file']}").status_code == 401
    assert client.delete(f"/api/admin/galeri/{r['id']}").status_code == 401


def test_tolak_berkas_bukan_gambar(client):
    r = client.post("/api/galeri/foto",
                    files={"file": ("evil.png", b"<script>alert(1)</script>", "image/png")})
    assert r.status_code == 400
    assert "png" in r.json()["detail"].lower() or "jpeg" in r.json()["detail"].lower()


def test_tolak_berkas_kosong(client):
    r = client.post("/api/galeri/foto", files={"file": ("a.png", b"", "image/png")})
    assert r.status_code == 400


def test_tolak_ukuran_berlebihan(client, monkeypatch):
    png = png_bytes()                       # ukuran yang sama dengan _unggah()
    monkeypatch.setattr(config, "FOTO_MAX_BYTES", max(10, len(png) - 1))
    r = _unggah(client)
    assert r.status_code in (400, 413), r.text
    monkeypatch.undo()


def test_tolak_dimensi_raksasa(client, monkeypatch):
    monkeypatch.setattr(galeri, "MAKS_DIMENSI", 10)
    r = client.post("/api/galeri/foto",
                    files={"file": ("big.png", png_bytes(64, 64), "image/png")})
    assert r.status_code == 400
    assert "dimensi" in r.json()["detail"].lower()
    monkeypatch.undo()


def test_magic_bytes_bukan_nama_file(client):
    """Berkas .png yang isinya JPEG harus diterima sebagai JPEG."""
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"
    r = client.post("/api/galeri/foto",
                    files={"file": ("palsu.png", jpeg, "image/png")})
    assert r.status_code == 201, r.text
    assert r.json()["nama_file"].endswith(".jpg")


# ------------------------------------------------------------------ panitia
def test_panitia_bisa_melihat_daftar(client, auth):
    _unggah(client)
    r = client.get("/api/admin/galeri?limit=50", headers=auth)
    assert r.status_code == 200
    d = r.json()
    assert d["total"] >= 1
    item = d["items"][0]
    for key in ("id", "nama_file", "mode", "created_at", "ukuran"):
        assert key in item
    # metadata tidak boleh membawa isi berkas
    assert "data" not in item


def test_filter_mode(client, auth):
    _unggah(client, mode="single")
    battle = client.get("/api/admin/galeri?mode=battle", headers=auth).json()
    single = client.get("/api/admin/galeri?mode=single", headers=auth).json()
    assert all(i["mode"] == "battle" for i in battle["items"])
    assert all(i["mode"] == "single" for i in single["items"])


def test_panitia_bisa_unduh_foto(client, auth):
    nama = _unggah(client).json()["nama_file"]
    r = client.get(f"/api/admin/galeri/{nama}", headers=auth)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_nama_file_tidak_sah_ditolak(client, auth):
    for jahat in ("../../etc/passwd", "..%2fconfig.py", "abc.png", "x" * 200 + ".png"):
        r = client.get(f"/api/admin/galeri/{jahat}", headers=auth)
        assert r.status_code == 404, jahat


def test_pratinjau_lewat_query_token(client, auth):
    """Tag <img> tidak bisa mengirim header, jadi ?token= harus diterima."""
    nama = _unggah(client).json()["nama_file"]
    token = auth["Authorization"].split(" ", 1)[1]
    r = client.get(f"/api/admin/galeri/{nama}?token={token}")
    assert r.status_code == 200
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_thumbnail_lebih_kecil_dari_asli(client, auth):
    r = client.post(
        "/api/galeri/foto",
        files={"file": ("foto.png", png_bytes(400, 300, noisy=True), "image/png")},
        data={"mode": "single"},
    )
    nama = r.json()["nama_file"]
    asli = client.get(f"/api/admin/galeri/{nama}", headers=auth).content
    kecil = client.get(f"/api/admin/galeri/{nama}?thumb=1", headers=auth).content
    assert kecil[:2] == b"\xff\xd8"     # JPEG
    assert len(kecil) < len(asli)


def test_query_token_palsu_ditolak(client):
    nama = _unggah(client).json()["nama_file"]
    assert client.get(f"/api/admin/galeri/{nama}?token=palsu").status_code == 401


def test_panitia_bisa_hapus(client, auth):
    body = _unggah(client).json()
    assert client.delete(f"/api/admin/galeri/{body['id']}", headers=auth).status_code == 200
    assert client.get(f"/api/admin/galeri/{body['nama_file']}", headers=auth).status_code == 404
    assert client.delete(f"/api/admin/galeri/{body['id']}", headers=auth).status_code == 404


def test_file_benar_benar_terhapus_dari_disk(client, auth):
    body = _unggah(client).json()
    path = config.FOTO_DIR / body["nama_file"]
    assert path.exists()
    client.delete(f"/api/admin/galeri/{body['id']}", headers=auth)
    assert not path.exists()


def test_pemangkasan_menjaga_batas(client, monkeypatch):
    monkeypatch.setattr(galeri, "MAKS_FOTO", 3)
    for _ in range(5):
        _unggah(client)
    d = galeri.daftar(limit=100)
    assert d["total"] <= 3
    monkeypatch.undo()


def test_unggah_bisa_dimatikan(client, monkeypatch):
    monkeypatch.setenv("SKOMDA_ALLOW_FOTO_UPLOAD", "0")
    r = _unggah(client)
    assert r.status_code == 403
    monkeypatch.undo()


def test_metadata_pemain_tersimpan(client, auth):
    body = _unggah(client).json()
    items = client.get("/api/admin/galeri?limit=5", headers=auth).json()["items"]
    row = next(i for i in items if i["id"] == body["id"])
    assert row["pemain_1"] == "Rina"
    assert row["pemain_2"] == "Budi"
    assert row["skor_1"] == 42
    assert row["skor_2"] == 30
    assert row["pemenang"] == "Rina"
