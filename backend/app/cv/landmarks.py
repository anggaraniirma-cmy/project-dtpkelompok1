"""Pembungkus MediaPipe Tasks HandLandmarker (21 landmark).

mediapipe 1.2.2 tidak lagi menyediakan mp.solutions.hands, jadi dipakai
mediapipe.tasks.python.vision dengan model .task dan RunningMode.VIDEO.

Frame di-flip horizontal SEBELUM inferensi:
  - pengunjung melihat kamera sebagai cermin (natural untuk pameran),
  - MediaPipe mengasumsikan input sudah mirror, jadi label handedness dan
    arah "kanan" tetap konsisten.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

from .. import config

# Koneksi antar landmark untuk visualisasi (indeks MediaPipe Hand).
HAND_CONNECTIONS: tuple[tuple[int, int], ...] = (
    (0, 1), (1, 2), (2, 3), (3, 4),           # ibu jari
    (0, 5), (5, 6), (6, 7), (7, 8),           # telunjuk
    (5, 9), (9, 10), (10, 11), (11, 12),      # tengah
    (9, 13), (13, 14), (14, 15), (15, 16),    # manis
    (13, 17), (17, 18), (18, 19), (19, 20),   # kelingking
    (0, 17),                                  # sisi telapak
)

FINGER_TIPS = {"thumb": 4, "index": 8, "middle": 12, "ring": 16, "pinky": 20}


@dataclass
class HandObservation:
    """Satu hasil deteksi: 21 titik 3D (koordinat ternormalisasi 0..1)."""

    landmarks: np.ndarray            # shape (21, 3), x & y ternormalisasi
    handedness: str                  # "Right" / "Left" / "Unknown"
    score: float
    image_size: tuple[int, int]      # (w, h) frame yang dipakai inferensi
    raw: object = field(default=None, repr=False)

    def as_list(self) -> list[dict]:
        return [
            {"x": round(float(p[0]), 4), "y": round(float(p[1]), 4), "z": round(float(p[2]), 4)}
            for p in self.landmarks
        ]

    def pixel(self, idx: int) -> tuple[int, int]:
        w, h = self.image_size
        p = self.landmarks[idx]
        return int(p[0] * w), int(p[1] * h)


class HandDetector:
    """Detector tunggal, aman dipanggil dari satu thread pipeline."""

    def __init__(self, model_path: Optional[str] = None, num_hands: int = 1):
        path = str(model_path or config.MODEL_PATH)
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=path),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=num_hands,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self._lock = threading.Lock()
        self._last_ts = 0
        self.num_hands = num_hands

    def detect(self, frame_bgr: np.ndarray, timestamp_ms: Optional[int] = None) -> Optional[HandObservation]:
        """Deteksi tangan pada frame BGR. Frame di-flip di dalam (lihat docstring modul)."""
        if frame_bgr is None or frame_bgr.size == 0:
            return None
        mirrored = cv2.flip(frame_bgr, 1)
        rgb = cv2.cvtColor(mirrored, cv2.COLOR_BGR2RGB)
        rgb = np.ascontiguousarray(rgb)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        ts = int(timestamp_ms if timestamp_ms is not None else time.time() * 1000)
        with self._lock:
            # detect_for_video menuntut timestamp monoton naik.
            ts = max(ts, self._last_ts + 1)
            self._last_ts = ts
            result = self._landmarker.detect_for_video(mp_image, ts)

        if not result.hand_landmarks:
            return None
        lm = result.hand_landmarks[0]
        arr = np.array([[p.x, p.y, p.z] for p in lm], dtype=np.float32)
        handed = "Unknown"
        score = 0.0
        if getattr(result, "handedness", None):
            cat = result.handedness[0][0]
            handed = cat.category_name or "Unknown"
            score = float(cat.score)
        h, w = frame_bgr.shape[:2]
        return HandObservation(
            landmarks=arr, handedness=handed, score=score,
            image_size=(w, h), raw=result,
        )

    def close(self) -> None:
        with self._lock:
            try:
                self._landmarker.close()
            except Exception:
                pass
