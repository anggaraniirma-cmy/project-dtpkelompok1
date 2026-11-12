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
    finished_at  TEXT
);

CREATE TABLE IF NOT EXISTS jawaban_permainan (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sesi_id      TEXT NOT NULL REFERENCES sesi_permainan(id) ON DELETE CASCADE,
    pertanyaan_id INTEGER,
    urutan       INTEGER NOT NULL,
    jawaban      TEXT,
    benar        INTEGER NOT NULL DEFAULT 0,
    waktu_pakai  REAL NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jawaban_sesi ON jawaban_permainan(sesi_id);
CREATE INDEX IF NOT EXISTS idx_pertanyaan_kategori ON pertanyaan(kategori);
"""

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


def init_db() -> None:
    """Buat skema bila belum ada + seed admin & contoh soal (sekali saja)."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        cur = conn.execute("SELECT COUNT(*) AS n FROM admin")
        if cur.fetchone()["n"] == 0:
            conn.execute(
                "INSERT INTO admin (username, password_hash, nama, created_at) VALUES (?,?,?,?)",
                (config.ADMIN_DEFAULT_USERNAME,
                 hash_password(config.ADMIN_DEFAULT_PASSWORD),
                 "Panitia SKOMDA", now_iso()),
            )
        cur = conn.execute("SELECT COUNT(*) AS n FROM pertanyaan")
        if cur.fetchone()["n"] == 0:
            ts = now_iso()
            for q in SEED_QUESTIONS:
                conn.execute(
                    """INSERT INTO pertanyaan
                       (pertanyaan, pilihan_a, pilihan_b, pilihan_c, pilihan_d,
                        jawaban, kategori, durasi, aktif, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,1,?,?)""",
                    (*q, ts, ts),
                )


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
