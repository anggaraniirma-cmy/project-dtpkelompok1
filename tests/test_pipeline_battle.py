"""Uji pipeline mode battle dengan kamera & detector PALSU.

Ini menguji jalur CV yang sebenarnya (VisionPipeline._process_battle) tanpa
perangkat keras: frame sintetis dipasok melewati CameraStream palsu, dan
detektor mengembalikan dua tangan pada zona yang ditentukan. Yang diperiksa
adalah perilaku nyata pipeline: pemisahan pemain, stabilizer independen,
antrean kunci per pemain, dan ketiadaan jawaban ganda.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from app.cv.pipeline import VisionPipeline
from app.cv.stabilizer import GestureStabilizer
from tests.synthetic_hand import make_hand


class FakeCamera:
    """CameraStream palsu: frame tetap, id bertambah tiap pembacaan."""

    def __init__(self):
        self.running = False
        self.error = None
        self._id = 0
        self.frame = np.zeros((480, 640, 3), dtype=np.uint8)

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def read(self):
        self._id += 1
        return self.frame, self._id


class FakeDetector:
    """Detektor palsu: mengembalikan daftar tangan yang diatur tes."""

    def __init__(self, hands=None):
        self.hands = list(hands or [])
        self.num_hands = 2
        self.calls = 0

    def detect(self, frame, timestamp_ms=None):
        self.calls += 1
        return self.hands[0] if self.hands else None

    def detect_many(self, frame, timestamp_ms=None):
        self.calls += 1
        return list(self.hands)

    def close(self):
        pass


def _pipeline(hands):
    # hold pendek supaya tes cepat, tetapi masih lewat jalur stabilizer asli.
    stab = GestureStabilizer(hold_seconds=0.05, cooldown_seconds=0.1,
                             rearm_seconds=0.02, window_seconds=0.06)
    return VisionPipeline(
        camera=FakeCamera(),
        detector=FakeDetector(hands),
        mode="battle",
        stabilizer=stab,
        hold_seconds=0.05,
        cooldown_seconds=0.1,
        rearm_seconds=0.02,
    )


def _proses(pipe, n=1):
    """Jalankan pemrosesan langsung (tanpa thread) n kali."""
    for _ in range(n):
        pipe._last_frame_id += 1
        if pipe.mode == "battle":
            pipe._process_battle(pipe.camera.frame, pipe._last_frame_id)
        else:
            pipe._process(pipe.camera.frame, pipe._last_frame_id)


def test_pipeline_mendeteksi_dua_pemain_dan_mengunci_terpisah():
    kiri = make_hand((True, False, False, False), offset_x=-0.28)   # A
    kanan = make_hand((True, True, True, True), offset_x=0.28)      # D
    pipe = _pipeline([kanan, kiri])   # urutan sengaja dibalik
    try:
        _proses(pipe, 1)
        st = pipe.status()
        assert st["mode"] == "battle"
        assert st["pemain"]["1"]["terdeteksi"] is True
        assert st["pemain"]["2"]["terdeteksi"] is True
        assert st["pemain"]["1"]["gesture"] == "A"
        assert st["pemain"]["2"]["gesture"] == "D"

        # tahan beberapa frame sampai stabilizer mengunci
        for _ in range(20):
            _proses(pipe, 1)
            time.sleep(0.01)
        locks = pipe.pop_locks()
        assert locks == {1: "A", 2: "D"}, f"kunci tertukar: {locks}"
        # antrean kosong setelah diambil sekali -> tidak ada duplikat
        assert pipe.pop_locks() == {}
    finally:
        pipe.close()


def test_pipeline_tidak_mengunci_dua_kali_untuk_tangan_yang_sama():
    kiri = make_hand((True, True, False, False), offset_x=-0.25)    # B
    pipe = _pipeline([kiri])
    try:
        total = []
        for _ in range(40):
            _proses(pipe, 1)
            time.sleep(0.01)
            d = pipe.pop_locks()
            if d:
                total.append(d)
        assert len(total) == 1, f"harus satu kunci, dapat {total}"
        assert total[0] == {1: "B"}
        # P2 tidak pernah dapat jawaban dari tangan P1
        assert all(2 not in d for d in total)
    finally:
        pipe.close()


def test_tangan_di_zona_salah_tidak_mengunci():
    """Dua tangan di sisi kanan: P1 tidak boleh menjawab dari zona yang salah."""
    a = make_hand((True, False, False, False), offset_x=0.16)   # pusat ~0.66
    b = make_hand((True, True, True, True), offset_x=0.42)      # pusat ~0.92
    pipe = _pipeline([a, b])
    try:
        _proses(pipe, 1)
        st = pipe.status()
        assert st["pemain"]["1"]["zona_ok"] is False
        assert st["pemain"]["2"]["zona_ok"] is True
        assert st["peringatan"], "harus ada peringatan zona"

        for _ in range(20):
            _proses(pipe, 1)
            time.sleep(0.01)
        locks = pipe.pop_locks()
        assert 1 not in locks, "P1 tidak boleh menjawab dari zona kanan"
        assert locks.get(2) == "D"
    finally:
        pipe.close()


def test_tangan_kiri_tidak_dapat_mengunci():
    tangan = make_hand((True, False, False, False), offset_x=-0.25, handedness="Left")
    pipe = _pipeline([tangan])
    try:
        _proses(pipe, 1)
        st = pipe.status()
        assert st["pemain"]["1"]["terdeteksi"] is False
        assert st["pemain"]["2"]["terdeteksi"] is False
        assert any("kiri" in w.lower() for w in st["peringatan"])
        for _ in range(20):
            _proses(pipe, 1)
            time.sleep(0.01)
        assert pipe.pop_locks() == {}
    finally:
        pipe.close()


def test_pemain_tanpa_tangan_tidak_menghapus_kunci_pemain_lain():
    kiri = make_hand((True, True, True, False), offset_x=-0.25)   # C untuk P1
    pipe = _pipeline([kiri])
    try:
        kunci = None
        for _ in range(60):
            _proses(pipe, 1)
            time.sleep(0.01)
            d = pipe.pop_locks()
            if d:
                kunci = d
                break
        assert kunci == {1: "C"}
        st = pipe.status()
        assert st["pemain"]["2"]["terdeteksi"] is False
        assert st["pemain"]["1"]["terdeteksi"] is True
    finally:
        pipe.close()


def test_reset_stabilizer_saat_soal_baru():
    kiri = make_hand((True, False, False, False), offset_x=-0.25)
    pipe = _pipeline([kiri])
    try:
        for _ in range(40):
            _proses(pipe, 1)
            time.sleep(0.01)
            pipe.pop_locks()
        # soal baru: latch dibersihkan, tangan masih terangkat
        pipe.disarm_stabilizers()
        for _ in range(5):
            _proses(pipe, 1)
            time.sleep(0.01)
        assert pipe.pop_locks() == {}, "tangan yang belum dilepas tidak boleh langsung menjawab"
    finally:
        pipe.close()


def test_status_memuat_dua_pemain_dan_peringatan():
    pipe = _pipeline([make_hand(offset_x=0.28)])
    try:
        _proses(pipe, 2)
        st = pipe.status()
        assert set(st["pemain"].keys()) == {"1", "2"}
        assert "peringatan" in st
        assert st["fps"] >= 0
        assert st["error"] is None
    finally:
        pipe.close()


def test_mode_single_tetap_satu_tangan():
    pipe = VisionPipeline(camera=FakeCamera(), detector=FakeDetector(
        [make_hand((True, False, False, False))]), mode="single")
    try:
        assert pipe.mode == "single"
        _proses(pipe, 1)
        st = pipe.status()
        assert st["mode"] == "single"
        assert st["pemain"] == {}
        assert st["gesture"] == "A"
    finally:
        pipe.close()
