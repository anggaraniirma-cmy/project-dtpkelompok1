"""Pemisahan pemain pada mode 2 Player Battle.

Satu kamera, dua pengunjung berdampingan. MediaPipe mengembalikan daftar tangan
TANPA identitas pemain, dan urutannya tidak stabil antar frame. Modul ini
menentukan tangan mana milik Player 1 dan Player 2 berdasarkan POSISI, bukan
urutan deteksi.

Aturan yang dipakai:

1. Hanya tangan kanan (atau label lemah "Unknown") yang boleh menjawab.
   Tangan kiri dipisahkan ke `wrong_hand` agar bisa ditampilkan sebagai
   peringatan, bukan diam-diam dipakai.
2. Bila terdeteksi DUA tangan yang sah:
     - tangan paling KIRI  -> Player 1 (zona kiri)
     - tangan paling KANAN -> Player 2 (zona kanan)
   Urutan ini deterministik sehingga tidak pernah ada frame di mana satu tangan
   dipakai dua pemain, dan tidak ada "tangan pertama = Player 1" yang permanen.
3. Bila hanya SATU tangan sah: tangan masuk ke pemain pemilik zonanya. Pemain
   lain berstatus "tangan tidak terdeteksi" (bukan jawaban salah).
4. `zone_ok` menandai apakah tangan benar-benar berada di zona pemiliknya.
   Bila kedua pemain berdiri terlalu berdempetan (dua tangan di satu sisi),
   permainan tetap jalan tetapi UI menampilkan indikator zona salah.

Modul ini murni geometri (tanpa kamera) sehingga bisa diuji langsung.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterable, Optional

import numpy as np

from .landmarks import HandObservation

# Batas kiri/kanan zona pada koordinat ternormalisasi frame yang SUDAH
# dicerminkan (0 = tepi kiri tampilan, 1 = tepi kanan tampilan).
ZONA_BATAS = 0.5

# Jarak horizontal minimum antar dua tangan agar dianggap dua orang berbeda.
# Di bawah ini kemungkinan besar dua tangan dari satu orang (deteksi ganda),
# atau kedua pemain benar-benar berdiri terlalu rapat.
JARAK_MIN_PEMAIN = 0.10

# Label handedness yang boleh menjawab. "Unknown" muncul saat tangan miring
# sehingga model ragu; menolaknya membuat pengunjung tertahan tanpa alasan.
HANDEDNESS_SAH = ("Right", "Unknown")

# Indeks landmark yang dipakai sebagai pusat tangan: pangkal jari.
_PALM_IDX = (0, 5, 9, 13, 17)


def palm_x(obs: HandObservation) -> float:
    """Posisi horizontal telapak (0..1) pada frame yang sudah dicerminkan."""
    pts = obs.landmarks[_PALM_IDX, 0]
    return float(np.mean(pts))


def palm_center(obs: HandObservation) -> tuple[float, float]:
    pts = obs.landmarks[_PALM_IDX, :2]
    cx, cy = np.mean(pts, axis=0)
    return float(cx), float(cy)


def zona_dari_x(x: float, batas: float = ZONA_BATAS) -> int:
    """1 = zona kiri (Player 1), 2 = zona kanan (Player 2)."""
    return 1 if x < batas else 2


@dataclass
class SplitResult:
    """Hasil pemisahan satu frame."""

    hands: dict[int, HandObservation] = field(default_factory=dict)
    palm_x: dict[int, float] = field(default_factory=dict)
    zone_ok: dict[int, bool] = field(default_factory=dict)
    # Batas zona yang dipakai, supaya overlay menggambar garis di posisi yang
    # sama dengan logika pembagian (bukan hardcode 0.5 di dua tempat).
    batas: float = ZONA_BATAS
    # Tangan kanan yang terdeteksi tetapi tidak mendapat pemain (mis. dua tangan
    # di satu zona dan pemain lainnya sudah terisi).
    unassigned: list[HandObservation] = field(default_factory=list)
    # Tangan kiri / label tidak sah: tidak boleh menjawab.
    wrong_hand: list[HandObservation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # --- identitas (dipakai PlayerTracker; kosong untuk PlayerSplitter) -----
    # id track per pemain, mis. {1: 7, 2: 9}
    track_id: dict[int, int] = field(default_factory=dict)
    # apakah pemain benar-benar punya tangan di frame ini
    terdeteksi: dict[int, bool] = field(default_factory=dict)
    # slot dipertahankan karena tangan baru hilang sesaat (bukan pemain baru)
    memori: dict[int, bool] = field(default_factory=dict)
    # jumlah kandidat mentah sebelum difilter (diisi pipeline, untuk status)
    kandidat: int = 0

    def terisi(self, player: int) -> bool:
        return player in self.hands


class PlayerSplitter:
    """Stateless: satu frame masuk, pembagian pemain keluar."""

    def __init__(
        self,
        batas: float = ZONA_BATAS,
        jarak_min: float = JARAK_MIN_PEMAIN,
    ):
        self.batas = batas
        self.jarak_min = jarak_min

    def assign(self, observations: Iterable[HandObservation]) -> SplitResult:
        out = SplitResult(batas=self.batas)
        sah: list[HandObservation] = []
        for obs in observations or []:
            if obs is None:
                continue
            if obs.handedness in HANDEDNESS_SAH:
                sah.append(obs)
            else:
                out.wrong_hand.append(obs)

        if out.wrong_hand:
            out.warnings.append(
                "Tangan kiri terdeteksi — setiap pemain memakai tangan KANAN."
            )

        if not sah:
            out.warnings.append("Tidak ada tangan kanan di depan kamera.")
            return out

        xs = {id(o): palm_x(o) for o in sah}
        sah.sort(key=lambda o: xs[id(o)])

        if len(sah) >= 2:
            # Dua tangan: kiri -> P1, kanan -> P2. Ambil dua yang paling
            # berjauhan bila MediaPipe mengembalikan lebih dari dua (tidak
            # mungkin dengan num_hands=2, tetapi dijaga agar aman).
            kiri, kanan = sah[0], sah[-1]
            if xs[id(kanan)] - xs[id(kiri)] < self.jarak_min:
                out.warnings.append(
                    "Kedua tangan terlalu berdekatan — berdiri agak ke samping."
                )
                # Tetap pakai satu tangan saja (yang paling dekat zonanya) agar
                # tidak ada satu tangan menjawab dua pemain.
                target = zona_dari_x(xs[id(kiri)], self.batas)
                self._pasang(out, target, kiri, xs[id(kiri)], True)
                out.unassigned.append(kanan)
                return out

            self._pasang(out, 1, kiri, xs[id(kiri)], zona_dari_x(xs[id(kiri)], self.batas) == 1)
            self._pasang(out, 2, kanan, xs[id(kanan)], zona_dari_x(xs[id(kanan)], self.batas) == 2)
            for p, ok in out.zone_ok.items():
                if not ok:
                    out.warnings.append(
                        f"Player {p} di luar zonanya — geser ke "
                        f"{'kiri' if p == 1 else 'kanan'} kamera."
                    )
            return out

        # Satu tangan: masuk ke pemain pemilik zonanya.
        obs = sah[0]
        x = xs[id(obs)]
        player = zona_dari_x(x, self.batas)
        self._pasang(out, player, obs, x, True)
        return out

    @staticmethod
    def _pasang(out: SplitResult, player: int, obs: HandObservation, x: float, zone_ok: bool) -> None:
        out.hands[player] = obs
        out.palm_x[player] = x
        out.zone_ok[player] = zone_ok

    @staticmethod
    def ringkas(split: SplitResult) -> dict:
        """Ringkasan JSON-able untuk status WebSocket / pengujian."""
        return {
            "pemain_terdeteksi": sorted(split.hands.keys()),
            "palm_x": {str(p): round(v, 4) for p, v in split.palm_x.items()},
            "zona_ok": {str(p): bool(v) for p, v in split.zone_ok.items()},
            "tangan_kiri": len(split.wrong_hand),
            "peringatan": list(split.warnings),
        }


def observation_palsu(x: float, handedness: str = "Right", y: float = 0.5) -> HandObservation:
    """Bantu pengujian: tangan dengan pusat telapak di x tertentu."""
    pts = np.zeros((21, 3), dtype=np.float32)
    for i, idx in enumerate(_PALM_IDX):
        pts[idx] = [x, y, 0.0]
    return HandObservation(
        landmarks=pts, handedness=handedness, score=0.9, image_size=(640, 480)
    )


# --------------------------------------------------------------- stateful ---
class PlayerTracker:
    """Pemisah pemain yang MENGINGAT identitas antar frame.

    `PlayerSplitter` di atas hanya melihat satu frame, sehingga:
      * saat satu tangan hilang sedetik, pemain itu langsung "kosong" dan
        tangan orang lain bisa masuk ke slotnya;
      * saat dua tangan menyilang, identitas bisa tertukar.

    Kelas ini menambatkan slot pemain ke ID track (dari cv.tracking), bukan ke
    posisi x mentah:

      * selama track pemiliknya masih hidup, slot tetap miliknya walau tangan
        bergeser ke zona lain (zona hanya jadi peringatan, BUKAN alasan
        menukar pemain);
      * bila tangan hilang < `memory_seconds`, slotnya ditahan (status
        "memori") sehingga pemain tidak langsung kehilangan identitas;
      * tangan baru hanya boleh mengisi slot yang benar-benar kosong, menurut
        zona tempatnya muncul. Tangan ekstra tidak pernah merebut slot terisi.

    Jaminan lama tetap berlaku: satu tangan tidak bisa menjawab dua pemain,
    tangan kiri tidak boleh menjawab, dan dua tangan di satu sisi tidak
    membuat pemain fiktif.
    """

    def __init__(
        self,
        batas: float = ZONA_BATAS,
        jarak_min: float = JARAK_MIN_PEMAIN,
        memory_seconds: float = 0.9,
        clock=time.monotonic,
    ):
        self.batas = batas
        self.jarak_min = jarak_min
        self.memory_seconds = memory_seconds
        self._clock = clock
        self._slot: dict[int, Optional[int]] = {1: None, 2: None}
        self._last_seen: dict[int, float] = {1: float("-inf"), 2: float("-inf")}

    def reset(self) -> None:
        """Sesi/pertandingan baru: lupakan identitas lama."""
        self._slot = {1: None, 2: None}
        self._last_seen = {1: float("-inf"), 2: float("-inf")}

    # -- inti --------------------------------------------------------------
    def assign(self, tracked, now: Optional[float] = None) -> SplitResult:
        """Tentukan pemain dari daftar TrackedHand frame ini."""
        now = self._clock() if now is None else now
        out = SplitResult(batas=self.batas)
        out.kandidat = len(tracked or [])

        sah, kiri = [], []
        for tr in tracked or []:
            if tr.obs.handedness in HANDEDNESS_SAH:
                sah.append(tr)
            else:
                kiri.append(tr)
        out.wrong_hand = [tr.obs for tr in kiri]
        if kiri:
            out.warnings.append(
                "Tangan kiri terdeteksi — setiap pemain memakai tangan KANAN."
            )

        dipakai: set[int] = set()

        # 1) Pemilik slot yang masih terlihat di frame ini mempertahankan slot.
        for p in (1, 2):
            tid = self._slot[p]
            if tid is None:
                continue
            cocok = next((tr for tr in sah if tr.id == tid and tr.id not in dipakai), None)
            if cocok is not None:
                self._ikat(out, p, cocok, now)
                dipakai.add(tid)
            elif now - self._last_seen[p] <= self.memory_seconds:
                # Tangan hilang sesaat: slot ditahan, jangan diberikan ke orang lain.
                out.memori[p] = True
                out.terdeteksi[p] = False
                out.zone_ok[p] = True
            else:
                self._slot[p] = None

        sisa = [tr for tr in sah if tr.id not in dipakai]
        bebas = [p for p in (1, 2) if self._slot[p] is None]

        # 2) Dua slot kosong + minimal dua tangan: kiri -> P1, kanan -> P2
        #    (aturan lama dipertahankan agar dua pemain baru langsung terpasang).
        if len(bebas) == 2 and len(sisa) >= 2:
            kiri_t, kanan_t = sisa[0], sisa[-1]
            if kanan_t.palm_x - kiri_t.palm_x < self.jarak_min:
                out.warnings.append(
                    "Kedua tangan terlalu berdekatan — berdiri agak ke samping."
                )
                target = zona_dari_x(kiri_t.palm_x, self.batas)
                self._ikat(out, target, kiri_t, now)
                out.unassigned.append(kanan_t.obs)
            else:
                self._ikat(out, 1, kiri_t, now)
                self._ikat(out, 2, kanan_t, now)
        else:
            # 3) Tangan baru hanya mengisi slot kosong sesuai zonanya.
            for tr in sisa:
                z = zona_dari_x(tr.palm_x, self.batas)
                if z in bebas:
                    self._ikat(out, z, tr, now)
                    bebas.remove(z)
                else:
                    out.unassigned.append(tr.obs)

        # 4) Status & peringatan.
        for p in (1, 2):
            out.terdeteksi.setdefault(p, False)
            out.memori.setdefault(p, False)
            out.zone_ok.setdefault(p, True)
        for p in (1, 2):
            if out.terdeteksi[p] and not out.zone_ok[p]:
                out.warnings.append(
                    f"Player {p} di luar zonanya — geser ke "
                    f"{'kiri' if p == 1 else 'kanan'} kamera."
                )
        if not sah:
            out.warnings.append("Tidak ada tangan kanan di depan kamera.")
        # Dedupe tanpa mengubah urutan.
        out.warnings = list(dict.fromkeys(out.warnings))
        return out

    def _ikat(self, out: SplitResult, player: int, tr, now: float,
              zone_ok: Optional[bool] = None) -> None:
        x = tr.palm_x
        ok = (zona_dari_x(x, self.batas) == player) if zone_ok is None else zone_ok
        out.hands[player] = tr.obs
        out.palm_x[player] = x
        out.zone_ok[player] = ok
        out.track_id[player] = tr.id
        out.terdeteksi[player] = True
        out.memori[player] = False
        self._slot[player] = tr.id
        self._last_seen[player] = now
