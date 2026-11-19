"""Uji mode 2 PLAYER BATTLE dan pemisahan pemain berbasis zona.

Semua tes di sini berjalan TANPA kamera: geometri tangan disintesis dan jam
server disuntikkan, sehingga hasilnya deterministik.
"""
from __future__ import annotations

import os
import tempfile

import numpy as np
import pytest

_tmpdir = tempfile.mkdtemp(prefix="skomda_battle_")
os.environ.setdefault("SKOMDA_DB", os.path.join(_tmpdir, "battle.db"))
os.environ.setdefault("SKOMDA_SECRET", "test-secret-battle")

from app import config, database  # noqa: E402
from app.cv.gesture import GestureClassifier  # noqa: E402
from app.cv.players import (  # noqa: E402
    PlayerSplitter,
    observation_palsu,
    palm_x,
    zona_dari_x,
)
from app.cv.stabilizer import GestureStabilizer  # noqa: E402
from app.game.battle import BattleEngine  # noqa: E402
from app.game.engine import hitung_poin  # noqa: E402
from tests.synthetic_hand import make_hand  # noqa: E402

CLF = GestureClassifier()


# ---------------------------------------------------------------- zona/pemain
def test_zona_kiri_player_1_kanan_player_2():
    assert zona_dari_x(0.2) == 1
    assert zona_dari_x(0.49) == 1
    assert zona_dari_x(0.5) == 2
    assert zona_dari_x(0.9) == 2


def test_satu_tangan_kiri_jadi_player_1():
    split = PlayerSplitter().assign([observation_palsu(0.25)])
    assert split.terisi(1)
    assert not split.terisi(2)
    assert split.zone_ok[1] is True


def test_satu_tangan_kanan_jadi_player_2():
    split = PlayerSplitter().assign([observation_palsu(0.8)])
    assert split.terisi(2)
    assert not split.terisi(1)


def test_dua_tangan_dipisah_berdasarkan_posisi_bukan_urutan():
    """Urutan deteksi dibalik: hasil pemain harus tetap sama."""
    kiri = observation_palsu(0.22)
    kanan = observation_palsu(0.78)
    for urutan in ([kiri, kanan], [kanan, kiri]):
        split = PlayerSplitter().assign(urutan)
        assert split.terisi(1) and split.terisi(2)
        assert palm_x(split.hands[1]) < 0.5 < palm_x(split.hands[2])
        assert split.zone_ok[1] and split.zone_ok[2]


def test_tidak_ada_tangan():
    split = PlayerSplitter().assign([])
    assert not split.hands
    assert split.warnings


def test_tangan_kiri_dipisahkan_tidak_boleh_menjawab():
    split = PlayerSplitter().assign([observation_palsu(0.3, handedness="Left")])
    assert not split.hands
    assert len(split.wrong_hand) == 1
    assert any("kiri" in w.lower() for w in split.warnings)


def test_kedua_tangan_di_zona_salah_ditandai():
    """Dua tangan di sisi kanan: salah satunya di luar zona -> ada peringatan."""
    split = PlayerSplitter().assign([observation_palsu(0.62), observation_palsu(0.9)])
    assert split.terisi(1) and split.terisi(2)
    # P1 dapat tangan paling kiri (0.62) tapi itu masih zona kanan
    assert split.zone_ok[1] is False
    assert split.zone_ok[2] is True
    assert any("zona" in w.lower() for w in split.warnings)


def test_tangan_berdempetan_tidak_dipakai_dua_pemain():
    split = PlayerSplitter().assign([observation_palsu(0.40), observation_palsu(0.43)])
    total = len(split.hands) + len(split.unassigned)
    assert total == 2
    assert len(split.hands) == 1, "satu tangan tidak boleh menjawab dua pemain"
    assert any("berdekatan" in w.lower() for w in split.warnings)


def test_gesture_per_pemain_independen_pada_dua_tangan():
    """Gesture A (kiri) dan D (kanan) diklasifikasi terpisah."""
    tangan_kiri = make_hand((True, False, False, False), offset_x=-0.28)
    tangan_kanan = make_hand((True, True, True, True), offset_x=0.28)
    split = PlayerSplitter().assign([tangan_kanan, tangan_kiri])
    assert palm_x(split.hands[1]) < 0.5 < palm_x(split.hands[2])
    assert CLF.classify(split.hands[1]).gesture == "A"
    assert CLF.classify(split.hands[2]).gesture == "D"


# ------------------------------------------------------------- stabilizer x2
class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _feed(stab, gesture, seconds, clock, dt=1 / 30):
    locked = []
    for _ in range(int(seconds / dt)):
        clock.advance(dt)
        r = stab.update(gesture)
        if r.locked:
            locked.append(r.locked)
    return locked


def test_stabilizer_dua_pemain_tidak_saling_mengunci():
    clock = FakeClock()
    s1 = GestureStabilizer(hold_seconds=0.6, cooldown_seconds=1.0, clock=clock)
    s2 = GestureStabilizer(hold_seconds=0.6, cooldown_seconds=1.0, clock=clock)
    locks1, locks2 = [], []
    for i in range(60):
        clock.advance(1 / 30)
        r1 = s1.update("A")       # P1 menahan A
        r2 = s2.update("D")       # P2 menahan D
        if r1.locked:
            locks1.append(r1.locked)
        if r2.locked:
            locks2.append(r2.locked)
    assert locks1 == ["A"]
    assert locks2 == ["D"]


def test_pemain_belum_menjawab_tidak_menghapus_status_lain():
    """P1 terkunci, P2 belum: latch P1 harus tetap setelah banyak frame."""
    clock = FakeClock()
    s1 = GestureStabilizer(hold_seconds=0.5, cooldown_seconds=2.0, clock=clock)
    s2 = GestureStabilizer(hold_seconds=0.5, cooldown_seconds=2.0, clock=clock)
    r1 = None
    for _ in range(20):
        clock.advance(1 / 30)
        a = s1.update("B")
        if a.locked:
            r1 = a.locked
        s2.update(None)           # P2 tidak ada tangan
    assert r1 == "B"
    # P1 masih menahan B -> tidak boleh mengunci dua kali
    assert _feed(s1, "B", 1.5, clock) == []


# ------------------------------------------------------------------- engine
@pytest.fixture()
def engine():
    database.init_db()
    e = BattleEngine()
    yield e
    e.stop()


def _jawaban_benar(engine) -> dict[int, str]:
    """Ambil kunci jawaban dari DB untuk soal aktif (bukan dari API)."""
    soal = engine.sesi.soal
    with database.get_conn() as conn:
        row = conn.execute("SELECT jawaban FROM pertanyaan WHERE id=?", (soal.id,)).fetchone()
    return {1: row["jawaban"], 2: row["jawaban"]}


def test_start_membuat_dua_pemain_dengan_skor_nol(engine):
    engine.start(jumlah_soal=3)
    st = engine.public_state()
    assert st["mode"] == "battle"
    assert st["total_soal"] == 3
    assert st["pemain"]["1"]["skor"] == 0
    assert st["pemain"]["2"]["skor"] == 0
    assert st["pemain"]["1"]["nama"] == "Player 1"
    assert "jawaban" not in st["soal"], "kunci jawaban tidak boleh bocor"


def test_nama_pemain_kustom(engine):
    engine.start(jumlah_soal=2, nama_pemain={1: "Rina", 2: "Budi"})
    st = engine.public_state()
    assert st["pemain"]["1"]["nama"] == "Rina"
    assert st["pemain"]["2"]["nama"] == "Budi"


def test_dua_pemain_menjawab_bersamaan_skor_terpisah(engine):
    engine.start(jumlah_soal=3)
    benar = _jawaban_benar(engine)
    salah = "A" if benar[1] != "A" else "B"

    e1 = engine.submit(1, benar[1])
    e2 = engine.submit(2, salah)

    assert e1["benar"] is True and e2["benar"] is False
    assert engine.sesi.pemain[1].skor > 0
    assert engine.sesi.pemain[2].skor == 0
    assert engine.sesi.pemain[1].benar == 1
    assert engine.sesi.pemain[2].benar == 0


def test_jawaban_kedua_pemain_benar_keduanya_dapat_poin(engine):
    engine.start(jumlah_soal=2)
    benar = _jawaban_benar(engine)[1]
    engine.submit(1, benar)
    engine.submit(2, benar)
    p1, p2 = engine.sesi.pemain[1], engine.sesi.pemain[2]
    assert p1.skor > 0 and p2.skor > 0
    assert p1.skor == p2.skor


def test_duplicate_answer_ditolak_per_pemain(engine):
    engine.start(jumlah_soal=2)
    engine.submit(1, "A")
    with pytest.raises(ValueError, match="sudah menjawab"):
        engine.submit(1, "B")
    # P2 tetap boleh menjawab
    assert engine.submit(2, "C")["pemain"] == 2


def test_jawaban_p1_tidak_mengubah_jawaban_p2(engine):
    engine.start(jumlah_soal=2)
    engine.submit(1, "A")
    assert engine.sesi.pemain[1].jawaban == "A"
    assert engine.sesi.pemain[2].jawaban is None
    assert engine.public_state()["pemain"]["2"]["sudah_menjawab"] is False


def test_soal_tidak_maju_sebelum_kedua_pemain_menjawab(engine):
    engine.start(jumlah_soal=3)
    engine.submit(1, "A")
    res = engine.next_question()
    assert res["diabaikan"] is True
    assert res["menunggu"] == [2]
    assert engine.sesi.indeks == 0
    # skor P1 tidak hilang walau soal belum maju
    assert engine.sesi.pemain[1].jawaban == "A"

    engine.submit(2, "B")
    res = engine.next_question()
    assert res["status"] == "berjalan"
    assert engine.sesi.indeks == 1
    assert engine.sesi.pemain[1].skor >= 0


def test_skor_bertahan_setelah_ganti_soal(engine):
    engine.start(jumlah_soal=3)
    benar = _jawaban_benar(engine)[1]
    engine.submit(1, benar)
    engine.submit(2, benar)
    skor1 = engine.sesi.pemain[1].skor
    engine.next_question()
    assert engine.sesi.pemain[1].skor == skor1
    assert engine.public_state()["nomor"] == 2
    # state soal baru bersih
    assert engine.sesi.pemain[1].jawaban is None
    assert engine.public_state()["pemain"]["1"]["sudah_menjawab"] is False


def test_timeout_hanya_menandai_pemain_yang_belum_menjawab(engine):
    engine.start(jumlah_soal=2)
    benar = _jawaban_benar(engine)[1]
    engine.submit(1, benar)
    skor1 = engine.sesi.pemain[1].skor
    engine.timeout()
    assert engine.sesi.pemain[1].skor == skor1, "skor P1 tidak boleh hilang"
    assert engine.sesi.pemain[1].sumber == "gesture"
    assert engine.sesi.pemain[2].sumber == "timeout"
    assert engine.sesi.pemain[2].skor == 0
    # setelah timeout, P2 tidak bisa menjawab soal ini lagi
    with pytest.raises(ValueError):
        engine.submit(2, "B")


def test_pemenang_dan_seri(engine):
    engine.start(jumlah_soal=2)
    benar = _jawaban_benar(engine)[1]
    salah = "A" if benar != "A" else "B"
    engine.submit(1, benar)
    engine.submit(2, salah)
    engine.next_question()
    hasil = engine.result()
    assert hasil["pemenang"] == 1
    assert hasil["seri"] is False
    assert hasil["status"] == "pemain_1"


def test_seri_ketika_skor_sama(engine):
    engine.start(jumlah_soal=2)
    benar = _jawaban_benar(engine)[1]
    engine.submit(1, benar)
    engine.submit(2, benar)
    hasil = engine.result()
    assert hasil["seri"] is True
    assert hasil["pemenang"] is None
    assert hasil["status"] == "seri"


def test_selesai_setelah_soal_terakhir(engine):
    engine.start(jumlah_soal=2)
    for i in range(2):
        engine.submit(1, "A")
        engine.submit(2, "B")
        res = engine.next_question()
        if i == 0:
            assert res["status"] == "berjalan"
        else:
            assert res["status"] == "selesai"
            assert res["hasil"]["mode"] == "battle"
            assert len(res["hasil"]["pemain"]["1"]["riwayat"]) == 2
            assert len(res["hasil"]["pemain"]["2"]["riwayat"]) == 2


def test_submit_setelah_selesai_ditolak(engine):
    engine.start(jumlah_soal=1)
    engine.submit(1, "A")
    engine.submit(2, "B")
    engine.next_question()
    with pytest.raises(ValueError, match="selesai"):
        engine.submit(1, "C")


def test_pemain_invalid_ditolak(engine):
    engine.start(jumlah_soal=1)
    with pytest.raises(ValueError, match="pemain"):
        engine.submit(3, "A")


def test_waktu_habis_server_side(engine):
    """Jam server dimajukan melewati durasi soal -> tick mencatat timeout."""
    t = {"now": 1000.0}
    e = BattleEngine(clock=lambda: t["now"])
    try:
        database.init_db()
        e.start(jumlah_soal=2)
        durasi = e.sesi.soal.durasi
        t["now"] += durasi + 1
        ev = e.tick()
        assert ev and ev["event"] == "timeout"
        assert e.sesi.pemain[1].sumber == "timeout"
        assert e.sesi.pemain[2].sumber == "timeout"
        # setelah grace, soal maju otomatis
        t["now"] += config.AUTO_ADVANCE_GRACE + 0.1
        ev2 = e.tick()
        assert ev2 and ev2["event"] == "berjalan"
        assert e.sesi.indeks == 1
    finally:
        e.stop()


def test_tidak_bisa_jawab_setelah_waktu_habis(engine):
    t = {"now": 500.0}
    e = BattleEngine(clock=lambda: t["now"])
    try:
        database.init_db()
        e.start(jumlah_soal=2)
        t["now"] += e.sesi.soal.durasi + 0.5
        with pytest.raises(ValueError, match="Waktu"):
            e.submit(1, "A")
    finally:
        e.stop()


def test_poin_konsisten_dengan_single_player():
    """Rumus poin dipakai bersama: tidak boleh ada dua versi."""
    assert hitung_poin(False, 1.0, 30) == 0
    assert hitung_poin(True, 0.0, 30) == config.POIN_BENAR + 5
    assert hitung_poin(True, 30.0, 30) == config.POIN_BENAR
    assert hitung_poin(True, 15.0, 30) == config.POIN_BENAR + 2


def test_skor_tersimpan_di_database(engine):
    engine.start(jumlah_soal=2)
    benar = _jawaban_benar(engine)[1]
    engine.submit(1, benar)
    engine.submit(2, benar)
    with database.get_conn() as conn:
        row = conn.execute(
            "SELECT mode, pemain_1, pemain_2, skor_1, skor_2 FROM sesi_permainan"
            " WHERE id=?", (engine.sesi.id,)
        ).fetchone()
        jawab = conn.execute(
            "SELECT pemain, jawaban FROM jawaban_permainan WHERE sesi_id=?"
            " ORDER BY pemain", (engine.sesi.id,)
        ).fetchall()
    assert row["mode"] == "battle"
    assert row["pemain_1"] == "Player 1"
    assert row["skor_1"] == engine.sesi.pemain[1].skor
    assert [j["pemain"] for j in jawab] == [1, 2]
