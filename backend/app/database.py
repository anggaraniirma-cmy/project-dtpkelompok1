"""Akses SQLite: koneksi, skema, dan seed awal.

Menggunakan sqlite3 standar (tanpa ORM) supaya ringan dan tidak menambah
dependency. Setiap operasi memakai koneksi sendiri (WAL) karena backend
diakses dari thread kamera + thread request FastAPI.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from . import config
from .security import hash_password

SCHEMA = """
CREATE TABLE IF NOT EXISTS admin (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    nama          TEXT NOT NULL DEFAULT 'Panitia',
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pertanyaan (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pertanyaan  TEXT NOT NULL,
    pilihan_a   TEXT NOT NULL,
    pilihan_b   TEXT NOT NULL,
    pilihan_c   TEXT NOT NULL,
    pilihan_d   TEXT NOT NULL,
    jawaban     TEXT NOT NULL CHECK (jawaban IN ('A','B','C','D')),
    kategori    TEXT NOT NULL DEFAULT 'Umum',
    durasi      INTEGER NOT NULL DEFAULT 30,
    aktif       INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sesi_permainan (
    id           TEXT PRIMARY KEY,
    total_soal   INTEGER NOT NULL,
    benar        INTEGER NOT NULL DEFAULT 0,
    skor         INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'berjalan',
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    -- Mode 2 PLAYER BATTLE. Baris mode='single' membiarkan kolom ini NULL,
    -- jadi skema lama tetap valid dan data lama tidak perlu diubah.
    mode         TEXT NOT NULL DEFAULT 'single',
    pemain_1     TEXT,
    pemain_2     TEXT,
    skor_1       INTEGER,
    skor_2       INTEGER,
    benar_1      INTEGER,
    benar_2      INTEGER
);

CREATE TABLE IF NOT EXISTS jawaban_permainan (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sesi_id      TEXT NOT NULL REFERENCES sesi_permainan(id) ON DELETE CASCADE,
    pertanyaan_id INTEGER,
    urutan       INTEGER NOT NULL,
    jawaban      TEXT,
    benar        INTEGER NOT NULL DEFAULT 0,
    waktu_pakai  REAL NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    -- NULL = jawaban mode single player; 1/2 = nomor pemain pada mode battle.
    pemain       INTEGER
);

CREATE INDEX IF NOT EXISTS idx_jawaban_sesi ON jawaban_permainan(sesi_id);
CREATE INDEX IF NOT EXISTS idx_pertanyaan_kategori ON pertanyaan(kategori);

-- Pengaturan permainan yang bisa diubah panitia dari panel admin tanpa
-- menyentuh kode. Disimpan sebagai key/value agar mudah ditambah.
CREATE TABLE IF NOT EXISTS pengaturan (
    kunci      TEXT PRIMARY KEY,
    nilai      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Galeri dokumentasi: foto hasil Photo Moment yang DIKIRIM pengunjung secara
-- sadar (tombol "Kirim ke Galeri Panitia"). File biner disimpan di folder
-- backend/data/foto/, tabel ini hanya metadata + nama file.
--
-- `publik` = status PERSETUJUAN TAMPIL di carousel hero halaman pengunjung.
-- Default 0: foto baru TIDAK otomatis dipajang ke publik. Panitia harus
-- menyetujui satu per satu lewat panel admin, sehingga tidak ada foto
-- pengunjung yang tayang tanpa izin.
CREATE TABLE IF NOT EXISTS galeri_foto (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nama_file   TEXT NOT NULL UNIQUE,
    sesi_id     TEXT,
    mode        TEXT NOT NULL DEFAULT 'single',
    pemain_1    TEXT,
    pemain_2    TEXT,
    skor_1      INTEGER,
    skor_2      INTEGER,
    pemenang    TEXT,
    ukuran      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    publik      INTEGER NOT NULL DEFAULT 0,
    publik_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_galeri_created ON galeri_foto(created_at DESC);
"""

# Nilai default & batas tiap pengaturan. Batas ditegakkan di backend supaya
# panitia tidak bisa membuat permainan mustahil (mis. timer 1 detik).
PENGATURAN_DEFAULT = {
    "jumlah_soal": 5,       # soal per sesi
    "durasi_default": 30,   # detik per soal, dipakai saat menambah soal baru
    "hold_detik": 1.0,      # lama gesture harus ditahan sebelum terkunci
    "cooldown_detik": 1.5,  # jeda minimal antar jawaban
}

PENGATURAN_BATAS = {
    "jumlah_soal": (1, 20),
    "durasi_default": (5, 180),
    "hold_detik": (0.6, 3.0),
    "cooldown_detik": (0.5, 5.0),
}

SEED_QUESTIONS = [
    ("Apa kepanjangan dari SMK?", "Sekolah Menengah Kejuruan", "Sekolah Menengah Komputer",
     "Sarjana Muda Komputer", "Sekolah Musik Klasik", "A", "Umum", 30),
    ("Bahasa pemrograman utama yang dipakai membangun backend aplikasi ini adalah?",
     "JavaScript", "Python", "PHP", "Go", "B", "Pemrograman", 30),
    ("Library Python yang dipakai untuk mendeteksi 21 titik tangan pada proyek ini?",
     "NumPy", "OpenCV", "MediaPipe", "Pandas", "C", "Computer Vision", 30),
    ("Berapa jumlah pilihan jawaban pada SKOMDA Gesture Quiz?",
     "Dua", "Tiga", "Empat", "Lima", "C", "Umum", 25),
    ("Modul Python yang dipakai untuk membaca frame webcam adalah?",
     "OpenCV (cv2)", "Flask", "Matplotlib", "Requests", "A", "Computer Vision", 25),
    ("Jurusan di SMK Telkom Sidoarjo yang mempelajari pengembangan perangkat lunak adalah?",
     "TKJ", "RPL", "DKV", "TBSM", "B", "Sekolah", 30),
    ("Gesture 'A' pada permainan ini dilakukan dengan mengangkat?",
     "Telunjuk saja", "Telunjuk dan tengah", "Tiga jari", "Empat jari", "A", "Gesture", 25),
    ("Database ringan berbasis file yang dipakai proyek ini adalah?",
     "MySQL Server", "PostgreSQL", "SQLite", "MongoDB", "C", "Database", 30),
]


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(config.get_db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrasi_kolom(conn: sqlite3.Connection) -> None:
    """Tambahkan kolom baru ke database lama (CREATE TABLE IF NOT EXISTS tidak
    menambah kolom pada tabel yang sudah ada).

    Idempoten: setiap kolom diperiksa lewat PRAGMA table_info sebelum ALTER,
    jadi aman dijalankan setiap startup dan tidak menyentuh data lama.
    """
    tambahan = {
        "sesi_permainan": [
            ("mode", "TEXT NOT NULL DEFAULT 'single'"),
            ("pemain_1", "TEXT"),
            ("pemain_2", "TEXT"),
            ("skor_1", "INTEGER"),
            ("skor_2", "INTEGER"),
            ("benar_1", "INTEGER"),
            ("benar_2", "INTEGER"),
        ],
        "jawaban_permainan": [
            ("pemain", "INTEGER"),
        ],
        # Kolom persetujuan publikasi carousel hero. Database yang dibuat
        # sebelum fitur ini tidak punya kolomnya, jadi ditambahkan di sini.
        "galeri_foto": [
            ("publik", "INTEGER NOT NULL DEFAULT 0"),
            ("publik_at", "TEXT"),
        ],
    }
    for tabel, kolom in tambahan.items():
        ada = {r["name"] for r in conn.execute(f"PRAGMA table_info({tabel})").fetchall()}
        for nama, tipe in kolom:
            if nama not in ada:
                conn.execute(f"ALTER TABLE {tabel} ADD COLUMN {nama} {tipe}")


def init_db() -> None:
    """Buat skema bila belum ada + seed admin, pengaturan & contoh soal."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrasi_kolom(conn)
        cur = conn.execute("SELECT COUNT(*) AS n FROM admin")
        if cur.fetchone()["n"] == 0:
            conn.execute(
                "INSERT INTO admin (username, password_hash, nama, created_at) VALUES (?,?,?,?)",
                (config.ADMIN_DEFAULT_USERNAME,
                 hash_password(config.ADMIN_DEFAULT_PASSWORD),
                 "Panitia SKOMDA", now_iso()),
            )
        # Pengaturan: isi hanya kunci yang belum ada (aman untuk upgrade).
        ts = now_iso()
        for kunci, nilai in PENGATURAN_DEFAULT.items():
            conn.execute(
                "INSERT OR IGNORE INTO pengaturan (kunci, nilai, updated_at) VALUES (?,?,?)",
                (kunci, str(nilai), ts),
            )
        cur = conn.execute("SELECT COUNT(*) AS n FROM pertanyaan")
        if cur.fetchone()["n"] == 0:
            for q in SEED_QUESTIONS:
                conn.execute(
                    """INSERT INTO pertanyaan
                       (pertanyaan, pilihan_a, pilihan_b, pilihan_c, pilihan_d,
                        jawaban, kategori, durasi, aktif, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,1,?,?)""",
                    (*q, ts, ts),
                )


def jumlah_soal_aktif() -> int:
    """Berapa soal aktif yang tersedia di bank soal.

    Dipakai UI untuk memberi tahu pengunjung bila memilih 7/10 soal padahal
    soal aktif belum cukup — permainan tetap berjalan dengan soal yang ada,
    tanpa error.
    """
    try:
        with get_conn() as conn:
            return int(conn.execute(
                "SELECT COUNT(*) n FROM pertanyaan WHERE aktif = 1"
            ).fetchone()["n"])
    except sqlite3.Error:
        return 0


def get_pengaturan() -> dict[str, float | int]:
    """Baca pengaturan permainan; nilai yang hilang/rusak jatuh ke default.

    Tipe dikembalikan sesuai PENGATURAN_DEFAULT (int untuk soal/durasi,
    float untuk hold/cooldown) supaya pemakai tidak perlu casting.
    """
    data: dict[str, float | int] = dict(PENGATURAN_DEFAULT)
    try:
        with get_conn() as conn:
            rows = conn.execute("SELECT kunci, nilai FROM pengaturan").fetchall()
    except sqlite3.Error:
        return data
    for row in rows:
        kunci, raw = row["kunci"], row["nilai"]
        if kunci not in PENGATURAN_DEFAULT:
            continue
        cetak = float if isinstance(PENGATURAN_DEFAULT[kunci], float) else int
        try:
            data[kunci] = cetak(float(raw))
        except (TypeError, ValueError):
            continue
    return data


def simpan_pengaturan(perubahan: dict[str, float | int]) -> dict[str, float | int]:
    """Validasi + simpan pengaturan. Melempar ValueError bila di luar batas."""
    bersih: dict[str, float | int] = {}
    for kunci, nilai in perubahan.items():
        if kunci not in PENGATURAN_DEFAULT:
            raise ValueError(f"Pengaturan tidak dikenal: {kunci}")
        lo, hi = PENGATURAN_BATAS[kunci]
        try:
            angka = float(nilai)
        except (TypeError, ValueError):
            raise ValueError(f"Nilai {kunci} harus berupa angka")
        if not (lo <= angka <= hi):
            raise ValueError(f"Nilai {kunci} harus antara {lo} dan {hi}")
        cetak = float if isinstance(PENGATURAN_DEFAULT[kunci], float) else int
        bersih[kunci] = cetak(angka)

    if not bersih:
        raise ValueError("Tidak ada pengaturan yang dikirim")

    ts = now_iso()
    with get_conn() as conn:
        for kunci, nilai in bersih.items():
            conn.execute(
                """INSERT INTO pengaturan (kunci, nilai, updated_at) VALUES (?,?,?)
                   ON CONFLICT(kunci) DO UPDATE SET nilai=excluded.nilai,
                                                    updated_at=excluded.updated_at""",
                (kunci, str(nilai), ts),
            )
    return get_pengaturan()


def row_to_question(row: sqlite3.Row, include_answer: bool = True) -> dict:
    data = {
        "id": row["id"],
        "pertanyaan": row["pertanyaan"],
        "pilihan": {
            "A": row["pilihan_a"],
            "B": row["pilihan_b"],
            "C": row["pilihan_c"],
            "D": row["pilihan_d"],
        },
        "kategori": row["kategori"],
        "durasi": row["durasi"],
        "aktif": bool(row["aktif"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if include_answer:
        data["jawaban"] = row["jawaban"]
    return data
