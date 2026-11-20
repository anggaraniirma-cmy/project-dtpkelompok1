"""Konfigurasi terpusat SKOMDA Gesture Quiz.

Semua path & nilai yang bisa diubah lewat environment dibaca di sini.
Catatan: pembacaan env dilakukan lewat fungsi (bukan konstanta modul) untuk
DB path, supaya test suite bisa memakai database sementara.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent

DATA_DIR = Path(os.getenv("SKOMDA_DATA_DIR", str(BACKEND_DIR / "data")))
MODEL_PATH = Path(os.getenv("SKOMDA_MODEL", str(BACKEND_DIR / "models" / "hand_landmarker.task")))

# Folder penyimpanan foto dokumentasi (galeri panitia). Dibuat saat dipakai.
FOTO_DIR = Path(os.getenv("SKOMDA_FOTO_DIR", str(DATA_DIR / "foto")))
FOTO_MAX_BYTES = int(os.getenv("SKOMDA_FOTO_MAX_BYTES", str(8 * 1024 * 1024)))

HOST = os.getenv("SKOMDA_HOST", "127.0.0.1")
PORT = int(os.getenv("SKOMDA_PORT", "8000"))

# Frontend yang diizinkan (admin :3000/:3001, visitor :8080).
CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]

# `serve_frontend.py` otomatis pindah port bila 3000/8080 sedang dipakai. Tanpa
# pola ini, frontend di port 8081 langsung diblokir CORS dan tampak "Backend
# offline". Pola dibatasi ke loopback saja — tetap tidak ada origin luar.
CORS_ORIGIN_REGEX = r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"

# --- Admin & auth ---------------------------------------------------------
ADMIN_DEFAULT_USERNAME = os.getenv("SKOMDA_ADMIN_USER", "admin")
ADMIN_DEFAULT_PASSWORD = os.getenv("SKOMDA_ADMIN_PASS", "skomda2026")
JWT_ALGORITHM = "HS256"
JWT_TTL_SECONDS = int(os.getenv("SKOMDA_JWT_TTL", str(8 * 3600)))

# --- Game ----------------------------------------------------------------
QUIZ_LENGTH = int(os.getenv("SKOMDA_QUIZ_LENGTH", "5"))
DEFAULT_DURATION = int(os.getenv("SKOMDA_DEFAULT_DURATION", "30"))
POIN_BENAR = 10

# Jeda (detik) antara "waktu habis / jawaban dicatat" dan soal berikutnya,
# ditegakkan server-side oleh GameEngine.tick() sehingga browser yang menutup
# tab tidak membuat sesi menggantung.
AUTO_ADVANCE_GRACE = float(os.getenv("SKOMDA_ADVANCE_GRACE", "2.0"))

# Bila soal sudah lewat waktu selama ini (detik), dianggap pengunjung
# meninggalkan kios: sesi ditutup sebagai "dibatalkan" agar tidak ada sesi
# "berjalan" yang menggantung selamanya di database.
SESI_TELANTAR_DETIK = float(os.getenv("SKOMDA_ABANDON_AFTER", "120"))

# --- Computer vision -----------------------------------------------------
CAMERA_INDEX = int(os.getenv("SKOMDA_CAM_INDEX", "0"))
CAMERA_WIDTH = int(os.getenv("SKOMDA_CAM_WIDTH", "640"))
CAMERA_HEIGHT = int(os.getenv("SKOMDA_CAM_HEIGHT", "480"))
CAMERA_FPS_TARGET = int(os.getenv("SKOMDA_CAM_FPS", "30"))
STREAM_QUALITY = int(os.getenv("SKOMDA_STREAM_QUALITY", "72"))

GESTURE_HOLD_SECONDS = float(os.getenv("SKOMDA_GESTURE_HOLD", "1.0"))
GESTURE_COOLDOWN_SECONDS = float(os.getenv("SKOMDA_GESTURE_COOLDOWN", "1.5"))
GESTURE_REARM_SECONDS = float(os.getenv("SKOMDA_GESTURE_REARM", "0.25"))
REQUIRE_RIGHT_HAND = os.getenv("SKOMDA_REQUIRE_RIGHT_HAND", "1") == "1"

# --- Computer vision: seleksi tangan -------------------------------------
# Ambang keyakinan MediaPipe. Dinaikkan dari 0.5 supaya deteksi "ragu" di
# keramaian pameran tidak langsung dipakai sebagai jawaban.
HAND_DETECTION_CONF = float(os.getenv("SKOMDA_HAND_DET_CONF", "0.60"))
HAND_PRESENCE_CONF = float(os.getenv("SKOMDA_HAND_PRESENCE_CONF", "0.60"))
HAND_TRACK_CONF = float(os.getenv("SKOMDA_HAND_TRACK_CONF", "0.55"))

# Jumlah maksimum tangan yang diminta ke MediaPipe. Mode single sengaja
# meminta LEBIH dari satu: tanpa itu, tangan orang di latar belakang bisa
# menjadi satu-satunya hasil dan otomatis dianggap jawaban pemain. Dengan
# beberapa kandidat, sistem bisa memilih tangan terdekat lalu menolak sisanya.
MAX_HANDS_SINGLE = int(os.getenv("SKOMDA_MAX_HANDS_SINGLE", "3"))
MAX_HANDS_BATTLE = int(os.getenv("SKOMDA_MAX_HANDS_BATTLE", "4"))

# Lebar telapak minimum (|MCP telunjuk - MCP kelingking| / lebar frame).
# Tangan yang jauh di latar belakang menghasilkan telapak kecil; ambang ini
# yang membuatnya tidak diterima sebagai input pemain.
HAND_MIN_PALM_WIDTH = float(os.getenv("SKOMDA_HAND_MIN_PALM", "0.055"))

# Area permainan (x0,y0,x1,y1 ternormalisasi). Tangan yang pusatnya di luar
# area ini diabaikan. Default membuang strip atas frame, tempat tangan orang
# yang berdiri di belakang biasanya muncul.
def _roi_dari_env() -> tuple[float, float, float, float]:
    raw = os.getenv("SKOMDA_HAND_ROI", "0.02,0.05,0.98,1.0")
    try:
        x0, y0, x1, y1 = (float(v) for v in raw.split(","))
    except (TypeError, ValueError):
        return (0.02, 0.05, 0.98, 1.0)
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        return (0.02, 0.05, 0.98, 1.0)
    return (x0, y0, x1, y1)


HAND_ROI = _roi_dari_env()

# Tracking identitas antar frame & memori pemain.
TRACK_MAX_MISS_SECONDS = float(os.getenv("SKOMDA_TRACK_MAX_MISS", "0.8"))
TRACK_DIST_MAX = float(os.getenv("SKOMDA_TRACK_DIST", "0.30"))
PLAYER_MEMORY_SECONDS = float(os.getenv("SKOMDA_PLAYER_MEMORY", "0.9"))

# Jalur jawab manual (klik opsi) untuk keadaan darurat saat kamera bermasalah.
# Aktif secara default; set SKOMDA_ALLOW_MANUAL_ANSWER=0 saat pameran bila
# panitia ingin jawaban MURNI lewat gesture.
ALLOW_MANUAL_ANSWER = os.getenv("SKOMDA_ALLOW_MANUAL_ANSWER", "1") == "1"


def get_db_path() -> Path:
    """Path SQLite; dibaca tiap panggilan agar test bisa override lewat env."""
    raw = os.getenv("SKOMDA_DB")
    path = Path(raw) if raw else DATA_DIR / "quiz.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_secret_key() -> str:
    """Secret JWT persisten per instalasi (env menang, kalau tidak file lokal)."""
    env = os.getenv("SKOMDA_SECRET")
    if env:
        return env
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    f = DATA_DIR / ".jwt_secret"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(48)
    f.write_text(value, encoding="utf-8")
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass
    return value
