"""Tutup sesi "berjalan" yang tertinggal dari versi lama / crash.

    .venv/Scripts/python.exe scripts/bersihkan_sesi.py            # lihat saja
    .venv/Scripts/python.exe scripts/bersihkan_sesi.py --apply     # tutup

Sejak Tahap 7, backend punya worker yang menutup sesi telantar secara otomatis
(lihat config.SESI_TELANTAR_DETIK). Skrip ini hanya untuk membersihkan baris
lama yang sudah terlanjur menggantung di database sebelum aturan itu ada.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app import config, database  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="benar-benar menutup sesi")
    ap.add_argument("--db", default=None, help="path database (default: konfigurasi)")
    args = ap.parse_args()

    db_path = Path(args.db) if args.db else config.get_db_path()
    if not db_path.exists():
        print(f"Database tidak ditemukan: {db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, total_soal, benar, skor, started_at FROM sesi_permainan"
        " WHERE status = 'berjalan' ORDER BY started_at"
    ).fetchall()

    print(f"Database : {db_path}")
    print(f"Sesi 'berjalan' tertinggal: {len(rows)}")
    for r in rows:
        print(f"  {r['id']}  mulai {r['started_at']}  "
              f"({r['benar']}/{r['total_soal']} benar, skor {r['skor']})")

    if not rows:
        conn.close()
        print("\nTidak ada yang perlu dibersihkan.")
        return 0

    if not args.apply:
        conn.close()
        print("\nMode lihat-saja. Jalankan ulang dengan --apply untuk menutupnya.")
        print("Status akan diubah menjadi 'dibatalkan' dengan finished_at = sekarang.")
        return 0

    ts = database.now_iso()
    conn.executemany(
        "UPDATE sesi_permainan SET status='dibatalkan', finished_at=? WHERE id=?",
        [(ts, r["id"]) for r in rows],
    )
    conn.commit()
    conn.close()
    print(f"\n{len(rows)} sesi ditutup sebagai 'dibatalkan' pada {ts}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
