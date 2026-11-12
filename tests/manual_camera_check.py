"""Uji kamera NYATA: deteksi tangan + klasifikasi gesture dari webcam asli.

Melewati gambar buatan. Test ini butuh orang di depan kamera, jadi
di-skip otomatis bila tidak ada tangan terdeteksi (mis. mesin headless),
dan melaporkan apa adanya. Jalankan manual:

    .venv/Scripts/python.exe tests/manual_camera_check.py

Mode interaktif (tampilkan jendela + overlay):
    .venv/Scripts/python.exe tests/manual_camera_check.py --gui
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import cv2  # noqa: E402

from app.cv.camera import CameraStream  # noqa: E402
from app.cv.gesture import GESTURE_LABEL, GestureClassifier  # noqa: E402
from app.cv.landmarks import HandDetector  # noqa: E402
from app.cv.overlay import draw_hud, draw_landmarks  # noqa: E402
from app.cv.stabilizer import GestureStabilizer  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gui", action="store_true", help="tampilkan jendela kamera")
    ap.add_argument("--seconds", type=float, default=15.0)
    args = ap.parse_args()

    print("Membuka kamera & MediaPipe…")
    cam = CameraStream()
    cam.start()
    det = HandDetector()
    clf = GestureClassifier()
    stab = GestureStabilizer(hold_seconds=1.0, cooldown_seconds=1.5)

    print(f"Resolusi: {cam.width}x{cam.height}")
    print(f"Uji selama {args.seconds:.0f} detik. Tunjukkan gerakan A/B/C/D.\n")

    seen_hand = 0
    frames = 0
    gestures = Counter()
    locks = []
    reasons = Counter()
    t0 = time.time()
    last_id = 0

    try:
        while time.time() - t0 < args.seconds:
            frame, fid = cam.read()
            if frame is None or fid == last_id:
                time.sleep(0.005)
                continue
            last_id = fid
            frames += 1

            obs = det.detect(frame)
            res = clf.classify(obs) if obs is not None else None
            gesture = res.gesture if res else None
            if obs is not None:
                seen_hand += 1
            if gesture:
                gestures[gesture] += 1
            elif res is not None and res.reason:
                reasons[res.reason] += 1

            stable = stab.update(gesture)
            if stable.locked:
                locks.append(stable.locked)
                print(f"  KUNCI -> {stable.locked}  ({GESTURE_LABEL[stable.locked]})")

            if args.gui:
                mirrored = cv2.flip(frame, 1)
                if obs is not None and res is not None:
                    draw_landmarks(mirrored, obs, res)
                draw_hud(mirrored, res, stable.gesture, stable.progress,
                         stab.cooldown_remaining, 0.0,
                         stable.locked if stable.locked else None)
                cv2.imshow("SKOMDA - Uji Kamera (ESC untuk keluar)", mirrored)
                if cv2.waitKey(1) & 0xFF == 27:
                    break
    finally:
        cam.stop()
        det.close()
        if args.gui:
            cv2.destroyAllWindows()

    elapsed = time.time() - t0
    print("\n=== HASIL UJI KAMERA NYATA ===")
    print(f"Frame diproses      : {frames}  ({frames / elapsed:.1f} FPS)")
    print(f"Frame ada tangan    : {seen_hand}  ({100 * seen_hand / max(frames, 1):.0f}%)")
    print(f"Gesture terbaca     : {dict(gestures) or 'tidak ada'}")
    print(f"Kunci jawaban       : {locks or 'tidak ada'}")

    if seen_hand == 0:
        print("\nSTATUS: TIDAK ADA TANGAN TERDETEKSI — kamera berfungsi, tetapi")
        print("        tidak ada tangan di depan kamera saat pengujian.")
        print("        Ini bukan kegagalan kode; ulangi dengan tangan terlihat.")
        return 2

    print(f"\nSTATUS: OK — {seen_hand} frame dengan tangan nyata terdeteksi.")
    if gestures:
        print(f"        Gesture dominan: {gestures.most_common(1)[0][0]}")
    # Bukti bahwa aturan menolak gesture tidak valid:
    if reasons:
        print(f"        Penolakan (contoh): {list(reasons.items())[:3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
