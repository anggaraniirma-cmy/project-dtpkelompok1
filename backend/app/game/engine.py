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
from typing import Any, Optional

from .. import config, database

HURUF = ("A", "B", "C", "D")


@dataclass
class SoalSesi:
    id: int
    pertanyaan: str
    pilihan: dict[str, str]
    jawaban: str
    kategori: str
    durasi: int
    mulai: float = field(default_factory=time.monotonic)


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


class GameEngine:
    """Menyimpan satu sesi aktif (kios pameran dengan satu kamera)."""

    def __init__(self):
        self._sesi: Optional[Sesi] = None
        self._last_reset = 0.0

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
        jumlah = jumlah_soal or config.QUIZ_LENGTH
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
        """Catat jawaban untuk soal aktif. Melempar ValueError bila tidak sah."""
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
        if any(r["urutan"] == sesi.indeks for r in sesi.riwayat):
            raise ValueError("Soal ini sudah dijawab")

        waktu_pakai = round(time.monotonic() - soal.mulai, 2)
        benar = pilihan == soal.jawaban
        poin = 0
        if benar:
            poin = config.POIN_BENAR
            # bonus kecepatan maks 5 poin
            if soal.durasi > 0:
                poin += int(round(5 * max(0.0, 1 - waktu_pakai / soal.durasi)))
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
        return entry

    def next_question(self) -> dict[str, Any]:
        """Majukan ke soal berikutnya atau selesaikan sesi."""
        sesi = self._sesi
        if sesi is None:
            raise ValueError("Belum ada permainan yang berjalan")
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
        if not any(r["urutan"] == sesi.indeks for r in sesi.riwayat):
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
