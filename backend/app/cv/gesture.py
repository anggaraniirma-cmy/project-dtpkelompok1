"""Klasifikasi gesture A/B/C/D secara rule-based dari 21 landmark.

BUKAN menghitung jumlah jari. Setiap jari dievaluasi sendiri dengan dua
ukuran geometri yang invarian terhadap rotasi & jarak ke kamera:

1. Rasio panjang: |tip - wrist| / |pip - wrist|
   Jari terlipat akan melipat ke telapak sehingga tip mendekati pergelangan.
2. Kelurusan: cos sudut antara (pip - mcp) dan (tip - pip)
   Jari lurus ~1.0, jari tertekuk menurun tajam.

Jari dianggap TERANGKAT hanya bila kedua ukuran lolos ambang. Ambang
dinormalisasi oleh lebar telapak (|mcp telunjuk - mcp kelingking|) sehingga
tidak bergantung pada ukuran tangan di frame.

Ibu jari punya aturan sendiri karena arah tekuknya berbeda: dianggap
TERLIPAT bila ujungnya tertarik ke telapak (dekat garis telunjuk) dan
abduksinya kecil.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .landmarks import HandObservation

# Landmark index MediaPipe
WRIST = 0
THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4
INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP = 5, 6, 7, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9, 10, 11, 12
RING_MCP, RING_PIP, RING_DIP, RING_TIP = 13, 14, 15, 16
PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP = 17, 18, 19, 20

# jari: (mcp, pip, dip, tip, ambang rasio panjang)
FINGER_JOINTS = {
    "telunjuk": (INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP, 1.22),
    "tengah": (MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP, 1.22),
    "manis": (RING_MCP, RING_PIP, RING_DIP, RING_TIP, 1.18),
    "kelingking": (PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP, 1.14),
}

GESTURE_MAP = {
    (True, False, False, False): "A",
    (True, True, False, False): "B",
    (True, True, True, False): "C",
    (True, True, True, True): "D",
}

GESTURE_LABEL = {
    "A": "Satu jari — Telunjuk",
    "B": "Dua jari — Telunjuk + Tengah",
    "C": "Tiga jari — Telunjuk + Tengah + Manis",
    "D": "Empat jari — Semua jari terbuka",
}


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-8 else v * 0.0


def _dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))


@dataclass
class FingerState:
    name: str
    extended: bool
    ratio: float          # |tip-wrist| / |pip-wrist|
    straightness: float   # cos sudut di PIP, -1..1


@dataclass
class GestureResult:
    gesture: Optional[str]          # "A"/"B"/"C"/"D" atau None
    reason: str                     # alasan bila tidak valid (untuk overlay/debug)
    fingers: dict[str, FingerState]
    thumb_folded: bool
    thumb_ratio: float
    palm_width: float
    hand_ok: bool = True
    label: str = ""


class GestureClassifier:
    """Stateless: menerima satu observasi, mengembalikan gesture."""

    def __init__(
        self,
        straight_min: float = 0.55,
        thumb_open_min: float = 0.85,
        thumb_folded_max: float = 0.72,
    ):
        # Ambang absolut: cos sudut minimal agar jari dianggap lurus.
        self.straight_min = straight_min
        # Rasio abduksi ibu jari (|tip4 - mcp5| / palm_width).
        self.thumb_open_min = thumb_open_min
        self.thumb_folded_max = thumb_folded_max

    # -- fitur -------------------------------------------------------------
    @staticmethod
    def palm_width(lm: np.ndarray) -> float:
        """Lebar telapak; skala acuan agar ambang bebas ukuran tangan."""
        w = _dist(lm[INDEX_MCP], lm[PINKY_MCP])
        return w if w > 1e-6 else 1.0

    def evaluate_fingers(self, lm: np.ndarray) -> dict[str, FingerState]:
        wrist = lm[WRIST]
        out: dict[str, FingerState] = {}
        for name, (mcp, pip, dip, tip, _rth) in FINGER_JOINTS.items():
            tip_d = _dist(lm[tip], wrist)
            pip_d = _dist(lm[pip], wrist)
            ratio = tip_d / pip_d if pip_d > 1e-6 else 0.0
            v1 = _unit(lm[pip] - lm[mcp])
            v2 = _unit(lm[tip] - lm[pip])
            straight = float(np.dot(v1, v2))
            out[name] = FingerState(name=name, extended=False, ratio=ratio, straightness=straight)
        return out

    def thumb_features(self, lm: np.ndarray, palm_w: float) -> tuple[float, float]:
        """(abduksi, kelurusan) ibu jari.

        abduksi = |tip ibu jari - pusat telapak| / lebar telapak
          Ibu jari terlipat dilipat masuk ke telapak sehingga ujungnya berada
          DI DALAM area telapak (nilai kecil). Ibu jari terbuka menjulur ke
          samping menjauhi telapak (nilai besar). Ukuran relatif terhadap
          lebar telapak -> bebas jarak kamera dan rotasi.
        kelurusan = cos sudut di IP (2-3-4)
        """
        palm_center = np.mean(lm[[INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP]], axis=0)
        abd = _dist(lm[THUMB_TIP], palm_center) / palm_w
        v1 = _unit(lm[THUMB_IP] - lm[THUMB_MCP])
        v2 = _unit(lm[THUMB_TIP] - lm[THUMB_IP])
        return abd, float(np.dot(v1, v2))

    # -- klasifikasi -------------------------------------------------------
    def classify(self, obs: HandObservation, require_right: bool = True) -> GestureResult:
        lm = obs.landmarks
        palm_w = self.palm_width(lm)
        fingers = self.evaluate_fingers(lm)
        thumb_abd, thumb_straight = self.thumb_features(lm, palm_w)

        states: list[bool] = []
        for name, (_mcp, _pip, _dip, _tip, r_th) in FINGER_JOINTS.items():
            f = fingers[name]
            extended = f.ratio >= r_th and f.straightness >= self.straight_min
            f.extended = extended
            states.append(extended)

        # Ibu jari: terlipat bila abduksi rendah (menempel telapak).
        thumb_folded = thumb_abd <= self.thumb_folded_max

        def make(gesture, reason, hand_ok=True):
            return GestureResult(
                gesture=gesture, reason=reason, fingers=fingers,
                thumb_folded=thumb_folded, thumb_ratio=thumb_abd,
                palm_width=palm_w, hand_ok=hand_ok,
                label=GESTURE_LABEL.get(gesture, ""),
            )

        if require_right and obs.handedness == "Left":
            return make(None, "Itu tangan kiri — gunakan tangan kanan", hand_ok=False)

        if not thumb_folded:
            return make(None, "Lipat ibu jari")

        key = tuple(states)
        if key in GESTURE_MAP:
            return make(GESTURE_MAP[key], "")

        # Diagnosa untuk kombinasi di luar aturan.
        raised = [n for n, s in zip(FINGER_JOINTS.keys(), states) if s]
        if not raised:
            return make(None, "Angkat telunjuk untuk memilih A")
        if not states[0]:
            return make(None, "Telunjuk harus terangkat")
        gaps = [i for i in range(3) if key[i] and not key[i + 1]]
        if gaps:
            return make(None, "Jari harus berurutan dari telunjuk")
        return make(None, "Gesture tidak dikenali")


def classifier_from_config() -> GestureClassifier:
    from .. import config
    return GestureClassifier()
