"""Endpoint visitor: mulai permainan, jawab, lanjut, selesai.

Tidak butuh login (pengunjung pameran). Tidak ada kunci jawaban di response.
Jawaban bisa datang dari dua sumber:
  * gesture (default) -> dipicu backend saat gesture terkunci stabil
  * manual (opsional, untuk panitia/aksesibilitas) -> POST /api/game/answer
Anti-duplikat tetap dijaga game engine (satu jawaban per soal).
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, status

from .. import config, database
from ..game import engine
from ..schemas import AnswerPayload, StartPayload

router = APIRouter(prefix="/api/game", tags=["game"])


@router.post("/start")
def start(payload: StartPayload | None = None):
    """Mulai sesi baru. Jumlah soal ikut pengaturan panel admin bila tidak dikirim."""
    jumlah = payload.jumlah_soal if payload else None
    try:
        engine.start(jumlah)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    pengaturan = database.get_pengaturan()
    state = engine.public_state()
    state["konfigurasi"] = {
        "hold_detik": float(pengaturan["hold_detik"]),
        "cooldown_detik": float(pengaturan["cooldown_detik"]),
        "poin_benar": config.POIN_BENAR,
        "jumlah_soal": int(pengaturan["jumlah_soal"]),
    }
    return state


@router.get("/state")
def state():
    # Tick juga di sini, supaya sesi tetap berjalan bila pengunjung menutup
    # WebSocket tetapi masih polling state.
    event = engine.tick()
    data = engine.public_state()
    if data.get("aktif") and data.get("status") == "berjalan":
        sisa = engine.sesi.sisa_waktu() if engine.sesi else 0.0
        data["sisa_waktu"] = round(sisa, 1)
        data["kadaluarsa"] = sisa <= 0
    if event:
        data["game_event"] = event
    return data


@router.post("/answer")
def answer(payload: AnswerPayload):
    """Jawab manual (klik). Bisa dimatikan lewat SKOMDA_ALLOW_MANUAL_ANSWER=0."""
    if not config.ALLOW_MANUAL_ANSWER:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Jawaban manual dinonaktifkan. Gunakan gerakan tangan.",
        )
    try:
        entry = engine.submit(payload.pilihan, sumber="manual")
    except ValueError as exc:
        code = status.HTTP_409_CONFLICT if "sudah dijawab" in str(exc) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(code, str(exc))
    return _feedback(entry)


@router.post("/next")
def next_question():
    try:
        res = engine.next_question()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    out: dict[str, Any] = {"lanjut": res["status"]}
    if res["status"] == "selesai":
        out["hasil"] = res.get("hasil") or engine.result()
        out["state"] = engine.public_state()
    else:
        # Selalu sertakan state, termasuk saat permintaan diabaikan (soal belum
        # dijawab / server sudah memajukan lebih dulu) agar UI tidak merusak
        # tampilan dengan state kosong.
        out["state"] = engine.public_state()
        if res.get("diabaikan"):
            out["diabaikan"] = True
    return out


@router.post("/timeout")
def timeout():
    try:
        engine.timeout()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return {"ok": True, "state": engine.public_state()}


@router.get("/result")
def result():
    data = engine.result()
    if not data.get("aktif"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tidak ada hasil permainan")
    return data


@router.post("/reset")
def reset():
    engine.stop()
    return {"ok": True}


def _feedback(entry: dict[str, Any]) -> dict[str, Any]:
    """Feedback benar/salah + state berikutnya, tanpa membocorkan soal lain."""
    return {
        "benar": entry["benar"],
        "jawaban": entry["jawaban"],
        "jawaban_benar": entry["jawaban_benar"],
        "poin": entry["poin"],
        "skor": engine.sesi.skor if engine.sesi else 0,
        "penjelasan": (
            f"Tepat! Jawaban yang benar adalah {entry['jawaban_benar']}."
            if entry["benar"] else
            f"Belum tepat. Jawaban yang benar adalah {entry['jawaban_benar']}."
        ),
        "soal_terakhir": entry["urutan"] + 1 >= (len(engine.sesi.soals) if engine.sesi else 0),
    }
