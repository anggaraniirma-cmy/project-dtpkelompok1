"""Router mode 2 PLAYER BATTLE + endpoint Photo Moment.

Prefix /api/battle. Pola identik dengan routers/game.py (mode single):
  * Tidak ada kunci jawaban di response.
  * Jawaban hanya masuk lewat `battle_engine.submit()` di sini (atau lewat
    WebSocket CV untuk jawaban gesture).
  * Waktu ditegakkan server-side lewat `tick()`.

Endpoint foto TIDAK menerima maupun menyimpan gambar: backend hanya menyediakan
frame terakhir agar browser bisa menyusun overlay lalu mengunduhnya sendiri.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from .. import config, database
from ..game import battle
from ..schemas import BattleAnswerPayload, BattleStartPayload

router = APIRouter(prefix="/api/battle", tags=["battle"])


@router.post("/start")
def start(payload: BattleStartPayload | None = None):
    """Mulai pertandingan 2 pemain. Nama pemain opsional (default Player 1/2)."""
    nama = {}
    jumlah = None
    if payload:
        jumlah = payload.jumlah_soal
        if payload.nama_pemain_1:
            nama[1] = payload.nama_pemain_1
        if payload.nama_pemain_2:
            nama[2] = payload.nama_pemain_2
    try:
        battle.battle_engine.start(jumlah, nama)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    pengaturan = database.get_pengaturan()
    state = battle.battle_engine.public_state()
    state["konfigurasi"] = {
        "hold_detik": float(pengaturan["hold_detik"]),
        "cooldown_detik": float(pengaturan["cooldown_detik"]),
        "poin_benar": config.POIN_BENAR,
        "jumlah_soal": int(pengaturan["jumlah_soal"]),
    }
    # Transparansi: berapa soal diminta vs dipakai (mode battle).
    diminta = int(jumlah or pengaturan["jumlah_soal"])
    dipakai = int(state.get("total_soal") or 0)
    state["permintaan_soal"] = {
        "diminta": diminta,
        "dipakai": dipakai,
        "kurang": max(0, diminta - dipakai),
    }
    return state


@router.get("/state")
def state():
    event = battle.battle_engine.tick()
    data = battle.battle_engine.public_state()
    sesi = battle.battle_engine.sesi
    if data.get("aktif") and data.get("status") == "berjalan" and sesi is not None:
        sisa = sesi.sisa_waktu()
        data["sisa_waktu"] = round(sisa, 1)
    if event:
        data["game_event"] = event
    return data


@router.post("/answer")
def answer(payload: BattleAnswerPayload):
    """Jawab manual per pemain (hanya bila jawaban manual diizinkan)."""
    if not config.ALLOW_MANUAL_ANSWER:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Jawaban manual dinonaktifkan. Gunakan gerakan tangan.",
        )
    try:
        entry = battle.battle_engine.submit(payload.pemain, payload.pilihan, sumber="manual")
    except ValueError as exc:
        msg = str(exc)
        code = status.HTTP_409_CONFLICT if "sudah menjawab" in msg else status.HTTP_400_BAD_REQUEST
        raise HTTPException(code, msg)
    return _feedback(entry)


@router.post("/next")
def next_question():
    try:
        res = battle.battle_engine.next_question()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    out: dict[str, Any] = {"lanjut": res["status"]}
    out["state"] = battle.battle_engine.public_state()
    if res["status"] == "selesai":
        out["hasil"] = res.get("hasil") or battle.battle_engine.result()
    if res.get("diabaikan"):
        out["diabaikan"] = True
        out["menunggu"] = res.get("menunggu", [])
    return out


@router.post("/timeout")
def timeout():
    try:
        battle.battle_engine.timeout()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return {"ok": True, "state": battle.battle_engine.public_state()}


@router.get("/result")
def result():
    data = battle.battle_engine.result()
    if not data.get("aktif"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tidak ada hasil pertandingan")
    return data


@router.post("/reset")
def reset():
    battle.battle_engine.stop()
    return {"ok": True}


def _feedback(entry: dict[str, Any]) -> dict[str, Any]:
    """Feedback benar/salah untuk satu pemain, tanpa membocorkan soal lain."""
    sesi = battle.battle_engine.sesi
    pemain = sesi.pemain[entry["pemain"]] if sesi else None
    return {
        "pemain": entry["pemain"],
        "nama": entry["nama"],
        "benar": entry["benar"],
        "jawaban": entry["jawaban"],
        "jawaban_benar": entry["jawaban_benar"],
        "poin": entry["poin"],
        "skor": pemain.skor if pemain else 0,
        "penjelasan": (
            f"Tepat! Jawaban yang benar adalah {entry['jawaban_benar']}."
            if entry["benar"] else
            f"Belum tepat. Jawaban yang benar adalah {entry['jawaban_benar']}."
        ),
    }
