"""Agar `pytest` dari root proyek bisa mengimpor paket `app` di backend/."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Database test terisolasi + jangan pakai webcam nyata di test.
os.environ.setdefault("SKOMDA_TEST", "1")

# PENTING: seluruh artefak runtime test WAJIB diarahkan ke folder sementara
# SEBELUM `app.config` diimpor. Menyetel env ini di dalam file test tidak
# cukup: modul test diimpor berurutan dan file pertama yang meng-import
# `app.config` mengunci nilai FOTO_DIR untuk seluruh sesi. Tanpa ini, upload
# foto pada test menulis ke backend/data/foto/ yang berisi data pengunjung
# asli (pernah terjadi: puluhan berkas uji 75 byte tertinggal di sana).
_TMP_TEST = tempfile.mkdtemp(prefix="skomda_pytest_")
os.environ.setdefault("SKOMDA_DB", os.path.join(_TMP_TEST, "test.db"))
os.environ.setdefault("SKOMDA_FOTO_DIR", os.path.join(_TMP_TEST, "foto"))
os.environ.setdefault("SKOMDA_DATA_DIR", _TMP_TEST)
