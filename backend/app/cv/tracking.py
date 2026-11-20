"""Seleksi tangan & tracking identitas antar frame.

Dua masalah yang diselesaikan modul ini (keduanya nyata di pameran yang ramai):

1. TANGAN LATAR BELAKANG.
   MediaPipe mengembalikan semua tangan yang terlihat, tanpa tahu siapa
   pemiliknya. `HandFilter` menolak kandidat yang jelas bukan pemain:
     * lebar telapak terlalu kecil  -> orangnya jauh di belakang;
     * pusat tangan di luar ROI     -> tangan yang terangkat di luar area main;
     * skor keyakinan di bawah ambang.
   Penolakan dicatat sebagai ALASAN (bukan dibuang diam-diam) supaya UI bisa
   memberi tahu pengunjung mengapa tangannya tidak terbaca.

2. IDENTITAS YANG BERGANTI TIAP FRAME.
   Hasil MediaPipe tidak punya ID; urutannya juga tidak stabil. `HandTracker`
   memberi ID sendiri dari kedekatan posisi antar frame (IoU lalu jarak pusat),
   sehingga satu tangan yang sama tetap punya ID yang sama walau urutan
   deteksinya berubah. Track yang hilang sesaat (< `max_miss_seconds`) tidak
   langsung dibuang — ini yang membuat identitas pemain tahan terhadap
   okulasi singkat.

Modul ini murni geometri + waktu (jam bisa disuntik) sehingga bisa diuji tanpa
kamera.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterable, Optional

import numpy as np

from .landmarks import HandObservation

# Indeks telapak: pergelangan + 4 pangkal jari.
_PALM_IDX = (0, 5, 9, 13, 17)
# Lebar telapak = jarak pangkal telunjuk ke pangkal kelingking.
_INDEX_MCP, _PINKY_MCP = 5, 17


# ------------------------------------------------------------------ geometri
def palm_width_norm(obs: HandObservation) -> float:
    """Lebar telapak dalam koordinat ternormalisasi (0..1 lebar frame)."""
    pts = obs.landmarks
    return float(abs(float(pts[_INDEX_MCP][0]) - float(pts[_PINKY_MCP][0])))


def centroid(obs: HandObservation) -> tuple[float, float]:
    """Pusat tangan (rata-rata 21 landmark) pada frame ternormalisasi."""
    pts = obs.landmarks[:, :2]
    return float(np.mean(pts[:, 0])), float(np.mean(pts[:, 1]))


def bbox(obs: HandObservation) -> tuple[float, float, float, float]:
    """Kotak pembatas (x0, y0, x1, y1) ternormalisasi."""
    pts = obs.landmarks[:, :2]
    return (float(np.min(pts[:, 0])), float(np.min(pts[:, 1])),
            float(np.max(pts[:, 0])), float(np.max(pts[:, 1])))


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > 1e-9 else 0.0


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


# --------------------------------------------------------------------- filter
@dataclass
class FilterPenolakan:
    """Ringkasan kandidat yang ditolak satu frame (untuk status & overlay)."""

    terlalu_kecil: int = 0
    luar_area: int = 0
    skor_rendah: int = 0

    @property
    def total(self) -> int:
        return self.terlalu_kecil + self.luar_area + self.skor_rendah

    def as_dict(self) -> dict[str, int]:
        return {
            "terlalu_kecil": self.terlalu_kecil,
            "luar_area": self.luar_area,
            "skor_rendah": self.skor_rendah,
        }


class HandFilter:
    """Gerbang kualitas kandidat tangan. Stateless, aman diuji langsung."""

    def __init__(
        self,
        roi: tuple[float, float, float, float] = (0.02, 0.05, 0.98, 1.0),
        min_palm_width: float = 0.055,
        min_score: float = 0.5,
    ):
        self.roi = roi
        self.min_palm_width = min_palm_width
        self.min_score = min_score

    def alasan_tolak(self, obs: HandObservation) -> Optional[str]:
        """None bila lolos; selain itu kode alasan yang stabil untuk UI."""
        if obs is None:
            return "luar_area"
        cx, cy = centroid(obs)
        x0, y0, x1, y1 = self.roi
        if not (x0 <= cx <= x1 and y0 <= cy <= y1):
            return "luar_area"
        if palm_width_norm(obs) < self.min_palm_width:
            return "terlalu_kecil"
        if obs.score and obs.score < self.min_score:
            return "skor_rendah"
        return None

    def saring(
        self, observations: Iterable[HandObservation]
    ) -> tuple[list[HandObservation], FilterPenolakan]:
        lolos: list[HandObservation] = []
        tolak = FilterPenolakan()
        for obs in observations or []:
            alasan = self.alasan_tolak(obs)
            if alasan is None:
                lolos.append(obs)
            elif alasan == "terlalu_kecil":
                tolak.terlalu_kecil += 1
            elif alasan == "skor_rendah":
                tolak.skor_rendah += 1
            else:
                tolak.luar_area += 1
        return lolos, tolak


# -------------------------------------------------------------------- tracker
@dataclass
class TrackedHand:
    """Satu tangan dengan identitas yang bertahan antar frame."""

    id: int
    obs: HandObservation
    first_seen: float
    last_seen: float
    hits: int = 1
    misses: int = 0

    @property
    def palm_x(self) -> float:
        return float(np.mean(self.obs.landmarks[list(_PALM_IDX), 0]))

    def as_dict(self) -> dict:
        cx, cy = centroid(self.obs)
        return {
            "id": self.id,
            "pusat": [round(cx, 3), round(cy, 3)],
            "lebar_telapak": round(palm_width_norm(self.obs), 3),
            "handedness": self.obs.handedness,
            "skor": round(self.obs.score, 3),
        }


class HandTracker:
    """Tracker sederhana (greedy IoU + jarak pusat). Clock bisa disuntik."""

    def __init__(
        self,
        max_miss_seconds: float = 0.8,
        dist_max: float = 0.30,
        iou_min: float = 0.10,
        clock=time.monotonic,
    ):
        self.max_miss_seconds = max_miss_seconds
        self.dist_max = dist_max
        self.iou_min = iou_min
        # Saat ada BEBERAPA kandidat, pencocokan berbasis jarak harus lebih
        # ketat: dua orang berbeda bisa berdiri berdekatan, dan jarak 0.30
        # frame terlalu longgar untuk memisahkan mereka.
        self.dist_max_multi = min(dist_max, 0.18)
        # Batas rasio ukuran telapak. Tangan yang jauh (kecil) tidak boleh
        # mewarisi identitas tangan pemain yang besar walau posisinya sama.
        self.rasio_ukuran_min = 0.60
        self.rasio_ukuran_max = 1.60
        self._clock = clock
        self._tracks: dict[int, TrackedHand] = {}
        self._next_id = 1

    # -- lifecycle ---------------------------------------------------------
    def reset(self) -> None:
        self._tracks.clear()
        self._next_id = 1

    @property
    def tracks(self) -> list[TrackedHand]:
        return list(self._tracks.values())

    # -- pemrosesan --------------------------------------------------------
    def update(
        self, observations: Iterable[HandObservation], now: Optional[float] = None
    ) -> list[TrackedHand]:
        """Cocokkan kandidat frame ini dengan track lama; kembalikan track aktif."""
        now = self._clock() if now is None else now
        kandidat = [o for o in (observations or []) if o is not None]

        # Buang track yang sudah terlalu lama hilang.
        for tid in list(self._tracks):
            if now - self._tracks[tid].last_seen > self.max_miss_seconds:
                del self._tracks[tid]

        pasangan: list[tuple[float, int, int]] = []   # (skor, track_id, index)
        batas_jarak = self.dist_max if len(kandidat) == 1 else self.dist_max_multi
        for tid, tr in self._tracks.items():
            tb = bbox(tr.obs)
            tc = centroid(tr.obs)
            lebar_track = palm_width_norm(tr.obs)
            for i, obs in enumerate(kandidat):
                lebar_obs = palm_width_norm(obs)
                if lebar_track > 1e-6 and lebar_obs > 1e-6:
                    rasio = lebar_obs / lebar_track
                    if not (self.rasio_ukuran_min <= rasio <= self.rasio_ukuran_max):
                        # Ukuran terlalu berbeda -> orang/jarak berbeda.
                        continue
                ob = bbox(obs)
                oc = centroid(obs)
                nilai = iou(tb, ob)
                jarak = distance(tc, oc)
                if nilai < self.iou_min:
                    if jarak > batas_jarak:
                        continue
                    # Dekat tetapi bbox tidak bertumpuk (tangan bergerak cepat).
                    nilai = max(0.0, 0.5 * (1 - jarak / max(batas_jarak, 1e-6)))
                # Label tangan yang bertentangan menurunkan kecocokan, tetapi
                # tidak membatalkannya: label MediaPipe bisa berubah saat tangan
                # miring, dan identitas pemain tidak boleh ikut berubah.
                if (tr.obs.handedness != "Unknown" and obs.handedness != "Unknown"
                        and tr.obs.handedness != obs.handedness):
                    nilai *= 0.5
                pasangan.append((nilai, tid, i))

        pasangan.sort(reverse=True)
        dipakai_track: set[int] = set()
        dipakai_idx: set[int] = set()
        aktif_ids: set[int] = set()
        for nilai, tid, i in pasangan:
            if nilai <= 0 or tid in dipakai_track or i in dipakai_idx:
                continue
            tr = self._tracks[tid]
            tr.obs = kandidat[i]
            tr.last_seen = now
            tr.misses = 0
            tr.hits += 1
            dipakai_track.add(tid)
            dipakai_idx.add(i)
            aktif_ids.add(tid)

        # Sisa kandidat: track baru.
        for i, obs in enumerate(kandidat):
            if i in dipakai_idx:
                continue
            tid = self._next_id
            self._next_id += 1
            self._tracks[tid] = TrackedHand(
                id=tid, obs=obs, first_seen=now, last_seen=now
            )
            aktif_ids.add(tid)

        # PENTING: jangan memilih track aktif dengan membandingkan timestamp
        # (`last_seen == now`). Resolusi time.monotonic() di Windows ~15 ms,
        # sehingga dua frame berurutan bisa punya `now` yang sama PERSIS dan
        # track yang sudah hilang ikut dianggap aktif.
        aktif = [self._tracks[tid] for tid in aktif_ids if tid in self._tracks]
        # Urutkan stabil: kiri ke kanan (bukan urutan deteksi MediaPipe).
        aktif.sort(key=lambda tr: tr.palm_x)
        return aktif

    def alive(self, track_id: Optional[int], now: Optional[float] = None) -> bool:
        """Apakah track masih dianggap ada (termasuk toleransi hilang sesaat)?"""
        if track_id is None or track_id not in self._tracks:
            return False
        now = self._clock() if now is None else now
        return (now - self._tracks[track_id].last_seen) <= self.max_miss_seconds
