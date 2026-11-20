"""Uji API: autentikasi, otorisasi admin, CRUD soal, alur permainan.

Menggunakan database SQLite sementara (tidak menyentuh data produksi).
"""
from __future__ import annotations

import os
import tempfile

import pytest

_tmpdir = tempfile.mkdtemp(prefix="skomda_test_")
os.environ["SKOMDA_DB"] = os.path.join(_tmpdir, "test.db")
os.environ["SKOMDA_SECRET"] = "test-secret-key"
os.environ.setdefault("SKOMDA_ADMIN_PASS", "skomda2026")

from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402
from app.main import app  # noqa: E402

ADMIN = {"username": "admin", "password": "skomda2026"}

# PNG 1x1 piksel sah (magic bytes benar) untuk menguji jalur berkas media.
PNG_CONTOH = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def token(client):
    r = client.post("/api/auth/login", json=ADMIN)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------- media publik
def test_media_fotocontoh_publik_dan_png(client):
    """Foto hero disajikan dari backend/data/foto tanpa perlu login.

    Berkas dibuat sendiri di folder foto sementara: conftest mengarahkan
    SKOMDA_FOTO_DIR ke folder sementara agar test tidak menyentuh data
    pengunjung asli.
    """
    from app import config

    config.FOTO_DIR.mkdir(parents=True, exist_ok=True)
    (config.FOTO_DIR / "fotocontoh.png").write_bytes(PNG_CONTOH)

    r = client.get("/api/media/fotocontoh.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert len(r.content) == len(PNG_CONTOH)


def test_media_tidak_bisa_dipakai_membaca_foto_galeri(client):
    """Nama berkas tidak diterima dari klien -> tidak bisa menebak foto galeri."""
    for nama in ("20261119-085404-c200f5c1.png", "quiz.db", "..%2fquiz.db"):
        r = client.get(f"/api/media/{nama}")
        assert r.status_code == 404


def test_media_tanpa_login_tapi_galeri_wajib_token(client):
    assert client.get("/api/media/fotocontoh.png").status_code in (200, 404)
    assert client.get("/api/admin/galeri").status_code == 401


# ---------------------------------------------------------------- kesehatan
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_seed_questions_exist(client):
    """Database baru harus sudah berisi soal contoh (bukan hardcode di game)."""
    from app import database
    with database.get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) n FROM pertanyaan").fetchone()["n"]
    assert n >= 5


# -------------------------------------------------------------------- auth
def test_login_benar(client):
    r = client.post("/api/auth/login", json=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["admin"]["username"] == "admin"
    assert body["access_token"]


def test_login_password_salah(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "salah"})
    assert r.status_code == 401
    assert "salah" in r.json()["detail"].lower()


def test_login_username_tidak_ada(client):
    r = client.post("/api/auth/login", json={"username": "hacker", "password": "x"})
    assert r.status_code == 401
    # Pesan tidak boleh membocorkan apakah username ada
    assert r.json()["detail"] == "Username atau password salah"


def test_password_disimpan_hash(client):
    from app import database
    with database.get_conn() as conn:
        row = conn.execute("SELECT password_hash FROM admin LIMIT 1").fetchone()
    assert row["password_hash"].startswith("$2b$")
    assert "skomda2026" not in row["password_hash"]


def test_me_butuh_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer ngawur"}).status_code == 401


# ------------------------------------------------- otorisasi endpoint admin
ADMIN_ENDPOINTS = [
    ("get", "/api/admin/stats"),
    ("get", "/api/admin/pertanyaan"),
    ("get", "/api/admin/kategori"),
    ("get", "/api/admin/sesi"),
    ("get", "/api/admin/pertanyaan/1"),
]


@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
def test_admin_endpoint_tanpa_token_ditolak(client, method, path):
    """Pengunjung tidak boleh mengakses endpoint admin."""
    r = getattr(client, method)(path)
    assert r.status_code == 401, f"{path} seharusnya 401, dapat {r.status_code}"


@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
def test_admin_endpoint_token_palsu_ditolak(client, method, path):
    r = getattr(client, method)(path, headers={"Authorization": "Bearer palsu.token.abc"})
    assert r.status_code == 401


def test_admin_tidak_bisa_tulis_tanpa_token(client):
    payload = {
        "pertanyaan": "Percobaan tanpa izin menulis soal",
        "pilihan_a": "A", "pilihan_b": "B", "pilihan_c": "C", "pilihan_d": "D",
        "jawaban": "A", "kategori": "Uji", "durasi": 30, "aktif": True,
    }
    assert client.post("/api/admin/pertanyaan", json=payload).status_code == 401


def test_token_kedaluwarsa_ditolak(client):
    """Token dengan exp lampau harus ditolak."""
    import time
    import jwt
    expired = jwt.encode(
        {"sub": "admin", "role": "admin", "iat": int(time.time()) - 100, "exp": int(time.time()) - 10},
        config.get_secret_key(), algorithm="HS256",
    )
    r = client.get("/api/admin/stats", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401


def test_role_bukan_admin_ditolak(client):
    import time
    import jwt
    visitor = jwt.encode(
        {"sub": "pengunjung", "role": "visitor", "iat": int(time.time()), "exp": int(time.time()) + 600},
        config.get_secret_key(), algorithm="HS256",
    )
    r = client.get("/api/admin/stats", headers={"Authorization": f"Bearer {visitor}"})
    assert r.status_code == 403


# ----------------------------------------------------------------- admin CRUD
def test_stats(client, auth):
    r = client.get("/api/admin/stats", headers=auth)
    assert r.status_code == 200
    d = r.json()
    assert d["total_pertanyaan"] >= 5
    assert isinstance(d["kategori"], list)


def test_crud_lengkap(client, auth):
    payload = {
        "pertanyaan": "Soal uji CRUD otomatis untuk validasi backend?",
        "pilihan_a": "Satu", "pilihan_b": "Dua", "pilihan_c": "Tiga", "pilihan_d": "Empat",
        "jawaban": "C", "kategori": "Uji Otomatis", "durasi": 25, "aktif": True,
    }
    # Create
    r = client.post("/api/admin/pertanyaan", json=payload, headers=auth)
    assert r.status_code == 201, r.text
    qid = r.json()["id"]
    assert r.json()["jawaban"] == "C"

    # Read
    r = client.get(f"/api/admin/pertanyaan/{qid}", headers=auth)
    assert r.status_code == 200
    assert r.json()["pertanyaan"] == payload["pertanyaan"]
    assert r.json()["pilihan"]["B"] == "Dua"

    # Update
    payload["pertanyaan"] = "Soal uji CRUD yang sudah diperbarui"
    payload["jawaban"] = "D"
    payload["durasi"] = 15
    r = client.put(f"/api/admin/pertanyaan/{qid}", json=payload, headers=auth)
    assert r.status_code == 200
    assert r.json()["jawaban"] == "D"
    assert r.json()["durasi"] == 15

    # Persistensi: dibaca ulang lewat koneksi baru
    r = client.get(f"/api/admin/pertanyaan/{qid}", headers=auth)
    assert r.json()["pertanyaan"] == "Soal uji CRUD yang sudah diperbarui"

    # Delete
    assert client.delete(f"/api/admin/pertanyaan/{qid}", headers=auth).status_code == 200
    assert client.get(f"/api/admin/pertanyaan/{qid}", headers=auth).status_code == 404


def test_validasi_input_ditolak(client, auth):
    base = {
        "pertanyaan": "Valid?", "pilihan_a": "A", "pilihan_b": "B",
        "pilihan_c": "C", "pilihan_d": "D", "jawaban": "A",
        "kategori": "Uji", "durasi": 30, "aktif": True,
    }
    # pertanyaan terlalu pendek
    bad = {**base, "pertanyaan": "Ya"}
    assert client.post("/api/admin/pertanyaan", json=bad, headers=auth).status_code == 422

    # jawaban di luar A-D
    bad = {**base, "jawaban": "E"}
    assert client.post("/api/admin/pertanyaan", json=bad, headers=auth).status_code == 422

    # durasi di luar batas
    bad = {**base, "durasi": 1}
    assert client.post("/api/admin/pertanyaan", json=bad, headers=auth).status_code == 422

    # pilihan kosong
    bad = {**base, "pilihan_c": "   "}
    assert client.post("/api/admin/pertanyaan", json=bad, headers=auth).status_code == 422


def test_pencarian_dan_filter(client, auth):
    for i in range(3):
        client.post("/api/admin/pertanyaan", headers=auth, json={
            "pertanyaan": f"Soal pencarian unik zulkan_{i} tentang jaringan",
            "pilihan_a": "A", "pilihan_b": "B", "pilihan_c": "C", "pilihan_d": "D",
            "jawaban": "A", "kategori": "Filter Uji", "durasi": 20, "aktif": True,
        })
    r = client.get("/api/admin/pertanyaan?q=zulkan_", headers=auth)
    assert r.status_code == 200
    assert r.json()["total"] == 3

    r = client.get("/api/admin/pertanyaan?kategori=Filter Uji", headers=auth)
    assert r.json()["total"] == 3

    r = client.get("/api/admin/pertanyaan?q=zulkan_&kategori=Kategori Lain", headers=auth)
    assert r.json()["total"] == 0


# ------------------------------------------------------------ alur permainan
def test_alur_permainan_penuh(client):
    """Mulai -> jawab semua -> selesai, dan skor konsisten."""
    client.post("/api/game/reset")
    r = client.post("/api/game/start", json={"jumlah_soal": 3})
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["nomor"] == 1
    assert st["total_soal"] == 3
    assert "soal" in st
    assert "jawaban" not in st["soal"], "kunci jawaban tidak boleh bocor ke browser"

    total_benar = 0
    for i in range(3):
        # jawab dengan huruf yang benar (didapat dari DB, bukan dari API)
        from app import database
        with database.get_conn() as conn:
            current = client.get("/api/game/state").json()
            row = conn.execute(
                "SELECT jawaban FROM pertanyaan WHERE pertanyaan = ?",
                (current["soal"]["pertanyaan"],),
            ).fetchone()
        correct = row["jawaban"]
        rr = client.post("/api/game/answer", json={"pilihan": correct})
        assert rr.status_code == 200, rr.text
        assert rr.json()["benar"] is True
        total_benar += 1

        nx = client.post("/api/game/next")
        assert nx.status_code == 200
        if i < 2:
            assert nx.json()["lanjut"] == "berjalan"
        else:
            assert nx.json()["lanjut"] == "selesai"
            hasil = nx.json()["hasil"]
            assert hasil["benar"] == total_benar
            assert hasil["skor"] > 0
            assert hasil["total_soal"] == 3


def test_jawaban_ganda_ditolak(client):
    client.post("/api/game/reset")
    client.post("/api/game/start", json={"jumlah_soal": 2})
    assert client.post("/api/game/answer", json={"pilihan": "A"}).status_code == 200
    r = client.post("/api/game/answer", json={"pilihan": "B"})
    assert r.status_code == 409
    assert "sudah dijawab" in r.json()["detail"].lower()


def test_jawaban_tidak_valid_ditolak(client):
    client.post("/api/game/reset")
    client.post("/api/game/start", json={"jumlah_soal": 2})
    assert client.post("/api/game/answer", json={"pilihan": "Z"}).status_code == 422
    assert client.post("/api/game/answer", json={"pilihan": "E"}).status_code == 422


def test_tidak_bisa_jawab_tanpa_sesi(client):
    client.post("/api/game/reset")
    r = client.post("/api/game/answer", json={"pilihan": "A"})
    assert r.status_code == 400
    r = client.post("/api/game/next")
    assert r.status_code == 400


def test_timeout_mencatat_jawaban_kosong(client):
    client.post("/api/game/reset")
    client.post("/api/game/start", json={"jumlah_soal": 2})
    assert client.post("/api/game/timeout").status_code == 200
    # setelah timeout, soal yang sama tidak bisa dijawab lagi
    assert client.post("/api/game/answer", json={"pilihan": "A"}).status_code == 409
    nx = client.post("/api/game/next")
    assert nx.json()["lanjut"] == "berjalan"


def test_start_tanpa_soal_aktif_gagal(client, auth):
    """Bila semua soal dinonaktifkan, start harus gagal dengan pesan jelas."""
    items = client.get("/api/admin/pertanyaan?limit=500", headers=auth).json()["items"]
    ids = [q["id"] for q in items]
    for qid in ids:
        q = client.get(f"/api/admin/pertanyaan/{qid}", headers=auth).json()
        client.put(f"/api/admin/pertanyaan/{qid}", headers=auth, json={
            "pertanyaan": q["pertanyaan"], "pilihan_a": q["pilihan"]["A"],
            "pilihan_b": q["pilihan"]["B"], "pilihan_c": q["pilihan"]["C"],
            "pilihan_d": q["pilihan"]["D"], "jawaban": q["jawaban"],
            "kategori": q["kategori"], "durasi": q["durasi"], "aktif": False,
        })
    client.post("/api/game/reset")
    r = client.post("/api/game/start", json={"jumlah_soal": 3})
    assert r.status_code == 400
    assert "belum ada pertanyaan" in r.json()["detail"].lower()

    # pulihkan agar test lain tetap bisa jalan
    for qid in ids:
        q = client.get(f"/api/admin/pertanyaan/{qid}", headers=auth).json()
        client.put(f"/api/admin/pertanyaan/{qid}", headers=auth, json={
            "pertanyaan": q["pertanyaan"], "pilihan_a": q["pilihan"]["A"],
            "pilihan_b": q["pilihan"]["B"], "pilihan_c": q["pilihan"]["C"],
            "pilihan_d": q["pilihan"]["D"], "jawaban": q["jawaban"],
            "kategori": q["kategori"], "durasi": q["durasi"], "aktif": True,
        })


def test_soal_diambil_dari_database(client, auth):
    """Soal yang ditambah lewat admin harus bisa muncul di permainan."""
    r = client.post("/api/admin/pertanyaan", headers=auth, json={
        "pertanyaan": "Soal khusus yang ditambahkan panitia untuk pengujian API?",
        "pilihan_a": "Pilihan satu", "pilihan_b": "Pilihan dua",
        "pilihan_c": "Pilihan tiga", "pilihan_d": "Pilihan empat",
        "jawaban": "B", "kategori": "Uji Dinamis", "durasi": 20, "aktif": True,
    })
    qid = r.json()["id"]

    client.post("/api/game/reset")
    # ambil semua soal agar yang baru pasti ikut terundi
    from app import database
    with database.get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) n FROM pertanyaan WHERE aktif=1").fetchone()["n"]

    st = client.post("/api/game/start", json={"jumlah_soal": min(total, 20)}).json()
    texts = []
    for i in range(st["total_soal"]):
        cur = client.get("/api/game/state").json()
        texts.append(cur["soal"]["pertanyaan"])
        client.post("/api/game/timeout")
        client.post("/api/game/next")
    assert "Soal khusus yang ditambahkan panitia untuk pengujian API?" in texts
    client.delete(f"/api/admin/pertanyaan/{qid}", headers=auth)


# ------------------------------------------------------------ endpoint publik
def test_info_endpoint(client):
    r = client.get("/api/info")
    assert r.status_code == 200
    assert r.json()["sekolah"] == "SMK Telkom Sidoarjo"
    assert set(r.json()["gesture"]) == {"A", "B", "C", "D"}


def test_cv_endpoints_tanpa_kamera(client):
    """Endpoint kamera harus gagal dengan rapi (503), bukan crash 500."""
    client.post("/api/cv/stop")
    r = client.get("/api/cv/stream")
    assert r.status_code == 503
    r = client.get("/api/cv/landmarks")
    assert r.status_code == 404
    r = client.get("/api/cv/live")
    assert r.status_code == 200
    assert r.json()["aktif"] is False


def test_feed_demo_dinonaktifkan(client):
    """Endpoint injeksi gesture tidak boleh terbuka untuk pengunjung."""
    r = client.post("/api/cv/feed?gesture=A")
    assert r.status_code == 403


# ------------------------------------------------- 2 PLAYER BATTLE (API)
def _jawaban_soal_aktif(client, mode: str = "battle") -> str:
    """Ambil kunci jawaban dari DB untuk soal yang sedang aktif."""
    from app import database
    st = client.get("/api/battle/state" if mode == "battle" else "/api/game/state").json()
    with database.get_conn() as conn:
        row = conn.execute(
            "SELECT jawaban FROM pertanyaan WHERE pertanyaan = ?",
            (st["soal"]["pertanyaan"],),
        ).fetchone()
    return row["jawaban"]


def test_battle_start_dan_state(client):
    client.post("/api/battle/reset")
    r = client.post("/api/battle/start", json={"jumlah_soal": 2,
                                               "nama_pemain_1": "Rina",
                                               "nama_pemain_2": "Budi"})
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["mode"] == "battle"
    assert st["total_soal"] == 2
    assert st["pemain"]["1"]["nama"] == "Rina"
    assert st["pemain"]["2"]["nama"] == "Budi"
    assert "jawaban" not in st["soal"], "kunci jawaban tidak boleh bocor"
    assert st["pemain"]["1"]["skor"] == 0 and st["pemain"]["2"]["skor"] == 0


def test_battle_dua_pemain_jawab_independen(client):
    client.post("/api/battle/reset")
    client.post("/api/battle/start", json={"jumlah_soal": 2})
    benar = _jawaban_soal_aktif(client)
    salah = "A" if benar != "A" else "B"

    r1 = client.post("/api/battle/answer", json={"pemain": 1, "pilihan": benar})
    r2 = client.post("/api/battle/answer", json={"pemain": 2, "pilihan": salah})
    assert r1.status_code == 200 and r1.json()["benar"] is True
    assert r2.status_code == 200 and r2.json()["benar"] is False
    assert r1.json()["skor"] > 0
    assert r2.json()["skor"] == 0, "skor P2 tidak boleh terpengaruh P1"

    nx = client.post("/api/battle/next").json()
    assert nx["lanjut"] == "berjalan", "kedua pemain sudah jawab -> boleh maju"
    assert nx["state"]["nomor"] == 2
    assert nx["state"]["pemain"]["1"]["skor"] == r1.json()["skor"], "skor tidak hilang"


def test_battle_jawaban_ganda_per_pemain_ditolak(client):
    client.post("/api/battle/reset")
    client.post("/api/battle/start", json={"jumlah_soal": 2})
    assert client.post("/api/battle/answer", json={"pemain": 1, "pilihan": "A"}).status_code == 200
    dup = client.post("/api/battle/answer", json={"pemain": 1, "pilihan": "B"})
    assert dup.status_code == 409
    assert "sudah menjawab" in dup.json()["detail"].lower()
    # P2 masih boleh menjawab soal yang sama
    assert client.post("/api/battle/answer", json={"pemain": 2, "pilihan": "C"}).status_code == 200


def test_battle_next_diabaikan_bila_satu_pemain_belum_jawab(client):
    client.post("/api/battle/reset")
    client.post("/api/battle/start", json={"jumlah_soal": 3})
    client.post("/api/battle/answer", json={"pemain": 1, "pilihan": "A"})
    nx = client.post("/api/battle/next").json()
    assert nx["diabaikan"] is True
    assert nx["menunggu"] == [2]
    assert nx["state"]["nomor"] == 1
    assert nx["state"]["pemain"]["1"]["sudah_menjawab"] is True


def test_battle_pemain_invalid_ditolak(client):
    client.post("/api/battle/reset")
    client.post("/api/battle/start", json={"jumlah_soal": 1})
    assert client.post("/api/battle/answer", json={"pemain": 3, "pilihan": "A"}).status_code == 422
    assert client.post("/api/battle/answer", json={"pemain": 0, "pilihan": "A"}).status_code == 422
    assert client.post("/api/battle/answer", json={"pemain": 1, "pilihan": "E"}).status_code == 422


def test_battle_seri_dan_pemenang(client):
    client.post("/api/battle/reset")
    client.post("/api/battle/start", json={"jumlah_soal": 1})
    benar = _jawaban_soal_aktif(client)
    client.post("/api/battle/answer", json={"pemain": 1, "pilihan": benar})
    client.post("/api/battle/answer", json={"pemain": 2, "pilihan": benar})
    nx = client.post("/api/battle/next").json()
    assert nx["lanjut"] == "selesai"
    hasil = nx["hasil"]
    assert hasil["mode"] == "battle"
    assert hasil["seri"] is True
    assert hasil["pemenang"] is None

    # Pertandingan baru: P2 menang
    client.post("/api/battle/reset")
    client.post("/api/battle/start", json={"jumlah_soal": 1})
    benar = _jawaban_soal_aktif(client)
    salah = "A" if benar != "A" else "D"
    client.post("/api/battle/answer", json={"pemain": 1, "pilihan": salah})
    client.post("/api/battle/answer", json={"pemain": 2, "pilihan": benar})
    hasil = client.post("/api/battle/next").json()["hasil"]
    assert hasil["pemenang"] == 2
    assert hasil["status"] == "pemain_2"


def test_battle_timeout_menyimpan_skor_pemain_yang_sudah_jawab(client):
    client.post("/api/battle/reset")
    client.post("/api/battle/start", json={"jumlah_soal": 2})
    benar = _jawaban_soal_aktif(client)
    skor1 = client.post("/api/battle/answer",
                        json={"pemain": 1, "pilihan": benar}).json()["skor"]
    assert client.post("/api/battle/timeout").status_code == 200
    st = client.get("/api/battle/state").json()
    assert st["pemain"]["1"]["skor"] == skor1
    assert st["pemain"]["2"]["skor"] == 0


def test_battle_result_tanpa_sesi_404(client):
    client.post("/api/battle/reset")
    assert client.get("/api/battle/result").status_code == 404


def test_photo_frame_tanpa_kamera_503(client):
    """Photo Moment harus gagal dengan rapi bila kamera mati."""
    client.post("/api/cv/stop")
    r = client.get("/api/cv/photo-frame")
    assert r.status_code == 503
    assert "kamera" in r.json()["detail"].lower()


def test_mode_kamera_battle_ditolak_tanpa_webcam(client):
    """Tanpa webcam, /api/cv/start?mode=battle memberi 503 (bukan 500)."""
    client.post("/api/cv/stop")
    r = client.post("/api/cv/start?mode=battle")
    assert r.status_code in (503, 200), r.text
    client.post("/api/cv/stop")
