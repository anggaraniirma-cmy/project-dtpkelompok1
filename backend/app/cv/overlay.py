"""Render overlay kamera: landmark, status gesture, progress hold, identitas.

Semua gambar dibuat dengan OpenCV (tanpa font eksternal) agar tidak ada
dependency tambahan dan tetap tajam. Palet mengikuti identitas SMK Telkom
Sidoarjo: merah #E4002B, navy #0B1526, putih.
"""
from __future__ import annotations

import cv2
import numpy as np

from .gesture import GestureResult
from .landmarks import HAND_CONNECTIONS, HandObservation

RED = (43, 0, 228)        # BGR dari #E4002B
NAVY = (38, 21, 11)       # BGR dari #0B1526
WHITE = (255, 255, 255)
GREY = (170, 170, 170)
GREEN = (110, 200, 60)
AMBER = (30, 180, 240)
# Warna identitas kedua pemain. Tetap dalam keluarga merah/navy sekolah:
# Player 1 memakai merah Telkom, Player 2 memakai biru teknisi (navy terang).
P1_COLOR = (60, 40, 240)      # merah-oranye terang
P2_COLOR = (250, 175, 40)     # biru langit (BGR)

FONT = cv2.FONT_HERSHEY_DUPLEX


def _rounded_box(img, p1, p2, color, alpha=0.55, radius=10):
    x1, y1 = p1
    x2, y2 = p2
    overlay = img.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
    cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)


def draw_landmarks(img: np.ndarray, obs: HandObservation, result: GestureResult) -> None:
    h, w = img.shape[:2]

    def px(i):
        p = obs.landmarks[i]
        return int(p[0] * w), int(p[1] * h)

    ok = result.gesture is not None
    line_color = GREEN if ok else (AMBER if result.hand_ok else (90, 90, 220))

    for a, b in HAND_CONNECTIONS:
        cv2.line(img, px(a), px(b), (30, 30, 30), 5, cv2.LINE_AA)
        cv2.line(img, px(a), px(b), line_color, 2, cv2.LINE_AA)

    for i in range(21):
        tip = i in (4, 8, 12, 16, 20)
        r = 6 if tip else 4
        cv2.circle(img, px(i), r + 2, (20, 20, 20), -1, cv2.LINE_AA)
        cv2.circle(img, px(i), r, WHITE if i == 0 else line_color, -1, cv2.LINE_AA)

    # Label per jari pada ujung jari: hijau = terangkat, abu = terlipat.
    for name, state in result.fingers.items():
        tip_idx = {"telunjuk": 8, "tengah": 12, "manis": 16, "kelingking": 20}[name]
        x, y = px(tip_idx)
        color = GREEN if state.extended else (120, 120, 120)
        cv2.circle(img, (x, y), 3, color, -1, cv2.LINE_AA)


def draw_hud(
    img: np.ndarray,
    result: GestureResult | None,
    stable: str | None,
    progress: float,
    cooldown: float,
    fps: float,
    locked_flash: str | None = None,
) -> None:
    h, w = img.shape[:2]
    _rounded_box(img, (10, 10), (250, 46), NAVY, 0.62, 8)
    cv2.putText(img, "SKOMDA GESTURE QUIZ", (20, 34), FONT, 0.5, WHITE, 1, cv2.LINE_AA)
    cv2.circle(img, (238, 28), 5, RED, -1, cv2.LINE_AA)

    # Panel status bawah
    panel_top = h - 96
    _rounded_box(img, (10, panel_top), (w - 10, h - 12), NAVY, 0.68, 10)

    if result is None:
        cv2.putText(img, "Tangan tidak terdeteksi", (26, panel_top + 34),
                    FONT, 0.62, GREY, 1, cv2.LINE_AA)
        cv2.putText(img, "Taruh tangan kanan di depan kamera", (26, panel_top + 62),
                    FONT, 0.48, (120, 120, 120), 1, cv2.LINE_AA)
    elif result.gesture:
        cv2.putText(img, f"{result.gesture}", (26, panel_top + 56), FONT, 1.5, GREEN, 3, cv2.LINE_AA)
        cv2.putText(img, result.label, (86, panel_top + 32), FONT, 0.5, WHITE, 1, cv2.LINE_AA)
        bar_x, bar_y, bar_w = 86, panel_top + 46, w - 130
        cv2.rectangle(img, (bar_x, bar_y), (bar_x + bar_w, bar_y + 12), (60, 60, 60), -1, cv2.LINE_AA)
        cv2.rectangle(img, (bar_x, bar_y),
                      (bar_x + int(bar_w * max(0.0, min(1.0, progress))), bar_y + 12),
                      GREEN, -1, cv2.LINE_AA)
        cv2.putText(img, "Tahan posisi untuk mengunci jawaban", (bar_x, bar_y + 34),
                    FONT, 0.43, (150, 150, 150), 1, cv2.LINE_AA)
    else:
        cv2.putText(img, "--", (26, panel_top + 56), FONT, 1.2, (100, 100, 100), 2, cv2.LINE_AA)
        cv2.putText(img, result.reason or "Gesture tidak valid", (76, panel_top + 34),
                    FONT, 0.52, AMBER, 1, cv2.LINE_AA)
        if cooldown > 0:
            cv2.putText(img, f"Tunggu {cooldown:.1f}s", (76, panel_top + 60),
                        FONT, 0.45, (130, 130, 130), 1, cv2.LINE_AA)

    if locked_flash:
        _rounded_box(img, (0, 0), (w, h), GREEN, 0.12, 0)
        cv2.putText(img, f"JAWABAN {locked_flash} TERKUNCI", (w // 2 - 190, 40),
                    FONT, 0.7, WHITE, 2, cv2.LINE_AA)

    cv2.putText(img, f"{fps:.0f} FPS", (w - 92, 34), FONT, 0.45, (160, 160, 160), 1, cv2.LINE_AA)


def placeholder(img: np.ndarray, message: str) -> np.ndarray:
    h, w = img.shape[:2]
    canvas = np.full((h, w, 3), NAVY, dtype=np.uint8)
    cv2.putText(canvas, "SKOMDA GESTURE QUIZ", (w // 2 - 150, h // 2 - 12),
                FONT, 0.7, RED, 2, cv2.LINE_AA)
    cv2.putText(canvas, message, (w // 2 - 140, h // 2 + 24),
                FONT, 0.5, (170, 170, 170), 1, cv2.LINE_AA)
    return canvas


# ---------------------------------------------------------------- 2 pemain --

def draw_players_landmarks(img: np.ndarray, obs: HandObservation, result: GestureResult | None,
                           color: tuple[int, int, int]) -> None:
    """Landmark satu pemain dengan warna identitasnya."""
    h, w = img.shape[:2]

    def px(i):
        p = obs.landmarks[i]
        return int(p[0] * w), int(p[1] * h)

    for a, b in HAND_CONNECTIONS:
        cv2.line(img, px(a), px(b), (25, 25, 25), 5, cv2.LINE_AA)
        cv2.line(img, px(a), px(b), color, 2, cv2.LINE_AA)
    for i in range(21):
        r = 6 if i in (4, 8, 12, 16, 20) else 4
        cv2.circle(img, px(i), r + 2, (20, 20, 20), -1, cv2.LINE_AA)
        cv2.circle(img, px(i), r, WHITE if i == 0 else color, -1, cv2.LINE_AA)
    if result is not None and result.gesture:
        tip = obs.pixel(12)
        cv2.putText(img, result.gesture, (tip[0] - 10, tip[1] - 24),
                    FONT, 1.0, color, 2, cv2.LINE_AA)


def draw_battle_overlay(
    img: np.ndarray,
    split,
    results: dict[int, GestureResult | None],
    progress: dict[int, float],
    gesture: dict[int, str | None],
    fps: float,
    flash: dict[int, str] | None = None,
) -> None:
    """HUD mode 2 Player: garis zona, label pemain, progres tahan per pemain.

    `split` adalah cv.players.SplitResult. Fungsi ini hanya menggambar; tidak
    ada keputusan permainan di sini.
    """
    h, w = img.shape[:2]
    mid = int(w * getattr(split, "batas", 0.5))

    # Pembatas zona + tint tipis supaya pengunjung tahu batas kiri/kanan.
    tint = img.copy()
    cv2.rectangle(tint, (0, 0), (mid, h), P1_COLOR, -1)
    cv2.rectangle(tint, (mid, 0), (w, h), P2_COLOR, -1)
    cv2.addWeighted(tint, 0.07, img, 0.93, 0, img)

    for x in range(0, h, 18):        # garis putus-putus tengah
        cv2.line(img, (mid, x), (mid, x + 9), (235, 235, 235), 2, cv2.LINE_AA)

    # Judul + FPS
    _rounded_box(img, (10, 10), (262, 46), NAVY, 0.66, 8)
    cv2.putText(img, "SKOMDA GESTURE QUIZ", (20, 34), FONT, 0.5, WHITE, 1, cv2.LINE_AA)
    cv2.circle(img, (250, 28), 5, RED, -1, cv2.LINE_AA)
    cv2.putText(img, f"{fps:.0f} FPS", (w - 92, 34), FONT, 0.45, (160, 160, 160), 1, cv2.LINE_AA)

    for p in (1, 2):
        obs = split.hands.get(p)
        color = P1_COLOR if p == 1 else P2_COLOR
        if obs is not None and results.get(p) is not None:
            draw_players_landmarks(img, obs, results.get(p), color)

        # Label pemain di atas zonanya.
        x0 = 14 if p == 1 else mid + 14
        _rounded_box(img, (x0, 58), (x0 + 168, 92), NAVY, 0.66, 8)
        cv2.circle(img, (x0 + 16, 75), 6, color, -1, cv2.LINE_AA)
        cv2.putText(img, f"PLAYER {p}", (x0 + 30, 74), FONT, 0.5, WHITE, 1, cv2.LINE_AA)

        zona_ok = split.zone_ok.get(p, True)
        r = results.get(p)
        if obs is None:
            status, scol = "Tangan belum terdeteksi", (120, 120, 120)
        elif not zona_ok:
            status, scol = "Di luar zona — geser", AMBER
        elif gesture.get(p):
            status = f"{gesture[p]}  {r.label if r else ''}"
            scol = color
        else:
            status = (r.reason if r else "—")
            scol = (200, 200, 200)
        cv2.putText(img, status[:34], (x0, 110), FONT, 0.42, scol, 1, cv2.LINE_AA)

        # Bar progres tahan per pemain (di bawah label, di atas panel bawah).
        bar_w = mid - 40 if p == 1 else w - mid - 40
        bx = 20 if p == 1 else mid + 20
        by = 122
        prog = max(0.0, min(1.0, progress.get(p, 0.0)))
        cv2.rectangle(img, (bx, by), (bx + bar_w, by + 10), (55, 55, 55), -1, cv2.LINE_AA)
        cv2.rectangle(img, (bx, by), (bx + int(bar_w * prog), by + 10), color, -1, cv2.LINE_AA)

    if flash:
        for p, letter in flash.items():
            x0 = 14 if p == 1 else mid + 14
            color = P1_COLOR if p == 1 else P2_COLOR
            _rounded_box(img, (x0, 140), (x0 + 260, 176), color, 0.75, 8)
            cv2.putText(img, f"P{p}: JAWABAN {letter} TERKUNCI", (x0 + 10, 164),
                        FONT, 0.48, (0, 0, 0), 1, cv2.LINE_AA)

    # Peringatan (tangan kiri / berdempetan) di panel bawah.
    if getattr(split, "warnings", None):
        _rounded_box(img, (10, h - 54), (w - 10, h - 12), NAVY, 0.72, 8)
        cv2.putText(img, split.warnings[0][:74], (22, h - 26),
                    FONT, 0.46, AMBER, 1, cv2.LINE_AA)
