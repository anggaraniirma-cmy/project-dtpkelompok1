"""Agar `pytest` dari root proyek bisa mengimpor paket `app` di backend/."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Database test terisolasi + jangan pakai webcam nyata di test.
os.environ.setdefault("SKOMDA_TEST", "1")
