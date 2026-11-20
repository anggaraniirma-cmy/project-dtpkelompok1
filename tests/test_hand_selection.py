"""Uji seleksi tangan, tracking identitas, dan pemisahan pemain stateful.

Semua buatan (sintetis), TANPA kamera — jadi yang dibuktikan di sini adalah
logika geometri/temporal, bukan kualitas deteksi di dunia nyata.

Skenario yang ditiru (kondisi pameran ramai):
  * tangan orang di latar belakang (kecil karena jauh) tidak boleh menjawab;
  * tangan yang muncul di luar area permainan diabaikan;
  * identitas Player 1/2 tidak berubah hanya karena tangan bergeser zona;
  * saat tangan pemain tertutup sesaat, slotnya ditahan (bukan direbut orang lain);
  * tangan kiri tetap tidak boleh menjawab.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from app.cv.players import PlayerTracker, PlayerSplitter, observation_palsu
from app.cv.pipeline import VisionPipeline
from app.cv.stabilizer import GestureStabilizer
from app.cv.tracking import (
    HandFilter,
    HandTracker,
    TrackedHand,
    centroid,
    iou,
    palm_width_norm,
)
from tests.synthetic_hand import make_hand


class FakeClock:
    def __init__(self, t: float = 100.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def maju(self, dt: float) -> None:
        self.t += dt


class FakeCamera:
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
    def __init__(self, hands=None):
        self.hands = list(hands or [])
        self.num_hands = 3
        self.calls = 0

    def detect(self, frame, timestamp_ms=None):
        self.calls += 1
        return self.hands[0] if self.hands else None

    def detect_many(self, frame, timestamp_ms=None):
        self.calls += 1
        return list(self.hands)

    def close(self):
        pass


def _pipeline(hands, mode="battle"):
    stab = GestureStabilizer(hold_seconds=0.05, cooldown_seconds=0.1,
                             rearm_seconds=0.02, window_seconds=0.06)
    return VisionPipeline(
        camera=FakeCamera(), detector=FakeDetector(hands), mode=mode,
        stabilizer=stab, hold_seconds=0.05, cooldown_seconds=0.1, rearm_seconds=0.02,
    )


def _proses(pipe, n=1):
    for _ in range(n):
        pipe._last_frame_id += 1
        if pipe.mode == "battle":
            pipe._process_battle(pipe.camera.frame, pipe._last_frame_id)
        else:
            pipe._process(pipe.camera.frame, pipe._last_frame_id)


def _tangan_jauh(offset_x: float = 0.36, y: float = 0.30):
    """Tangan kecil = orang berdiri jauh di latar belakang."""
    return make_hand((True, True, True, True), wrist=(0.5 + offset_x, y), scale=0.2)


# ------------------------------------------------------------------- filter
def test_tangan_dekat_lolos_filter():
    tangan = make_hand((True, False, False, False))
    assert palm_width_norm(tangan) >= 0.2
    assert HandFilter().alasan_tolak(tangan) is None


def test_tangan_jauh_ditolak_karena_terlalu_kecil():
    jauh = _tangan_jauh()
    f = HandFilter()
    assert palm_width_norm(jauh) < f.min_palm_width
    assert f.alasan_tolak(jauh) == "terlalu_kecil"


def test_tangan_di_luar_area_permainan_ditolak():
    tinggi = make_hand((True, False, False, False))
    tinggi.landmarks[:, 1] -= 0.6          # geser ke atas frame
    assert centroid(tinggi)[1] < 0.05
    assert HandFilter().alasan_tolak(tinggi) == "luar_area"


def test_filter_menghitung_alasan_penolakan():
    tangan = make_hand((True, False, False, False))
    lolos, tolak = HandFilter().saring([tangan, _tangan_jauh(), _tangan_jauh(0.1)])
    assert len(lolos) == 1
    assert tolak.terlalu_kecil == 2
    assert tolak.total == 2


def test_iou_dan_geometri_dasar():
    a = (0.1, 0.1, 0.3, 0.3)
    assert iou(a, a) == pytest.approx(1.0)
    assert iou(a, (0.5, 0.5, 0.6, 0.6)) == 0.0


# ------------------------------------------------------------------ tracker
def test_tracker_mempertahankan_id_walau_urutan_deteksi_dibalik():
    clock = FakeClock()
    tracker = HandTracker(max_miss_seconds=0.5, clock=clock)
    kiri = make_hand((True, False, False, False), offset_x=-0.25)
    kanan = make_hand((True, True, True, True), offset_x=0.25)

    pertama = tracker.update([kiri, kanan])
    id_kiri = next(t.id for t in pertama if t.palm_x < 0.5)

    clock.maju(1 / 30)
    kedua = tracker.update([kanan, kiri])       # urutan dibalik
    id_kiri_lagi = next(t.id for t in kedua if t.palm_x < 0.5)
    assert id_kiri == id_kiri_lagi, "identitas harus ikut posisi, bukan urutan"
    assert len({t.id for t in kedua}) == 2


def test_tracker_memberi_id_baru_setelah_hilang_melewati_toleransi():
    clock = FakeClock()
    tracker = HandTracker(max_miss_seconds=0.2, clock=clock)
    tangan = make_hand((True, False, False, False))

    awal = tracker.update([tangan])
    tid = awal[0].id

    clock.maju(0.1)
    assert [t.id for t in tracker.update([])] == []      # hilang, belum kedaluwarsa
    clock.maju(0.05)
    assert [t.id for t in tracker.update([tangan])] == [tid]   # masih dikenali

    clock.maju(0.5)                                        # lewat toleransi
    baru = tracker.update([tangan])
    assert baru[0].id != tid


# ------------------------------------------------------------ player tracker
def _tracked(tid: int, x: float, handedness: str = "Right") -> TrackedHand:
    obs = make_hand((True, False, False, False), offset_x=x - 0.5,
                    handedness=handedness)
    return TrackedHand(id=tid, obs=obs, first_seen=0.0, last_seen=0.0)


def test_player_tracker_dua_tangan_pertama_kali_kiri_kanan():
    pt = PlayerTracker(clock=FakeClock())
    split = pt.assign([_tracked(1, 0.25), _tracked(2, 0.75)])
    assert split.track_id == {1: 1, 2: 2}
    assert split.terdeteksi[1] and split.terdeteksi[2]
    assert split.zone_ok[1] and split.zone_ok[2]


def test_identitas_tidak_tertukar_saat_tangan_menyilang_zona():
    clock = FakeClock()
    pt = PlayerTracker(memory_seconds=0.5, clock=clock)
    pt.assign([_tracked(1, 0.25), _tracked(2, 0.75)])

    clock.maju(1 / 30)
    # Track 1 (P1) bergerak ke kanan melewati garis tengah; track 2 ke kiri.
    split = pt.assign([_tracked(1, 0.62), _tracked(2, 0.35)])
    assert split.track_id == {1: 1, 2: 2}, "pemain tidak boleh bertukar identitas"
    assert split.zone_ok[1] is False, "bergeser zona harus jadi PERINGATAN"
    assert split.zone_ok[2] is False


def test_slot_pemain_ditahan_saat_tangan_hilang_sesaat():
    clock = FakeClock()
    pt = PlayerTracker(memory_seconds=0.4, clock=clock)
    pt.assign([_tracked(1, 0.25), _tracked(2, 0.75)])

    clock.maju(0.2)
    split = pt.assign([_tracked(2, 0.75)])       # tangan P1 tertutup
    assert split.terdeteksi[1] is False
    assert split.memori[1] is True
    assert split.track_id.get(2) == 2
    assert 1 not in split.hands


def test_tangan_baru_tidak_merebut_slot_yang_sedang_ditahan():
    clock = FakeClock()
    pt = PlayerTracker(memory_seconds=0.5, clock=clock)
    pt.assign([_tracked(1, 0.25), _tracked(2, 0.75)])

    clock.maju(0.2)
    # P1 hilang, lalu orang lain menaruh tangan di zona kiri (tangan besar).
    split = pt.assign([_tracked(2, 0.75), _tracked(9, 0.20)])
    assert 1 not in split.hands, "slot P1 masih milik pemain sebelumnya"
    assert split.memori[1] is True
    assert 9 not in split.track_id.values()


def test_setelah_memori_habis_tangan_baru_mendapat_slot():
    clock = FakeClock()
    pt = PlayerTracker(memory_seconds=0.3, clock=clock)
    pt.assign([_tracked(1, 0.25)])

    clock.maju(0.5)                              # memori habis
    split = pt.assign([_tracked(9, 0.22)])
    assert split.track_id == {1: 9}
    assert split.terdeteksi[1] is True


def test_tangan_kiri_tetap_tidak_boleh_menjawab():
    pt = PlayerTracker(clock=FakeClock())
    split = pt.assign([_tracked(1, 0.25, handedness="Left")])
    assert not split.hands
    assert len(split.wrong_hand) == 1
    assert any("kiri" in w.lower() for w in split.warnings)


# ---------------------------------------------------------------- pipeline
def test_single_player_mengabaikan_tangan_di_latar_belakang():
    utama = make_hand((True, False, False, False), wrist=(0.55, 0.85))   # A, dekat
    jauh = _tangan_jauh(offset_x=0.30, y=0.30)                            # D, jauh
    pipe = _pipeline([jauh, utama], mode="single")
    try:
        _proses(pipe, 1)
        st = pipe.status()
        assert st["tangan_mentah"] == 2
        assert st["tangan_ditolak"]["terlalu_kecil"] == 1
        assert st["terdeteksi"] is True
        assert st["gesture"] == "A", "tangan jauh tidak boleh jadi jawaban"
        assert st["status"] in {"mengenali", "menahan", "belum_valid"}
    finally:
        pipe.close()


def test_battle_mengabaikan_tangan_di_latar_belakang():
    kiri = make_hand((True, False, False, False), offset_x=-0.28)   # A
    kanan = make_hand((True, True, True, True), offset_x=0.28)      # D
    jauh = _tangan_jauh(offset_x=0.02, y=0.32)
    pipe = _pipeline([kiri, kanan, jauh])
    try:
        _proses(pipe, 2)
        st = pipe.status()
        assert st["pemain"]["1"]["gesture"] == "A"
        assert st["pemain"]["2"]["gesture"] == "D"
        assert st["tangan_mentah"] == 3
        assert st["tangan_ditolak"]["terlalu_kecil"] == 1
        assert st["tangan_terlihat"] == 2
    finally:
        pipe.close()


def test_identitas_pemain_bertahan_saat_tangan_tertutup_sesaat():
    kiri = make_hand((True, False, False, False), offset_x=-0.28)
    kanan = make_hand((True, True, True, True), offset_x=0.28)
    pipe = _pipeline([kiri, kanan])
    try:
        _proses(pipe, 2)
        id_p1 = pipe.status()["pemain"]["1"]["track_id"]
        assert id_p1 is not None

        pipe.detector.hands = [kanan]        # tangan P1 tertutup
        _proses(pipe, 1)
        st = pipe.status()
        assert st["pemain"]["1"]["terdeteksi"] is False
        assert st["pemain"]["1"]["memori"] is True
        assert st["pemain"]["1"]["status"] == "memori"
        assert st["pemain"]["2"]["terdeteksi"] is True

        pipe.detector.hands = [kiri, kanan]  # tangan muncul lagi
        _proses(pipe, 1)
        st2 = pipe.status()
        assert st2["pemain"]["1"]["track_id"] == id_p1, "identitas P1 harus sama"
        assert st2["pemain"]["1"]["terdeteksi"] is True
    finally:
        pipe.close()


def test_tangan_jauh_tidak_mewarisi_identitas_tangan_dekat():
    """Posisi sama, ukuran beda -> orang berbeda, identitas tidak boleh nyebrang."""
    tracker = HandTracker()
    dekat = make_hand((True, False, False, False))            # telapak lebar
    tracker.update([dekat])
    jauh = make_hand((True, False, False, False), scale=0.25)  # telapak kecil
    assert palm_width_norm(jauh) / palm_width_norm(dekat) < 0.6
    baru = tracker.update([jauh])
    assert len(baru) == 1 and baru[0].id != 1


def test_slot_p1_dilepas_setelah_memori_habis_lalu_diisi_pengunjung_baru():
    kiri = make_hand((True, False, False, False), offset_x=-0.28)
    kanan = make_hand((True, True, True, True), offset_x=0.28)
    pipe = _pipeline([kiri, kanan])
    try:
        # Percepat toleransi supaya tes tidak menunggu ~1 detik.
        pipe.player_tracker.memory_seconds = 0.02
        pipe.tracker.max_miss_seconds = 0.02

        _proses(pipe, 2)
        id_lama = pipe.status()["pemain"]["1"]["track_id"]
        assert id_lama is not None

        pipe.detector.hands = [kanan]        # P1 benar-benar pergi
        time.sleep(0.06)
        _proses(pipe, 1)
        st = pipe.status()
        assert st["pemain"]["1"]["terdeteksi"] is False
        assert st["pemain"]["1"]["memori"] is False, "memori sudah habis"
        assert st["pemain"]["1"]["status"] == "tidak_ada"

        # Pengunjung baru berdiri di zona kiri -> boleh mendapat slot P1,
        # tetapi dengan identitas BARU (bukan mewarisi track pemain lama).
        pipe.detector.hands = [kanan, kiri]
        time.sleep(0.06)
        _proses(pipe, 1)
        st2 = pipe.status()
        assert st2["pemain"]["1"]["terdeteksi"] is True
        assert st2["pemain"]["1"]["track_id"] != id_lama
    finally:
        pipe.close()


def test_dua_pemain_tetap_bisa_mengunci_setelah_perubahan_ini():
    kiri = make_hand((True, False, False, False), offset_x=-0.28)
    kanan = make_hand((True, True, True, True), offset_x=0.28)
    pipe = _pipeline([kanan, kiri])
    try:
        _proses(pipe, 1)
        for _ in range(20):
            _proses(pipe, 1)
            time.sleep(0.01)
        assert pipe.pop_locks() == {1: "A", 2: "D"}
    finally:
        pipe.close()


def test_status_memuat_indikator_baru():
    pipe = _pipeline([make_hand(offset_x=-0.25)], mode="single")
    try:
        _proses(pipe, 1)
        st = pipe.status()
        for kunci in ("status", "terdeteksi", "tangan_terlihat",
                      "tangan_mentah", "tangan_ditolak"):
            assert kunci in st
    finally:
        pipe.close()


def test_player_splitter_lama_tetap_berfungsi():
    """Kontrak lama tidak boleh rusak: modul stateless masih dipakai tes lain."""
    split = PlayerSplitter().assign([observation_palsu(0.2), observation_palsu(0.8)])
    assert split.terisi(1) and split.terisi(2)
