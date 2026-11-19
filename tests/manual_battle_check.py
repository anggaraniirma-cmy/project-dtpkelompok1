"""Cek kamera untuk mode 2 PLAYER BATTLE (jendela preview).

Menampilkan kamera dengan pembatas zona dan status kedua pemain, plus laporan
teks apa adanya: tangan mana yang terdeteksi di zona mana.

Pakai:
    .venv\\Scripts\\python.exe tests/manual_battle_check.py            # 20 detik
    .venv\\Scripts\\python.exe tests/manual_battle_check.py --seconds 60
    .venv\\Scripts\\python.exe tests/manual_battle_check.py --no-window

Bila tidak ada tangan di depan kamera, skrip MELAPORKAN itu — bukan mengklaim
berhasil.
"""
from __future__ import annotations

import argparse
import sys
import time
import collections

import cv2

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "backend"))

from app.cv import overlay  # noqa: E402
from app.cv.camera import CameraError, CameraStream  # noqa: E402
from app.cv.landmarks import HandDetector  # noqa: E402
from app.cv.players import PlayerSplitter  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--no-window", action="store_true")
    ap.add_argument("--cam", type=int, default=None)
    args = ap.parse_args()

    cam = CameraStream(index=args.cam)
    try:
        cam.start()
    except CameraError as exc:
        print(f"KAMERA TIDAK TERSEDIA: {exc}")
        return 2

    det = HandDetector(num_hands=2)
    splitter = PlayerSplitter()
    stats = collections.Counter()
    p1_gestures = collections.Counter()
    p2_gestures = collections.Counter()
    t0 = time.time()
    frames = 0

    print(f"Mengamati selama {args.seconds:.0f} detik. Berdiri berdua, tangan KANAN.")
    try:
        while time.time() - t0 < args.seconds:
            frame, _ = cam.read()
            if frame is None:
                continue
            hands = det.detect_many(frame)
            split = splitter.assign(hands)
            frames += 1
            if split.terisi(1):
                stats["p1_terdeteksi"] += 1
            if split.terisi(2):
                stats["p2_terdeteksi"] += 1
            if len(split.hands) == 2:
                stats["dua_tangan"] += 1
            stats[f"tangan_di_frame_{len(hands)}"] += 1
            for p in (1, 2):
                if p in split.hands:
                    r = split.hands[p]
                    if r.handedness == "Left":
                        stats[f"p{p}_tangan_kiri"] += 1
                    if not split.zone_ok.get(p, True):
                        stats[f"p{p}_di_luar_zona"] += 1

            mirrored = cv2.flip(frame, 1)
            res = {p: None for p in (1, 2)}
            overlay.draw_battle_overlay(
                mirrored, split, res,
                {p: 0.0 for p in (1, 2)},
                {p: None for p in (1, 2)},
                0.0,
            )
            if not args.no_window:
                cv2.imshow("SKOMDA 2P check (ESC untuk keluar)", mirrored)
                if cv2.waitKey(1) & 0xFF == 27:
                    break
    finally:
        cam.stop()
        det.close()
        if not args.no_window:
            cv2.destroyAllWindows()

    print()
    print(f"Frame diproses: {frames}")
    if not frames:
        print("TIDAK ADA FRAME DARI KAMERA.")
        return 1
    print(f"Frame dengan 2 tangan      : {stats['dua_tangan']} "
          f"({100*stats['dua_tangan']/frames:.1f}%)")
    print(f"Player 1 terdeteksi        : {stats['p1_terdeteksi']} "
          f"({100*stats['p1_terdeteksi']/frames:.1f}%)")
    print(f"Player 2 terdeteksi        : {stats['p2_terdeteksi']} "
          f"({100*stats['p2_terdeteksi']/frames:.1f}%)")
    print(f"Player 1 di luar zona      : {stats['p1_di_luar_zona']}")
    print(f"Player 2 di luar zona      : {stats['p2_di_luar_zona']}")
    print(f"Tangan kiri (ditolak) P1/P2: {stats['p1_tangan_kiri']}/{stats['p2_tangan_kiri']}")
    if stats["dua_tangan"] == 0:
        print()
        print("CATATAN: dua tangan tidak pernah terdeteksi bersamaan. Periksa:")
        print("  - kedua pemain benar-benar di zona kiri & kanan")
        print("  - pencahayaan cukup, tangan tidak terhalang")
        print("  - kamera tidak dipakai aplikasi lain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
