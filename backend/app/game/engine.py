"""Game engine: state sesi, timer soal, penilaian, anti jawaban ganda.

Server-authoritative:
  * Kunci jawaban tidak pernah dikirim ke browser.
  * Jawaban hanya bisa masuk lewat `submit()` yang dipanggil router.
  * Satu jawaban per pertanyaan (`satu_jawaban_per_soal`), dan sesi yang sudah
    selesai tidak bisa dijawab lagi.
  * Timer dihitung dari waktu mulai soal, bukan dari timer di JS.
"""
from __future__ import annotations

import random
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .. import config, database

HURUF = ("A", "B", "C", "D")


def hitung_poin(benar: bool, waktu_pakai: float, durasi: int) -> int:
    """Poin satu jawaban. SATU rumus untuk Single Player & 2 Player Battle.

    Aturannya: jawaban benar = POIN_BENAR + bonus kecepatan (maks 5 poin,
    menurun linear terhadap durasi soal). Jawaban salah / timeout = 0.
    Dipusatkan di sini supaya kedua mode tidak bisa menyimpang.
    """
    if not benar:
        return 0
    poin = config.POIN_BENAR
    if durasi > 0:
        poin += int(round(5 * max(0.0, 1 - waktu_pakai / durasi)))
    return poin


@dataclass
class SoalSesi:
    id: int
    pertanyaan: str
    pilihan: dict[str, str]
    jawaban: str
    kategori: str
    durasi: int
    mulai: float = field(default_factory=time.monotonic)
    # Jam yang dipakai menilai kedaluwarsa. Mode battle menyuntikkan jamnya
    # sendiri (bisa diuji tanpa menunggu waktu nyata); default perilaku lama.
    clock: Callable[[], float] = time.monotonic

    def kedaluwarsa(self) -> bool:
        """Waktu soal habis menurut jam server (bukan timer di browser)."""
        return (self.clock() - self.mulai) >= self.durasi


@dataclass
class Sesi:
    id: str
    soals: list[SoalSesi]
    indeks: int = 0
    benar: int = 0
    skor: int = 0
    status: str = "berjalan"           # berjalan | selesai
    riwayat: list[dict[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    # -- turunan -----------------------------------------------------------
    @property
    def soal(self) -> Optional[SoalSesi]:
        return self.soals[self.indeks] if self.indeks < len(self.soals) else None

    def sisa_waktu(self) -> float:
        s = self.soal
        if s is None:
            return 0.0
        return max(0.0, s.durasi - (time.monotonic() - s.mulai))

    def kedaluwarsa(self) -> bool:
        """True bila waktu soal habis (dihitung dari jam server, bukan browser)."""
        s = self.soal
        return s is not None and s.kedaluwarsa()


class GameEngine:
    """Menyimpan satu sesi aktif (kios pameran dengan satu kamera)."""

    def __init__(self):
        self._sesi: Optional[Sesi] = None
        self._last_reset = 0.0
        # Waktu monotonic kapan tick() boleh memajukan soal, atau None.
        self._pending_advance_at: Optional[float] = None

    # -- query -------------------------------------------------------------
    @property
    def sesi(self) -> Optional[Sesi]:
        return self._sesi

    def active_question_index(self) -> Optional[int]:
        s = self._sesi
        if s is None or s.status != "berjalan":
            return None
        return s.indeks

    # -- lifecycle ---------------------------------------------------------
    def start(self, jumlah_soal: Optional[int] = None) -> Sesi:
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
            )
            for r in rows
        ]
        random.shuffle(soals)  # sudah random di SQL, tetap diacak untuk pilihan

        sesi = Sesi(id=uuid.uuid4().hex[:12], soals=soals)
        sesi.soals[0].mulai = time.monotonic()
        self._sesi = sesi
        self._last_reset = time.monotonic()
        self._pending_advance_at = None
        with database.get_conn() as conn:
            conn.execute(
                "INSERT INTO sesi_permainan (id, total_soal, benar, skor, status, started_at)"
                " VALUES (?,?,0,0,'berjalan',?)",
                (sesi.id, len(soals), database.now_iso()),
            )
        return sesi

    def stop(self) -> None:
        """Akhiri sesi (dipakai saat kamera dimatikan / keluar game)."""
        if self._sesi and self._sesi.status == "berjalan":
            self._finish(self._sesi, "dibatalkan")
        self._sesi = None

    def _finish(self, sesi: Sesi, status: str) -> None:
        sesi.status = "selesai"
        with database.get_conn() as conn:
            conn.execute(
                "UPDATE sesi_permainan SET benar=?, skor=?, status=?, finished_at=? WHERE id=?",
                (sesi.benar, sesi.skor, status, database.now_iso(), sesi.id),
            )

    # -- gameplay ----------------------------------------------------------
    def submit(self, pilihan: str, sumber: str = "gesture") -> dict[str, Any]:
        """Catat jawaban untuk soal aktif. Melempar ValueError bila tidak sah.

        Waktu diperiksa di server: jawaban yang datang setelah durasi soal habis
        ditolak (dicatat sebagai timeout) supaya browser tidak bisa mengakali
        timer dengan menahan request.
        """
        sesi = self._sesi
        if sesi is None:
            raise ValueError("Belum ada permainan yang berjalan")
        if sesi.status != "berjalan":
            raise ValueError("Permainan sudah selesai")
        soal = sesi.soal
        if soal is None:
            raise ValueError("Tidak ada pertanyaan aktif")
        pilihan = (pilihan or "").upper()
        if pilihan not in HURUF:
            raise ValueError("Pilihan jawaban tidak valid")

        # Satu jawaban per soal -> mencegah duplikat meski ada dua request.
        if self._sudah_dijawab(sesi):
            raise ValueError("Soal ini sudah dijawab")

        if soal.kedaluwarsa():
            # Tandai sebagai timeout sekali, lalu tolak jawaban ini.
            self.timeout()
            self._pending_advance_at = time.monotonic() + config.AUTO_ADVANCE_GRACE
            raise ValueError("Waktu soal sudah habis")

        waktu_pakai = round(time.monotonic() - soal.mulai, 2)
        benar = pilihan == soal.jawaban
        poin = hitung_poin(benar, waktu_pakai, soal.durasi)
        if benar:
            sesi.benar += 1
        sesi.skor += poin

        entry = {
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
        sesi.riwayat.append(entry)

        with database.get_conn() as conn:
            conn.execute(
                "INSERT INTO jawaban_permainan"
                " (sesi_id, pertanyaan_id, urutan, jawaban, benar, waktu_pakai, created_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (sesi.id, soal.id, sesi.indeks, pilihan, int(benar), waktu_pakai,
                 database.now_iso()),
            )

        # Jadwalkan perpindahan soal di server. Browser biasanya memanggil
        # /next lebih dulu (feedback 1,9 detik); jadwal ini hanya jaring
        # pengaman bila tab pengunjung ditutup atau JS berhenti.
        self._pending_advance_at = time.monotonic() + config.AUTO_ADVANCE_GRACE
        return entry

    def next_question(self) -> dict[str, Any]:
        """Majukan ke soal berikutnya atau selesaikan sesi.

        Invarian penting: soal hanya boleh ditinggalkan setelah jawabannya
        TERCATAT (dijawab, timeout, atau dibatalkan). Aturan ini membuat
        pemanggilan ganda aman — bila tick() server sudah memajukan soal dan
        browser juga memanggil /next, panggilan kedua tidak melompati soal.
        """
        sesi = self._sesi
        if sesi is None:
            raise ValueError("Belum ada permainan yang berjalan")
        if sesi.status != "berjalan":
            # Sesi sudah selesai (mis. tick() server mendahului browser).
            # Kembalikan hasil akhir, bukan error 400, supaya UI bisa menutup
            # permainan dengan rapi.
            return {"status": "selesai", "hasil": self.result()}

        if not self._sudah_dijawab(sesi):
            # Soal aktif belum dijawab: jangan maju, cukup kembalikan state.
            return {"status": "berjalan", "hasil": None, "diabaikan": True}

        self._pending_advance_at = None
        sesi.indeks += 1
        if sesi.indeks >= len(sesi.soals):
            self._finish(sesi, "selesai")
            return {"status": "selesai", "hasil": self.result()}
        sesi.soal.mulai = time.monotonic()
        return {"status": "berjalan"}

    def timeout(self) -> dict[str, Any]:
        """Waktu soal habis: catat sebagai tidak dijawab."""
        sesi = self._sesi
        if sesi is None or sesi.status != "berjalan":
            raise ValueError("Tidak ada soal aktif")
        if not self._sudah_dijawab(sesi):
            soal = sesi.soal
            entry = {
                "urutan": sesi.indeks, "pertanyaan_id": soal.id,
                "pertanyaan": soal.pertanyaan, "jawaban": None,
                "jawaban_benar": soal.jawaban, "benar": False, "poin": 0,
                "waktu_pakai": float(soal.durasi), "sumber": "timeout",
            }
            sesi.riwayat.append(entry)
            with database.get_conn() as conn:
                conn.execute(
                    "INSERT INTO jawaban_permainan"
                    " (sesi_id, pertanyaan_id, urutan, jawaban, benar, waktu_pakai, created_at)"
                    " VALUES (?,?,?,NULL,0,?,?)",
                    (sesi.id, soal.id, sesi.indeks, float(soal.durasi), database.now_iso()),
                )
        return {"status": "berjalan"}

    @staticmethod
    def _sudah_dijawab(sesi: Sesi) -> bool:
        return any(r["urutan"] == sesi.indeks for r in sesi.riwayat)

    def tick(self) -> Optional[dict[str, Any]]:
        """Detak server-side: batas waktu & maju otomatis tanpa bantuan browser.

        Dipanggil berkala oleh WebSocket status dan endpoint /api/game/state.
        Tanpa ini, sesi bisa menggantung bila tab pengunjung ditutup atau timer
        di browser tidak pernah jalan.

        Catch-up: satu panggilan memproses SEMUA soal yang sudah kedaluwarsa,
        bukan hanya satu. Tanpa ini, pengunjung yang pergi 2 menit dengan timer
        5 detik meninggalkan antrean timeout yang butuh banyak polling.

        Mengembalikan event (atau None) berisi apa yang PALING AKHIR terjadi:
          {"event": "timeout", ...}  -> waktu habis, jawaban dicatat kosong
          {"event": "selesai", ...}  -> soal terakhir lewat, hasil tersedia
          {"event": "berjalan", ...} -> lanjut ke soal berikutnya
        Field "timeout_count" menandai berapa soal yang habis dalam catch-up.
        """
        sesi = self._sesi
        if sesi is None or sesi.status != "berjalan":
            return None
        soal = sesi.soal
        if soal is None:
            return None
        now = time.monotonic()
        lewat = (now - soal.mulai) - soal.durasi

        # 0) Ditinggal terlalu lama: catat timeout lalu tutup sesi sebagai
        #    "dibatalkan". Tanpa ini sesi "berjalan" menggantung di database.
        if lewat >= config.SESI_TELANTAR_DETIK and not self._sudah_dijawab(sesi):
            self.timeout()
            self._finish(sesi, "dibatalkan")
            self._pending_advance_at = None
            return {"event": "selesai", "dibatalkan": True,
                    "hasil": self.result()}

        # 1) Waktu soal habis dan belum dijawab -> catat timeout sekali.
        if lewat >= 0 and not self._sudah_dijawab(sesi):
            self.timeout()
            self._pending_advance_at = now + config.AUTO_ADVANCE_GRACE
            return {"event": "timeout", "nomor": sesi.indeks + 1,
                    "total_soal": len(sesi.soals), "skor": sesi.skor}

        # 2) Sudah dijawab / sudah timeout: maju setelah jeda feedback lewat.
        if self._pending_advance_at is not None and now >= self._pending_advance_at:
            self._pending_advance_at = None
            res = self.next_question()
            if res["status"] == "selesai":
                return {"event": "selesai", "hasil": res["hasil"]}
            return {"event": "berjalan", "state": self.public_state()}

        return None

    # -- view --------------------------------------------------------------
    def public_state(self) -> dict[str, Any]:
        """Snapshot untuk browser. TIDAK memuat kunci jawaban."""
        sesi = self._sesi
        if sesi is None:
            return {"aktif": False}
        soal = sesi.soal
        data: dict[str, Any] = {
            "aktif": True,
            "sesi_id": sesi.id,
            "status": sesi.status,
            "nomor": sesi.indeks + 1,
            "total_soal": len(sesi.soals),
            "skor": sesi.skor,
            "benar": sesi.benar,
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
        total = len(sesi.soals)
        pct = round(100 * sesi.benar / total) if total else 0
        if pct >= 90:
            predikat, pesan = "Sempurna", "Luar biasa! Kamu menguasai teknologi ini."
        elif pct >= 70:
            predikat, pesan = "Hebat", "Kerja bagus! Sedikit lagi menuju sempurna."
        elif pct >= 40:
            predikat, pesan = "Cukup Baik", "Terus berlatih, kamu pasti bisa lebih baik."
        else:
            predikat, pesan = "Pemula", "Jangan menyerah, coba lagi dan pelajari panduannya."
        return {
            "aktif": True,
            "sesi_id": sesi.id,
            "total_soal": total,
            "benar": sesi.benar,
            "salah": total - sesi.benar,
            "skor": sesi.skor,
            "persen": pct,
            "predikat": predikat,
            "pesan": pesan,
            "riwayat": sesi.riwayat,
        }
