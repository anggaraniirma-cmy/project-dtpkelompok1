"""Pembangkit landmark sintetis untuk menguji classifier tanpa kamera.

Geometri dibuat menyerupai tangan kanan nyata menghadap kamera:
  - pergelangan (0) di bawah, jari mengarah ke atas (y mengecil)
  - MCP tersusun busur horizontal
  - jari terangkat: pip/dip/tip kolinear naik dari mcp
  - jari terlipat: tip berbelok tajam ke bawah mendekati pergelangan
Tujuannya menguji ATURAN geometri, bukan menggantikan validasi di kamera.
"""
from __future__ import annotations

import numpy as np

from app.cv.landmarks import HandObservation

# posisi x MCP relatif (telunjuk..kelingking)
_MCP_X = [0.42, 0.50, 0.58, 0.65]


def make_hand(
    raised: tuple[bool, bool, bool, bool] = (True, False, False, False),
    thumb_folded: bool = True,
    handedness: str = "Right",
    wrist=(0.50, 0.85),
    scale: float = 1.0,
    rotation_deg: float = 0.0,
) -> HandObservation:
    """Buat 21 landmark ternormalisasi sesuai konfigurasi jari."""
    wrist = np.array(wrist, dtype=np.float32)
    pts = np.zeros((21, 3), dtype=np.float32)
    pts[0] = [wrist[0], wrist[1], 0.0]

    # --- ibu jari -------------------------------------------------------
    # Terlipat: melipat ke telapak (arah +x mendekati telunjuk, y sekitar mcp)
    # Terbuka : menjauh ke samping (-x) dan sedikit ke atas.
    if thumb_folded:
        # Ibu jari dilipat melintang di atas telapak: ujungnya berhenti di
        # dekat PIP telunjuk, jadi berada DI DALAM area telapak.
        pts[1] = [wrist[0] - 0.05, wrist[1] - 0.04, 0.0]
        pts[2] = [wrist[0] - 0.02, wrist[1] - 0.09, 0.0]
        pts[3] = [wrist[0] + 0.02, wrist[1] - 0.14, 0.0]
        pts[4] = [wrist[0] + 0.06, wrist[1] - 0.19, 0.0]   # dekat PIP telunjuk
    else:
        pts[1] = [wrist[0] - 0.07, wrist[1] - 0.03, 0.0]
        pts[2] = [wrist[0] - 0.14, wrist[1] - 0.08, 0.0]
        pts[3] = [wrist[0] - 0.20, wrist[1] - 0.13, 0.0]
        pts[4] = [wrist[0] - 0.26, wrist[1] - 0.17, 0.0]   # jauh dari telapak

    mcp_y = wrist[1] - 0.22
    seg = 0.075  # panjang ruas jari

    for i, (x, is_up) in enumerate(zip(_MCP_X, raised)):
        base = 5 + i * 4
        mcp = np.array([x, mcp_y], dtype=np.float32)
        pts[base] = [mcp[0], mcp[1], 0.0]
        if is_up:
            for k in range(1, 4):
                pts[base + k] = [mcp[0] + 0.004 * k * (i - 1.5), mcp[1] - seg * k, 0.0]
        else:
            # terlipat: ruas pertama naik sedikit, lalu berbelok tajam ke bawah
            pts[base + 1] = [mcp[0], mcp[1] - seg * 0.75, 0.0]
            pts[base + 2] = [mcp[0], mcp[1] - seg * 0.55, 0.0]
            pts[base + 3] = [mcp[0], mcp[1] + seg * 0.15, 0.0]

    if scale != 1.0:
        pts[:, :2] = (pts[:, :2] - wrist) * scale + wrist

    if rotation_deg:
        th = np.deg2rad(rotation_deg)
        c, s = np.cos(th), np.sin(th)
        rel = pts[:, :2] - wrist
        pts[:, 0] = rel[:, 0] * c - rel[:, 1] * s + wrist[0]
        pts[:, 1] = rel[:, 0] * s + rel[:, 1] * c + wrist[1]

    return HandObservation(
        landmarks=pts, handedness=handedness, score=0.97, image_size=(640, 480)
    )
