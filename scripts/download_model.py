"""Unduh model MediaPipe Hand Landmarker bila belum ada di repo.

    python scripts/download_model.py

Model resmi Google (Apache-2.0), sekitar 7,5 MB. Dipakai sebagai alternatif
bila `backend/models/hand_landmarker.task` tidak tersedia (mis. hasil clone
tanpa file biner).
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
TARGET = Path(__file__).resolve().parent.parent / "backend" / "models" / "hand_landmarker.task"


def main() -> int:
    if TARGET.exists() and TARGET.stat().st_size > 1_000_000:
        print(f"Model sudah ada: {TARGET} ({TARGET.stat().st_size / 1e6:.1f} MB)")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    print(f"Mengunduh model ke {TARGET} ...")
    try:
        urllib.request.urlretrieve(MODEL_URL, TARGET)
    except Exception as exc:  # jaringan sekolah sering memblokir GCS
        print(f"GAGAL mengunduh: {exc}")
        print("Unduh manual dari:")
        print(f"  {MODEL_URL}")
        print(f"lalu simpan sebagai: {TARGET}")
        return 1
    print(f"Selesai: {TARGET.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
