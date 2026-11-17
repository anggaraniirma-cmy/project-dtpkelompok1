"""Uji classifier gesture, stabilisasi, dan cooldown (tanpa kamera)."""
from __future__ import annotations

import numpy as np
import pytest

from app.cv.gesture import GestureClassifier
from app.cv.stabilizer import GestureStabilizer
from tests.synthetic_hand import make_hand

CLF = GestureClassifier()

CASES = {
    "A": (True, False, False, False),
    "B": (True, True, False, False),
    "C": (True, True, True, False),
    "D": (True, True, True, True),
}


@pytest.mark.parametrize("expected,raised", CASES.items())
def test_empat_gesture_dikenali(expected, raised):
    obs = make_hand(raised)
    res = CLF.classify(obs)
    assert res.gesture == expected, f"{expected} gagal: {res.reason} {res.fingers}"


@pytest.mark.parametrize("expected,raised", CASES.items())
@pytest.mark.parametrize("scale", [0.7, 1.0, 1.5])
def test_skala_tangan_tidak_mengubah_hasil(expected, raised, scale):
    obs = make_hand(raised, scale=scale)
    assert CLF.classify(obs).gesture == expected


@pytest.mark.parametrize("expected,raised", CASES.items())
@pytest.mark.parametrize("rot", [-25, 0, 25])
def test_rotasi_wajar_tidak_mengubah_hasil(expected, raised, rot):
    obs = make_hand(raised, rotation_deg=rot)
    assert CLF.classify(obs).gesture == expected


def test_ibu_jari_terbuka_ditolak():
    obs = make_hand(CASES["A"], thumb_folded=False)
    res = CLF.classify(obs)
    assert res.gesture is None
    assert "ibu jari" in res.reason.lower()


def test_ibu_jari_terbuka_dengan_4_jari_juga_ditolak():
    obs = make_hand(CASES["D"], thumb_folded=False)
    assert CLF.classify(obs).gesture is None


def test_tangan_kiri_ditolak():
    obs = make_hand(CASES["A"], handedness="Left")
    res = CLF.classify(obs)
    assert res.gesture is None
    assert not res.hand_ok
    assert "tangan kanan" in res.reason.lower()


def test_tangan_kanan_diterima_dan_unknown_diizinkan():
    """Label 'Right' lolos; 'Unknown' (label lemah) tidak memblokir pengunjung."""
    for label in ("Right", "Unknown"):
        obs = make_hand(CASES["A"], handedness=label)
        assert CLF.classify(obs).gesture == "A"


def test_label_mediapipe_dibalik_setelah_frame_dimirror():
    """Frame di-mirror sebelum inferensi, jadi label MediaPipe kebalikannya."""
    from app.cv.landmarks import real_handedness

    assert real_handedness("Left") == "Right"    # mirip tangan kiri -> sebenarnya kanan
    assert real_handedness("Right") == "Left"
    assert real_handedness("Unknown") == "Unknown"
    assert real_handedness(None) == "Unknown"


def test_kepalan_kosong_ditolak():
    obs = make_hand((False, False, False, False))
    # kelingking (jari kecil) boleh terdeteksi terlipat; intinya bukan A-D
    assert CLF.classify(obs).gesture is None


def test_kombinasi_tidak_berurutan_ditolak():
    """Telunjuk + manis tanpa tengah bukan gesture yang sah."""
    obs = make_hand((True, False, True, False))
    res = CLF.classify(obs)
    assert res.gesture is None
    assert "berurutan" in res.reason.lower()


def test_finger_state_individu_bukan_jumlah():
    """Setiap jari dinilai terpisah; tidak ada logika 'hitung jari'."""
    obs = make_hand(CASES["B"])
    res = CLF.classify(obs)
    assert res.fingers["telunjuk"].extended is True
    assert res.fingers["tengah"].extended is True
    assert res.fingers["manis"].extended is False
    assert res.fingers["kelingking"].extended is False
    assert res.thumb_folded is True


# --- stabilisasi -----------------------------------------------------------

class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _feed(stab, gesture, seconds, clock, dt=1 / 30):
    locked = []
    steps = int(seconds / dt)
    for _ in range(steps):
        clock.advance(dt)
        r = stab.update(gesture)
        if r.locked:
            locked.append(r.locked)
    return locked


def test_kunci_setelah_tahan_satu_detik():
    clock = FakeClock()
    stab = GestureStabilizer(hold_seconds=1.0, cooldown_seconds=1.5, clock=clock)
    # 0.5 detik belum boleh terkunci
    assert _feed(stab, "A", 0.5, clock) == []
    # total 1.1 detik -> terkunci
    assert _feed(stab, "A", 0.7, clock) == ["A"]


def test_tidak_ada_duplikat_dalam_cooldown():
    clock = FakeClock()
    stab = GestureStabilizer(hold_seconds=1.0, cooldown_seconds=1.5, clock=clock)
    locked = _feed(stab, "B", 4.0, clock)
    assert locked == ["B"], f"harus tepat satu kunci, dapat {locked}"


def test_gesture_harus_dilepas_sebelum_kuis_berikutnya():
    clock = FakeClock()
    stab = GestureStabilizer(hold_seconds=0.6, cooldown_seconds=0.5, rearm_seconds=0.3, clock=clock)
    assert _feed(stab, "A", 1.0, clock) == ["A"]
    # ganti langsung ke C tanpa netral: cooldown habis tapi belum rearm
    assert _feed(stab, "C", 0.9, clock) == []
    # lepas tangan (None) -> rearm
    _feed(stab, None, 0.7, clock)
    # latensi total = jendela buffer (0.6s) + tahan (0.6s) -> beri 1.5s
    assert _feed(stab, "C", 1.5, clock) == ["C"]


def test_jitter_tidak_mengunci():
    """Gesture yang berganti-ganti tiap frame tidak boleh lolos."""
    clock = FakeClock()
    stab = GestureStabilizer(hold_seconds=1.0, cooldown_seconds=1.0, clock=clock)
    locked = []
    for i in range(120):
        clock.advance(1 / 30)
        r = stab.update(["A", "B", None, "D"][i % 4])
        if r.locked:
            locked.append(r.locked)
    assert locked == []


def test_gesture_sama_dengan_satu_gangguan_tetap_terkunci():
    clock = FakeClock()
    stab = GestureStabilizer(hold_seconds=0.8, cooldown_seconds=1.0, window_seconds=0.5, clock=clock)
    locked = []
    for i in range(40):
        clock.advance(1 / 30)
        g = None if i == 12 else "C"
        r = stab.update(g)
        if r.locked:
            locked.append(r.locked)
    assert locked == ["C"]


def test_progress_naik_secara_monoton():
    clock = FakeClock()
    stab = GestureStabilizer(hold_seconds=1.0, cooldown_seconds=1.0, clock=clock)
    vals = []
    for _ in range(30):
        clock.advance(1 / 30)
        vals.append(stab.update("A").progress)
    assert vals[0] < 0.2 and max(vals) > 0.9
    assert all(b >= a - 1e-6 for a, b in zip(vals, vals[1:]))
