"""Jalankan ketiga service sekaligus.

    python scripts/run_all.py

  * Backend API + Computer Vision : http://localhost:8000
  * Admin Panel                   : http://localhost:3000
  * Visitor / Game Panel          : http://localhost:8080

Bila port 3000/8080 terpakai proses lain, server frontend memilih port
berikutnya dan mencetak URL sebenarnya. Tekan Ctrl+C untuk menghentikan
semua (kamera ikut dilepas).
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
BACKEND = PROJECT_DIR / "backend"
PY = str(PROJECT_DIR / ".venv" / "Scripts" / "python.exe")
if not Path(PY).exists():
    PY = sys.executable

API_PORT = int(os.getenv("SKOMDA_PORT", "8000"))
API_URL = f"http://localhost:{API_PORT}"

procs: list[subprocess.Popen] = []


def start(name: str, args: list[str], cwd: Path, env: dict | None = None) -> subprocess.Popen:
    # PYTHONUNBUFFERED: tanpa ini, log anak (uvicorn / static server) tidak
    # muncul di jendela start.bat sampai proses selesai.
    e = {**os.environ, "PYTHONUNBUFFERED": "1", **(env or {})}
    p = subprocess.Popen(args, cwd=str(cwd), env=e)
    procs.append(p)
    return p


def wait_api(timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(API_URL + "/api/health", timeout=1.5) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def shutdown(*_):
    print("\n  Menghentikan semua service…")
    for p in procs:
        if p.poll() is None:
            p.terminate()
    time.sleep(0.6)
    for p in procs:
        if p.poll() is None:
            p.kill()
    sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # flush=True: saat dijalankan lewat start.bat / redirect, Python memblok
    # output sehingga pengguna tidak melihat progres apa pun sampai selesai.
    def say(msg: str = "") -> None:
        print(msg, flush=True)

    say("\n  SKOMDA GESTURE QUIZ — SMK Telkom Sidoarjo")
    say("  " + "─" * 52)
    say(f"  Python  : {PY}")
    say(f"  Database: {os.getenv('SKOMDA_DB', 'backend/data/quiz.db')}")

    # 1) Backend
    say("  [1/3] Menjalankan backend API + computer vision…")
    start("api", [PY, "-m", "app", "--port", str(API_PORT)], BACKEND)

    if wait_api():
        say(f"  [1/3] Backend siap di {API_URL}")
    else:
        say(f"  [1/3] PERINGATAN: backend belum merespons di {API_URL}")
        say("        Periksa pesan error di atas (model/kamera/dependency).")

    # 2) Admin dan 3) Visitor
    say("  [2/3] Menjalankan admin panel…")
    start("admin", [PY, str(PROJECT_DIR / "scripts" / "serve_frontend.py"), "admin",
                    "--port", "3000", "--api", API_URL], PROJECT_DIR)
    say("  [3/3] Menjalankan panel pengunjung…")
    start("visitor", [PY, str(PROJECT_DIR / "scripts" / "serve_frontend.py"), "visitor",
                      "--port", "8080", "--api", API_URL], PROJECT_DIR)

    time.sleep(2.0)
    say("  " + "─" * 52)
    say(f"  API      : {API_URL}  ({API_URL}/docs)")
    say("  Admin    : http://localhost:3000   (admin / skomda2026)")
    say("  Visitor  : http://localhost:8080")
    say("  " + "─" * 52)
    say("  Tekan Ctrl+C untuk berhenti.\n")

    try:
        while True:
            for p in list(procs):
                if p.poll() is not None:
                    say(f"  Service berhenti (exit {p.returncode}). Menghentikan semua…")
                    shutdown()
            time.sleep(1.0)
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
