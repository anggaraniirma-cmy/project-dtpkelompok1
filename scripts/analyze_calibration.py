"""Analisis sampel kalibrasi → usulan ambang gesture.

Membaca JSONL dari tests/record_gesture_samples.py, lalu untuk TIAP jari
melaporkan sebaran rasio panjang & kelurusan, dipisah antara "seharusnya
terangkat" (sesuai label gesture) dan "seharusnya terlipat". Dari sebaran itu
dihitung ambang yang memisahkan keduanya dengan margin terbesar.

    .venv/Scripts/python.exe scripts/analyze_calibration.py samples-20260101-1200.jsonl

Bila jarak antar kelas tidak lebar, skrip mengatakannya — bukan memaksakan
ambang yang terlihat bagus di atas kertas tetapi rapuh di kamera.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import numpy as np  # noqa: E402

from app.cv.gesture import FINGER_JOINTS, GestureClassifier  # noqa: E402

# Jari mana yang terangkat untuk tiap label gesture.
TERANGKAT = {
    "A": (True, False, False, False),
    "B": (True, True, False, False),
    "C": (True, True, True, False),
    "D": (True, True, True, True),
}
NAMES = list(FINGER_JOINTS.keys())


def persen(vals, q):
    return float(np.percentile(vals, q)) if len(vals) else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="nama file di backend/data/calibration atau path penuh")
    ap.add_argument("--json", action="store_true", help="keluarkan ringkasan JSON saja")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        candidate = BACKEND / "data" / "calibration" / args.file
        if candidate.exists():
            path = candidate
        else:
            print(f"File tidak ditemukan: {args.file}")
            return 1

    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not rows:
        print("File kosong / tidak ada sampel valid.")
        return 1

    clf = GestureClassifier()
    per_label: dict[str, int] = {}
    # kumpulan nilai per (jari, kelas)
    ratios = {n: {"up": [], "down": []} for n in NAMES}
    straight = {n: {"up": [], "down": []} for n in NAMES}
    thumbs_folded: list[float] = []
    thumbs_open: list[float] = []
    salah_prediksi = 0
    kiri = 0

    for r in rows:
        label = r.get("label")
        if label not in TERANGKAT:
            continue
        per_label[label] = per_label.get(label, 0) + 1
        if r.get("handedness") == "Left":
            kiri += 1
        lm = np.array([[p["x"], p["y"], p["z"]] for p in r["landmarks"]], dtype=np.float32)
        fingers = clf.evaluate_fingers(lm)
        palm_w = clf.palm_width(lm)
        abd, _ = clf.thumb_features(lm, palm_w)
        (thumbs_folded if abd <= 0.72 else thumbs_open).append(abd)

        for name, should_up in zip(NAMES, TERANGKAT[label]):
            key = "up" if should_up else "down"
            ratios[name][key].append(fingers[name].ratio)
            straight[name][key].append(fingers[name].straightness)

        obs_pred = _classify_with(clf, lm, r.get("handedness", "Unknown"))
        if obs_pred != label:
            salah_prediksi += 1

    total = sum(per_label.values())
    if not total:
        print("Tidak ada sampel berlabel A/B/C/D.")
        return 1

    ringkas = {
        "file": path.name,
        "total_sampel": total,
        "per_label": per_label,
        "terdeteksi_tangan_kiri": kiri,
        "prediksi_salah_dengan_ambang_sekarang": salah_prediksi,
        "akurasi_sekarang_persen": round(100 * (total - salah_prediksi) / total, 1),
        "ambang_usulan": {},
        "jari": {},
    }

    print(f"File            : {path.name}")
    print(f"Total sampel    : {total}  {per_label}")
    print(f"Tangan kiri     : {kiri} frame (seharusnya 0 bila disiplin tangan kanan)")
    print(f"Akurasi ambang sekarang: {ringkas['akurasi_sekarang_persen']}% "
          f"({total - salah_prediksi}/{total} benar)")
    print()

    ok_semua = True
    for name in NAMES:
        up_r, down_r = ratios[name]["up"], ratios[name]["down"]
        up_s, down_s = straight[name]["up"], straight[name]["down"]
        print(f"--- {name} ---")
        if not up_r:
            print("  (tidak ada sampel 'terangkat' untuk jari ini di data)\n")
            continue
        # Ambang rasio di tengah celah p5 kelas terangkat dan p95 kelas terlipat.
        lo_up = persen(up_r, 5)
        hi_down = persen(down_r, 95) if down_r else float("nan")
        lo_straight = persen(up_s, 5)
        hi_straight_down = persen(down_s, 95) if down_s else float("nan")

        print(f"  rasio terangkat : p5={lo_up:.3f} median={persen(up_r,50):.3f} p95={persen(up_r,95):.3f}")
        if down_r:
            print(f"  rasio terlipat  : p5={persen(down_r,5):.3f} median={persen(down_r,50):.3f} p95={hi_down:.3f}")
        print(f"  kelurusan angkt : p5={lo_straight:.3f} median={persen(up_s,50):.3f}")
        if down_s:
            print(f"  kelurusan lipat : p95={hi_straight_down:.3f}")

        # Usulan: titik tengah celah, dibulatkan 2 desimal.
        if not np.isnan(hi_down):
            if lo_up > hi_down:
                usul_rasio = round((lo_up + hi_down) / 2, 2)
                print(f"  celah rasio     : {hi_down:.3f} (lipat) … {lo_up:.3f} (angkat) — LEBAR")
            else:
                usul_rasio = round((lo_up + hi_down) / 2, 2)
                ok_semua = False
                print(f"  celah rasio     : TIDAK ADA PEMISAH JELAS "
                      f"(lipat p95={hi_down:.3f} ≥ angkat p5={lo_up:.3f})")
            ringkas["jari"][name] = {"rasio_usulan": usul_rasio,
                                     "celah_lebar": bool(lo_up > hi_down)}
        if not np.isnan(hi_straight_down) and lo_straight <= hi_straight_down:
            ok_semua = False
            print(f"  PERINGATAN      : kelurusan juga tidak memisah bersih")
        print()

    if thumbs_folded and thumbs_open:
        f95 = persen(thumbs_folded, 95)
        o5 = persen(thumbs_open, 5)
        print(f"--- ibu jari ---")
        print(f"  terlipat: p95={f95:.3f} (n={len(thumbs_folded)})")
        print(f"  terbuka : p5={o5:.3f} (n={len(thumbs_open)})")
        if f95 < o5:
            print(f"  usulan ambang terlipat <= {round((f95 + o5) / 2, 2)}")
            ringkas["ambang_usulan"]["thumb_folded_max"] = round((f95 + o5) / 2, 2)
        else:
            ok_semua = False
            print("  PERINGATAN: ibu jari terlipat & terbuka tidak terpisah bersih")
    else:
        print("--- ibu jari ---")
        print("  butuh sampel dengan ibu jari terlipat DAN terbuka untuk mengukur ambang.")

    print()
    if ok_semua:
        print("KESIMPULAN: data punya pemisahan kelas yang jelas. Terapkan ambang di atas")
        print("pada backend/app/cv/gesture.py lalu jalankan ulang pytest + uji kamera.")
    else:
        print("KESIMPULAN: sebagian jari tidak terpisah bersih. Kemungkinan penyebab:")
        print("  - sudut/rotasi tangan yang ekstrem saat merekam")
        print("  - label tertukar (mis. menekan D tapi membentuk C)")
        print("  - jari 'terlipat' masih terlihat lurus karena sudut kamera dari atas")
        print("Rekam ulang dari jarak & sudut seperti pengunjung sebenarnya.")

    if args.json:
        print(json.dumps(ringkas, indent=2, ensure_ascii=False))
    return 0


def _classify_with(clf: GestureClassifier, lm: np.ndarray, handedness: str) -> str | None:
    """Klasifikasi memakai objek HandObservation sementara (tanpa impor ulang)."""
    from app.cv.landmarks import HandObservation
    obs = HandObservation(landmarks=lm, handedness=handedness, score=1.0,
                          image_size=(640, 480))
    return clf.classify(obs).gesture


if __name__ == "__main__":
    raise SystemExit(main())
