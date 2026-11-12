"""Stabilisasi temporal + cooldown untuk gesture.

Masalah yang diselesaikan:
  * jitter MediaPipe antar frame -> butuh konfirmasi mayoritas dalam jendela waktu
  * gesture harus ditahan ~1 detik sebelum mengunci jawaban
  * setelah terkunci, tidak boleh ada input ganda (cooldown + latch)
  * tangan harus DILEPAS dulu sebelum gesture berikutnya bisa mengunci,
    supaya tangan yang masih terangkat tidak otomatis menjawab soal berikutnya

Modul ini murni logika waktu (clock disuntikkan) sehingga bisa diuji tanpa
kamera.
"""
from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class StableGesture:
    gesture: Optional[str] = None      # gesture mayoritas saat ini
    candidates: dict[str, int] = field(default_factory=dict)
    progress: float = 0.0              # 0..1 progres tahan
    locked: Optional[str] = None       # gesture yang baru dikunci (event)
    locked_at: float = 0.0
    armed: bool = True                 # sudah boleh mengunci lagi?
    cooldown: float = 0.0              # sisa cooldown detik
    waiting_release: bool = False      # menunggu tangan dilepas


class GestureStabilizer:
    def __init__(
        self,
        hold_seconds: float = 1.0,
        cooldown_seconds: float = 1.5,
        rearm_seconds: float = 0.25,
        window_seconds: float = 0.6,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.hold_seconds = hold_seconds
        self.cooldown_seconds = cooldown_seconds
        self.rearm_seconds = rearm_seconds
        self.window_seconds = window_seconds
        self._clock = clock
        self._samples: deque[tuple[float, Optional[str]]] = deque(maxlen=240)

        self._candidate: Optional[str] = None
        self._candidate_since = 0.0
        self._last_locked_at: float = -1e9
        self._armed = True
        self._neutral_since: Optional[float] = None

    # -- API ---------------------------------------------------------------
    def reset(self) -> None:
        """Panggil saat sesi/pertanyaan berganti: bersihkan riwayat & latch."""
        self._samples.clear()
        self._candidate = None
        self._candidate_since = 0.0
        self._armed = True
        self._neutral_since = None
        self._last_locked_at = -1e9

    def disarm(self) -> None:
        """Cegah kunci hingga tangan dilepas (dipakai saat soal baru muncul)."""
        self._candidate = None
        self._candidate_since = 0.0
        self._armed = False
        self._neutral_since = None
        self._last_locked_at = self._clock()

    def _majority(self) -> tuple[Optional[str], dict[str, int]]:
        counts = Counter(g for _t, g in self._samples if g)
        if not counts:
            return None, {}
        gesture, n = counts.most_common(1)[0]
        ratio = n / max(len(self._samples), 1)
        return (gesture if ratio >= 0.6 else None), dict(counts)

    def update(self, gesture: Optional[str]) -> StableGesture:
        now = self._clock()
        self._samples.append((now, gesture))
        cutoff = now - self.window_seconds
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

        cooldown_left = max(0.0, self.cooldown_seconds - (now - self._last_locked_at))
        in_cooldown = cooldown_left > 0

        # Re-arm hanya setelah tangan benar-benar netral cukup lama.
        if gesture is None:
            if self._neutral_since is None:
                self._neutral_since = now
            if not in_cooldown and (now - self._neutral_since) >= self.rearm_seconds:
                self._armed = True
        else:
            self._neutral_since = None

        majority, counts = self._majority()
        result = StableGesture(
            gesture=majority, candidates=counts, cooldown=round(cooldown_left, 2),
            armed=self._armed and not in_cooldown,
            waiting_release=(not self._armed) and majority is not None,
        )

        if not result.armed:
            # Tangan masih terangkat / cooldown: progres tidak dihitung.
            self._candidate = None
            self._candidate_since = 0.0
            return result

        if majority is None:
            self._candidate = None
            self._candidate_since = 0.0
            return result

        if majority != self._candidate:
            self._candidate = majority
            self._candidate_since = now

        held = now - self._candidate_since
        result.progress = min(1.0, held / self.hold_seconds) if self.hold_seconds > 0 else 1.0

        if held >= self.hold_seconds:
            self._last_locked_at = now
            self._armed = False          # butuh lepas tangan sebelum kunci berikutnya
            result.locked = majority
            result.locked_at = now
            result.progress = 1.0
            result.armed = False
            result.waiting_release = True
            self._candidate = None
            self._candidate_since = 0.0
            self._neutral_since = None
        return result

    @property
    def cooldown_remaining(self) -> float:
        return max(0.0, self.cooldown_seconds - (self._clock() - self._last_locked_at))
