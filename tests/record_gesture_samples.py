"""Perekam sampel landmark untuk kalibrasi ambang gesture.

Jalankan di laptop pameran, lalu lakukan tiap gesture beberapa kali. Skrip
menyimpan 21 landmark mentah per frame ke JSONL, yang nanti dianalisis oleh
scripts/analyze_calibration.py untuk menentukan ambang rasio/kelurusan yang
paling pas dengan tangan & kamera sebenarnya.

    .venv/Scripts/python.exe tests/record_gesture_samples.py
    .venv/Scripts/python.exe tests/record_gesture_samples.py --seconds 5 --out backend/data/calibration

Tombol (jendela harus aktif):
    A / B / C / D  mulai merekam gesture tersebut selama --seconds detik
    SPASI          rekam gesture yang sedang dipilih tanpa membuka sesi baru
    Q / ESC        selesai dan simpan

Bila kamera atau tangan tidak terdeteksi, skrip melaporkannya apa adanya.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import cv2  # noqa: E402

from app.cv.camera import CameraError, CameraStream  # noqa: E402
from app.cv.gesture import GestureClassifier  # noqa: E402
from app.cv.landmarks import HandDetector  # noqa: E402
from app.cv.overlay import draw_hud, draw_landmarks  # noqa: E402
from app.cv.stabilizer import GestureStabilizer  # noqa: E402

GESTURES = ("A", "B", "C", "D")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=4.0,
                    help="lama merekam satu gesture (detik)")
    ap.add_argument("--out", default=str(BACKEND / "data" / "calibration"),
                    help="folder keluaran JSONL")
    ap.add_argument("--label", default="", help="nama sesi (default: timestamp)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    label = args.label or datetime.now().strftime("%Y%m%d-%H%M%S")
    out_file = out_dir / f"samples-{label}.jsonl"

    print("Membuka kamera & MediaPipe…")
    try:
        cam = CameraStream()
        cam.start()
    except CameraError as exc:
        print(f"GAGAL: {exc}")
        return 1
    det = HandDetector()
    clf = GestureClassifier()
    stab = GestureStabilizer(hold_seconds=1.0, cooldown_seconds=1.5)

    print(f"Resolusi kamera : {cam.width}x{cam.height}")
    print(f"Keluaran        : {out_file}")
    print("\nCara pakai: fokuskan jendela kamera lalu tekan A, B, C atau D.")
    print("Lakukan gesture yang diminta dan tahan sampai hitungan selesai.")
    print("Ulangi tiap gesture minimal 3x agar sebarannya terlihat. Q = selesai.\n")

    counts: Counter[str] = Counter()
    recording: str | None = None
    record_until = 0.0
    saved = 0
    skipped_no_hand = 0
    frames = 0
    last_id = 0

    fh = out_file.open("w", encoding="utf-8")
    try:
        while True:
            frame, fid = cam.read()
            if frame is None or fid == last_id:
                time.sleep(0.004)
                continue
            last_id = fid
            frames += 1

            obs = det.detect(frame)
            res = clf.classify(obs) if obs is not None else None
            gesture = res.gesture if res else None
            stable = stab.update(gesture)

            now = time.time()
            if recording:
                if now >= record_until:
                    print(f"  selesai merekam {recording} "
                          f"({counts[recording]} sampel total untuk gesture ini)")
                    recording = None
                else:
                    if obs is None:
                        skipped_no_hand += 1
                    else:
                        fh.write(json.dumps({
                            "label": recording,
                            "ts": round(now, 3),
                            "handedness": obs.handedness,
                            "score": round(obs.score, 3),
                            "prediksi": gesture,
                            "landmarks": obs.as_list(),
                        }) + "\n")
                        saved += 1
                        counts[recording] += 1

            mirrored = cv2.flip(frame, 1)
            if obs is not None and res is not None:
                draw_landmarks(mirrored, obs, res)
            draw_hud(mirrored, res, stable.gesture, stable.progress,
                     stab.cooldown_remaining, 0.0,
                     stable.locked if stable.locked else None)

            hint = (f"MEREKAM {recording}  {max(0.0, record_until - now):.1f}s"
                    if recording else "Tekan A/B/C/D untuk merekam, Q untuk selesai")
            cv2.putText(mirrored, hint, (16, mirrored.shape[0] - 118),
                        cv2.FONT_HERSHEY_DUPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            cv2.putText(mirrored,
                        f"sampel: A={counts['A']} B={counts['B']} C={counts['C']} D={counts['D']}",
                        (16, mirrored.shape[0] - 96),
                        cv2.FONT_HERSHEY_DUPLEX, 0.45, (170, 220, 170), 1, cv2.LINE_AA)

            cv2.imshow("SKOMDA - Kalibrasi Gesture (A/B/C/D, Q keluar)", mirrored)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            pressed = chr(key).upper() if 32 <= key < 127 else ""
            if pressed in GESTURES:
                recording = pressed
                record_until = time.time() + args.seconds
                print(f"  merekam {pressed} selama {args.seconds:.0f} detik…")
    finally:
        fh.close()
        cam.stop()
        det.close()
        cv2.destroyAllWindows()

    print("\n=== RINGKASAN ===")
    print(f"Frame diproses   : {frames}")
    print(f"Sampel tersimpan : {saved}")
    print(f"Frame tanpa tangan saat merekam (dilewati): {skipped_no_hand}")
    print(f"Per gesture      : {dict(counts) or 'belum ada'}")
    print(f"File             : {out_file}")

    if saved == 0:
        print("\nTIDAK ADA SAMPEL TERSIMPAN. Pastikan tangan terlihat kamera dan")
        print("tombol A/B/C/D ditekan saat jendela kamera aktif.")
        try:
            out_file.unlink()
        except OSError:
            pass
        return 2
    print("\nLangkah berikutnya:")
    print(f"  .venv/Scripts/python.exe scripts/analyze_calibration.py {out_file.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
