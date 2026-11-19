"""Game engine mode 2 PLAYER BATTLE.

Dua pengunjung, satu kamera, satu set pertanyaan. Setiap pemain punya state
sendiri: skor, jumlah benar, jawaban terkunci, dan riwayatnya.

Invarian yang dijaga (sama ketatnya dengan mode Single Player):

  * Satu jawaban per pemain per soal. Jawaban yang sudah terkunci tidak bisa
    diubah dan tidak dihitung dua kali (`submit()` menolak pemain yang sudah
    menjawab).
  * Jawaban Player 1 TIDAK PERNAH mengubah state Player 2, dan sebaliknya.
    Keduanya disimpan pada objek `PemainBattle` terpisah.
  * Soal hanya berganti bila KEDUA pemain sudah menjawab, atau waktu habis.
    Pemain yang sudah menjawab tetap mempertahankan jawabannya saat menunggu.
  * Waktu dihitung dari jam server (`time.monotonic`), bukan timer browser.
  * Rumus poin dipakai bersama mode Single Player (`engine.hitung_poin`), jadi
    skor kedua mode selalu sebanding.
"""
from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .. import config, database
from .engine import HURUF, SoalSesi, hitung_poin

JUMLAH_PEMAIN = 2


@dataclass
class PemainBattle:
    nomor: int                       # 1 atau 2
    nama: str
    skor: int = 0
    benar: int = 0
    # -- state soal aktif (direset tiap soal) -------------------------------
    jawaban: Optional[str] = None
    poin: int = 0
    waktu_pakai: float = 0.0
    sumber: str = ""
    riwayat: list[dict[str, Any]] = field(default_factory=list)

    @property
    def sudah_menjawab(self) -> bool:
        return self.jawaban is not None

    def mulai_soal(self) -> None:
        self.jawaban = None
        self.poin = 0
        self.waktu_pakai = 0.0
        self.sumber = ""


@dataclass
class SesiBattle:
    id: str
    soals: list[SoalSesi]
    pemain: dict[int, PemainBattle]
    indeks: int = 0
    status: str = "berjalan"         # berjalan | selesai
    started_at: float = field(default_factory=time.time)

    @property
    def soal(self) -> Optional[SoalSesi]:
        return self.soals[self.indeks] if self.indeks < len(self.soals) else None

    def sisa_waktu(self) -> float:
        s = self.soal
        if s is None:
            return 0.0
        return max(0.0, s.durasi - (s.clock() - s.mulai))

    def semua_menjawab(self) -> bool:
        return all(p.sudah_menjawab for p in self.pemain.values())


def nama_default(nomor: int) -> str:
    return f"Player {nomor}"


class BattleEngine:
    """Satu sesi battle aktif (kios pameran: satu kamera, satu pertandingan)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._sesi: Optional[SesiBattle] = None
        self._pending_advance_at: Optional[float] = None
        self._clock = clock
        # Feedback terakhir per pemain, dikonsumsi WebSocket sekali.
        self._feedback: dict[int, Optional[dict[str, Any]]] = {1: None, 2: None}

    # -- query -------------------------------------------------------------
    @property
    def sesi(self) -> Optional[SesiBattle]:
        return self._sesi

    @property
    def aktif(self) -> bool:
        return self._sesi is not None and self._sesi.status == "berjalan"

    def _pastikan(self) -> SesiBattle:
        if self._sesi is None:
            raise ValueError("Belum ada pertandingan yang berjalan")
        return self._sesi

    # -- lifecycle ---------------------------------------------------------
    def start(
        self,
        jumlah_soal: Optional[int] = None,
        nama_pemain: Optional[dict[int, str]] = None,
    ) -> SesiBattle:
        pengaturan = database.get_pengaturan()
        jumlah = jumlah_soal or int(pengaturan["jumlah_soal"])
        with database.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM pertanyaan WHERE aktif = 1 ORDER BY RANDOM() LIMIT ?",
                (jumlah,),
            ).fetchall()
        if not rows:
            raise ValueError(
                "Belum ada pertanyaan aktif di database. Tambahkan lewat panel admin."
            )

        soals = [
            SoalSesi(
                id=r["id"],
                pertanyaan=r["pertanyaan"],
                pilihan={"A": r["pilihan_a"], "B": r["pilihan_b"],
                         "C": r["pilihan_c"], "D": r["pilihan_d"]},
                jawaban=r["jawaban"],
                kategori=r["kategori"],
                durasi=int(r["durasi"]),
                mulai=self._clock(),
                clock=self._clock,
            )
            for r in rows
        ]
        random.shuffle(soals)

        nama = nama_pemain or {}
        pemain = {
            n: PemainBattle(nomor=n, nama=(nama.get(n) or nama_default(n)).strip()[:24] or nama_default(n))
            for n in range(1, JUMLAH_PEMAIN + 1)
        }
        sesi = SesiBattle(id=uuid.uuid4().hex[:12], soals=soals, pemain=pemain)
        sesi.soals[0].mulai = self._clock()
        self._sesi = sesi
        self._pending_advance_at = None
        self._feedback = {1: None, 2: None}

        with database.get_conn() as conn:
            conn.execute(
                "INSERT INTO sesi_permainan"
                " (id, total_soal, benar, skor, status, started_at, mode,"
                "  pemain_1, pemain_2, skor_1, skor_2, benar_1, benar_2)"
                " VALUES (?,?,0,0,'berjalan',?,'battle',?,?,0,0,0,0)",
                (sesi.id, len(soals), database.now_iso(),
                 pemain[1].nama, pemain[2].nama),
            )
        return sesi

    def stop(self) -> None:
        if self._sesi and self._sesi.status == "berjalan":
            self._finish(self._sesi, "dibatalkan")
        self._sesi = None
        self._pending_advance_at = None
        self._feedback = {1: None, 2: None}

    def _simpan_skor(self, sesi: SesiBattle) -> None:
        """Tulis skor kedua pemain. Dipanggil tiap perubahan agar tidak hilang
        bila server mati di tengah pertandingan."""
        p1, p2 = sesi.pemain[1], sesi.pemain[2]
        with database.get_conn() as conn:
            conn.execute(
                "UPDATE sesi_permainan SET benar=?, skor=?, benar_1=?, benar_2=?,"
                " skor_1=?, skor_2=? WHERE id=?",
                (p1.benar + p2.benar, p1.skor + p2.skor,
                 p1.benar, p2.benar, p1.skor, p2.skor, sesi.id),
            )

    def _finish(self, sesi: SesiBattle, status: str) -> None:
        sesi.status = "selesai"
        p1, p2 = sesi.pemain[1], sesi.pemain[2]
        with database.get_conn() as conn:
            conn.execute(
                "UPDATE sesi_permainan SET benar=?, skor=?, benar_1=?, benar_2=?,"
                " skor_1=?, skor_2=?, status=?, finished_at=? WHERE id=?",
                (p1.benar + p2.benar, p1.skor + p2.skor,
                 p1.benar, p2.benar, p1.skor, p2.skor,
                 status, database.now_iso(), sesi.id),
            )

    # -- gameplay ----------------------------------------------------------
    def submit(self, pemain: int, pilihan: str, sumber: str = "gesture") -> dict[str, Any]:
        """Catat jawaban satu pemain. Melempar ValueError bila tidak sah."""
        sesi = self._pastikan()
        if sesi.status != "berjalan":
            raise ValueError("Pertandingan sudah selesai")
        if pemain not in sesi.pemain:
            raise ValueError("Nomor pemain tidak valid (1 atau 2)")
        soal = sesi.soal
        if soal is None:
            raise ValueError("Tidak ada pertanyaan aktif")

        pilihan = (pilihan or "").upper()
        if pilihan not in HURUF:
            raise ValueError("Pilihan jawaban tidak valid")

        p = sesi.pemain[pemain]

        # Anti jawaban ganda: berlaku per pemain, bukan per pertandingan.
        if p.sudah_menjawab:
            raise ValueError(f"{p.nama} sudah menjawab soal ini")

        if soal.kedaluwarsa():
            self.timeout()
            raise ValueError("Waktu soal sudah habis")

        waktu_pakai = round(self._clock() - soal.mulai, 2)
        benar = pilihan == soal.jawaban
        poin = hitung_poin(benar, waktu_pakai, soal.durasi)
        p.jawaban = pilihan
        p.poin = poin
        p.waktu_pakai = waktu_pakai
        p.sumber = sumber
        p.skor += poin
        if benar:
            p.benar += 1

        entry = {
            "pemain": pemain,
            "nama": p.nama,
            "urutan": sesi.indeks,
            "pertanyaan_id": soal.id,
            "pertanyaan": soal.pertanyaan,
            "jawaban": pilihan,
            "jawaban_benar": soal.jawaban,
            "benar": benar,
            "poin": poin,
            "waktu_pakai": waktu_pakai,
            "sumber": sumber,
        }
        p.riwayat.append(entry)

        with database.get_conn() as conn:
            conn.execute(
                "INSERT INTO jawaban_permainan"
                " (sesi_id, pertanyaan_id, urutan, jawaban, benar, waktu_pakai,"
                "  created_at, pemain)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (sesi.id, soal.id, sesi.indeks, pilihan, int(benar), waktu_pakai,
                 database.now_iso(), pemain),
            )
        self._simpan_skor(sesi)
        self._feedback[pemain] = entry

        # Bila keduanya sudah menjawab, jadwalkan perpindahan soal.
        if sesi.semua_menjawab():
            self._pending_advance_at = self._clock() + config.AUTO_ADVANCE_GRACE
        return entry

    def pop_feedback(self, pemain: int) -> Optional[dict[str, Any]]:
        """Feedback sekali-pakai untuk WebSocket (tidak dikirim berulang)."""
        fb = self._feedback.get(pemain)
        self._feedback[pemain] = None
        return fb

    def next_question(self) -> dict[str, Any]:
        """Majukan soal bila kedua pemain sudah menjawab (atau timeout)."""
        sesi = self._sesi
        if sesi is None:
            raise ValueError("Belum ada pertandingan yang berjalan")
        if sesi.status != "berjalan":
            return {"status": "selesai", "hasil": self.result()}

        if not sesi.semua_menjawab():
            return {"status": "berjalan", "hasil": None, "diabaikan": True,
                    "menunggu": [p.nomor for p in sesi.pemain.values() if not p.sudah_menjawab]}

        self._pending_advance_at = None
        sesi.indeks += 1
        if sesi.indeks >= len(sesi.soals):
            self._finish(sesi, "selesai")
            return {"status": "selesai", "hasil": self.result()}

        sesi.soals[sesi.indeks].mulai = self._clock()
        for p in sesi.pemain.values():
            p.mulai_soal()
        return {"status": "berjalan", "state": self.public_state()}

    def timeout(self) -> dict[str, Any]:
        """Waktu soal habis: catat pemain yang BELUM menjawab sebagai kosong.

        Pemain yang sudah menjawab tidak tersentuh — skor dan status
        kuncinya dipertahankan.
        """
        sesi = self._pastikan()
        if sesi.status != "berjalan":
            raise ValueError("Tidak ada soal aktif")
        soal = sesi.soal
        if soal is None:
            raise ValueError("Tidak ada soal aktif")

        for p in sesi.pemain.values():
            if p.sudah_menjawab:
                continue
            p.jawaban = ""
            p.poin = 0
            p.waktu_pakai = float(soal.durasi)
            p.sumber = "timeout"
            entry = {
                "pemain": p.nomor, "nama": p.nama, "urutan": sesi.indeks,
                "pertanyaan_id": soal.id, "pertanyaan": soal.pertanyaan,
                "jawaban": None, "jawaban_benar": soal.jawaban,
                "benar": False, "poin": 0,
                "waktu_pakai": float(soal.durasi), "sumber": "timeout",
            }
            p.riwayat.append(entry)
            with database.get_conn() as conn:
                conn.execute(
                    "INSERT INTO jawaban_permainan"
                    " (sesi_id, pertanyaan_id, urutan, jawaban, benar, waktu_pakai,"
                    "  created_at, pemain)"
                    " VALUES (?,?,?,NULL,0,?,?,?)",
                    (sesi.id, soal.id, sesi.indeks, float(soal.durasi),
                     database.now_iso(), p.nomor),
                )
        self._simpan_skor(sesi)
        self._pending_advance_at = self._clock() + config.AUTO_ADVANCE_GRACE
        return {"status": "berjalan"}

    def tick(self) -> Optional[dict[str, Any]]:
        """Detak server-side: batas waktu & maju otomatis tanpa bantuan browser."""
        sesi = self._sesi
        if sesi is None or sesi.status != "berjalan":
            return None
        soal = sesi.soal
        if soal is None:
            return None
        now = self._clock()
        lewat = (now - soal.mulai) - soal.durasi

        if lewat >= config.SESI_TELANTAR_DETIK and not sesi.semua_menjawab():
            self.timeout()
            self._finish(sesi, "dibatalkan")
            self._pending_advance_at = None
            return {"event": "selesai", "dibatalkan": True, "hasil": self.result()}

        if lewat >= 0 and not sesi.semua_menjawab():
            self.timeout()
            return {"event": "timeout", "nomor": sesi.indeks + 1,
                    "total_soal": len(sesi.soals), "state": self.public_state()}

        if self._pending_advance_at is not None and now >= self._pending_advance_at:
            res = self.next_question()
            if res["status"] == "selesai":
                return {"event": "selesai", "hasil": res["hasil"]}
            return {"event": "berjalan", "state": res.get("state") or self.public_state()}
        return None

    # -- view --------------------------------------------------------------
    def public_state(self) -> dict[str, Any]:
        """Snapshot untuk browser. TIDAK memuat kunci jawaban."""
        sesi = self._sesi
        if sesi is None:
            return {"aktif": False, "mode": None}
        soal = sesi.soal
        data: dict[str, Any] = {
            "aktif": True,
            "mode": "battle",
            "sesi_id": sesi.id,
            "status": sesi.status,
            "nomor": sesi.indeks + 1,
            "total_soal": len(sesi.soals),
            "pemain": {
                str(p.nomor): {
                    "nama": p.nama,
                    "skor": p.skor,
                    "benar": p.benar,
                    "sudah_menjawab": p.sudah_menjawab,
                    "jawaban": p.jawaban or None,
                    "poin": p.poin,
                }
                for p in sesi.pemain.values()
            },
        }
        if soal is not None and sesi.status == "berjalan":
            data["soal"] = {
                "pertanyaan": soal.pertanyaan,
                "pilihan": soal.pilihan,
                "kategori": soal.kategori,
                "durasi": soal.durasi,
            }
            data["sisa_waktu"] = round(sesi.sisa_waktu(), 1)
        return data

    def result(self) -> dict[str, Any]:
        sesi = self._sesi
        if sesi is None:
            return {"aktif": False}
        p1, p2 = sesi.pemain[1], sesi.pemain[2]
        pemenang = None
        if p1.skor > p2.skor:
            pemenang = 1
        elif p2.skor > p1.skor:
            pemenang = 2

        def ringkas(p: PemainBattle) -> dict[str, Any]:
            total = len(sesi.soals)
            return {
                "nomor": p.nomor,
                "nama": p.nama,
                "skor": p.skor,
                "benar": p.benar,
                "salah": total - p.benar,
                "persen": round(100 * p.benar / total) if total else 0,
                "riwayat": p.riwayat,
            }

        return {
            "aktif": True,
            "mode": "battle",
            "sesi_id": sesi.id,
            "total_soal": len(sesi.soals),
            "pemain": {str(n): ringkas(p) for n, p in sesi.pemain.items()},
            "pemenang": pemenang,            # 1 / 2 / None (= seri)
            "seri": pemenang is None,
            "status": "seri" if pemenang is None else f"pemain_{pemenang}",
        }


# Engine global untuk mode battle (sesi tunggal, seperti mode single player).
battle_engine = BattleEngine()
