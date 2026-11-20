"""Endpoint computer vision: kontrol kamera, stream MJPEG, status, WebSocket.

Browser tidak pernah mengirim frame. Backend pemilik kamera:
  * POST /api/cv/start  -> buka webcam + pipeline (mode single / battle)
  * POST /api/cv/stop   -> tutup pipeline + RELEASE kamera
  * GET  /api/cv/stream -> multipart MJPEG (dipakai <img src> di browser)
  * WS   /api/cv/ws     -> status gesture + event kunci jawaban (single)
  * WS   /api/cv/ws/battle -> status dua pemain + event kunci per pemain
  * GET  /api/cv/live   -> status JSON (fallback bila WebSocket diblokir)

Event kunci gesture diteruskan ke game engine di sini, sehingga browser tidak
bisa memalsukan jawaban.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse

from .. import config
from ..cv.camera import CameraError
from ..cv.pipeline import VisionPipeline
from ..cv.stabilizer import GestureStabilizer
from ..game import engine
from ..game import battle as battle_mod

log = logging.getLogger("skomda.cv")
router = APIRouter(prefix="/api/cv", tags=["cv"])

_pipeline: Optional[VisionPipeline] = None
_pipeline_mode: str = "single"
_lock = threading.Lock()

# Penundaan antara gesture terkunci dan pengiriman jawaban: game engine perlu
# soal yang sedang aktif; bila tidak ada soal berjalan event diabaikan.
GESTURE_LOG: list[dict] = []
MAX_LOG = 50


def get_pipeline() -> Optional[VisionPipeline]:
    return _pipeline


def pipeline_mode() -> str:
    return _pipeline_mode


def _new_pipeline(mode: str = "single") -> VisionPipeline:
    """Pipeline baru; hold & cooldown mengikuti pengaturan panel admin.

    Pengaturan dibaca saat kamera dinyalakan (bukan per frame) supaya panitia
    bisa mengubah kepekaan gesture tanpa restart backend.
    """
    from .. import database
    p = database.get_pengaturan()
    return VisionPipeline(
        mode=mode,
        hold_seconds=float(p["hold_detik"]),
        cooldown_seconds=float(p["cooldown_detik"]),
        rearm_seconds=config.GESTURE_REARM_SECONDS,
    )


@router.post("/start")
def start_camera(mode: str = "single"):
    """Nyalakan kamera. `mode=battle` mengaktifkan deteksi dua tangan."""
    global _pipeline, _pipeline_mode
    mode = "battle" if mode == "battle" else "single"
    with _lock:
        if _pipeline is not None and _pipeline.running:
            if _pipeline.mode == mode:
                # Sesi permainan baru: lupakan identitas tangan/pemain lama
                # supaya pengunjung sebelumnya tidak "mewarisi" slot pemain.
                _pipeline.reset_tracking()
                return {"ok": True, "pesan": "Kamera sudah aktif",
                        "mode": mode, "status": _pipeline.status()}
            # Mode berbeda: lepas pipeline lama dulu agar kamera tidak dibuka
            # dua kali (gagal di Windows).
            _pipeline.close()
            _pipeline = None
        try:
            _pipeline = _new_pipeline(mode)
            _pipeline.start()
            _pipeline_mode = mode
        except CameraError as exc:
            _pipeline = None
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
        except Exception as exc:  # model hilang / MediaPipe gagal inisialisasi
            _pipeline = None
            log.exception("gagal memulai pipeline")
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"Gagal mengaktifkan kamera/MediaPipe: {exc}",
            )
    return {"ok": True, "pesan": "Kamera aktif", "mode": mode, "status": _pipeline.status()}


@router.post("/stop")
def stop_camera():
    global _pipeline
    with _lock:
        if _pipeline is None:
            return {"ok": True, "pesan": "Kamera tidak aktif"}
        pipe, _pipeline = _pipeline, None
    pipe.close()   # melepas kamera + menutup MediaPipe
    return {"ok": True, "pesan": "Kamera dilepas"}


@router.get("/live")
def live():
    if _pipeline is None:
        return {"aktif": False, "error": None}
    st = _pipeline.status()
    st["aktif"] = _pipeline.running
    return st


@router.get("/landmarks")
def landmarks():
    if _pipeline is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kamera tidak aktif")
    return _pipeline.landmarks() or {"landmarks": None}


@router.get("/photo-frame")
def photo_frame():
    """Frame terakhir TANPA overlay (kualitas 92) untuk Photo Moment."""
    from fastapi import Response
    pipe = _pipeline
    jpeg = pipe.photo_jpeg() if pipe is not None else None
    if not jpeg:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Kamera belum aktif atau belum menghasilkan frame.",
        )
    return Response(content=jpeg, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


@router.get("/stream")
def stream():
    if _pipeline is None or not _pipeline.running:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Kamera belum diaktifkan")
    return StreamingResponse(
        _pipeline.mjpeg_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store", "Connection": "close"},
    )


@router.post("/feed")
def feed(gesture: str):
    """Injeksi gesture manual (HANYA untuk pengujian/demo tanpa kamera).

    Dinonaktifkan kecuali env SKOMDA_ALLOW_FEED=1, sehingga tidak bisa dipakai
    pengunjung untuk menipu game.
    """
    import os
    if os.getenv("SKOMDA_ALLOW_FEED") != "1":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Endpoint demo dinonaktifkan")
    if _pipeline is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Kamera tidak aktif")
    g = gesture.upper()
    if g not in ("A", "B", "C", "D"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Gesture harus A/B/C/D")
    _pipeline.set_virtual_gesture(g, seconds=0.5)
    return {"ok": True, "gesture": g}


# --- jembatan gesture -> game ---------------------------------------------

def _apply_gesture(gesture: str) -> Optional[dict]:
    """Teruskan jawaban gesture ke engine single player."""
    try:
        entry = engine.submit(gesture, sumber="gesture")
    except ValueError:
        return None
    GESTURE_LOG.append(
        {"waktu": time.strftime("%H:%M:%S"), "gesture": gesture,
         "benar": entry["benar"], "soal": entry["urutan"] + 1}
    )
    del GESTURE_LOG[:-MAX_LOG]
    return entry


def _apply_battle_gesture(pemain: int, gesture: str) -> Optional[dict]:
    """Teruskan jawaban gesture ke engine battle untuk SATU pemain."""
    try:
        entry = battle_mod.battle_engine.submit(pemain, gesture, sumber="gesture")
    except ValueError:
        return None
    GESTURE_LOG.append(
        {"waktu": time.strftime("%H:%M:%S"), "pemain": pemain, "gesture": gesture,
         "benar": entry["benar"], "soal": entry["urutan"] + 1}
    )
    del GESTURE_LOG[:-MAX_LOG]
    return entry


@router.websocket("/ws")
async def ws_status(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # Mode battle memakai endpoint terpisah supaya kontrak mode single
            # tidak berubah sedikit pun.
            if _pipeline is not None and _pipeline.mode == "battle":
                await websocket.send_text(json.dumps(
                    {"tipe": "salah_mode",
                     "pesan": "Kamera aktif dalam mode 2 Player. Gunakan /api/cv/ws/battle."}
                ))
                await asyncio.sleep(0.5)
                continue

            if _pipeline is None:
                # Kamera belum aktif: tetap jalankan tick agar sesi tidak
                # menggantung bila kamera gagal dinyalakan.
                ev = engine.tick()
                payload: dict = {"tipe": "offline"}
                if ev:
                    payload["game_event"] = ev
                await websocket.send_text(json.dumps(payload))
                await asyncio.sleep(0.4)
                continue

            st = _pipeline.status()
            event = engine.tick()
            payload = {
                "tipe": "status",
                "kamera": st,
                "game": {
                    "nomor": (engine.sesi.indeks + 1) if engine.sesi else None,
                    "status": engine.sesi.status if engine.sesi else None,
                    "sisa_waktu": round(engine.sesi.sisa_waktu(), 1) if engine.sesi else None,
                    "skor": engine.sesi.skor if engine.sesi else 0,
                },
            }

            gesture = _pipeline.pop_lock()
            if gesture:
                entry = _apply_gesture(gesture)
                payload["kunci"] = gesture
                if entry:
                    payload["jawaban"] = {
                        "benar": entry["benar"],
                        "jawaban": entry["jawaban"],
                        "jawaban_benar": entry["jawaban_benar"],
                        "poin": entry["poin"],
                        "skor": engine.sesi.skor if engine.sesi else 0,
                        "penjelasan": (
                            f"Tepat! Jawaban benar {entry['jawaban_benar']}."
                            if entry["benar"] else
                            f"Belum tepat. Jawaban benar {entry['jawaban_benar']}."
                        ),
                    }
                else:
                    payload["diabaikan"] = "Tidak ada soal aktif / soal sudah dijawab"

            # Event dari tick: timeout / lanjut / selesai. Dikirim setelah gesture
            # diproses supaya jawaban yang sah tetap menang atas timeout.
            if event:
                payload["game_event"] = event

            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("websocket ditutup: %s", exc)


@router.websocket("/ws/battle")
async def ws_battle(websocket: WebSocket):
    """Status dua pemain + event kunci jawaban masing-masing.

    Payload:
      {"tipe":"status",
       "kamera": {...StatusPipeline dengan "pemain": {"1":..., "2":...}},
       "game": {"nomor", "total_soal", "status", "sisa_waktu", "pemain": {...}},
       "kunci": {"1":"A"},             # jawaban yang BARU terkunci
       "jawaban": {"1": {...feedback...}},
       "game_event": {...}}
    """
    await websocket.accept()
    b = battle_mod.battle_engine
    try:
        while True:
            if _pipeline is None:
                ev = b.tick()
                payload: dict = {"tipe": "offline"}
                if ev:
                    payload["game_event"] = ev
                await websocket.send_text(json.dumps(payload))
                await asyncio.sleep(0.4)
                continue

            if _pipeline.mode != "battle":
                await websocket.send_text(json.dumps(
                    {"tipe": "salah_mode",
                     "pesan": "Kamera aktif dalam mode Single Player."}
                ))
                await asyncio.sleep(0.5)
                continue

            st = _pipeline.status()
            event = b.tick()
            sesi = b.sesi
            payload = {
                "tipe": "status",
                "kamera": st,
                "game": {
                    "nomor": (sesi.indeks + 1) if sesi else None,
                    "total_soal": len(sesi.soals) if sesi else None,
                    "status": sesi.status if sesi else None,
                    "sisa_waktu": round(sesi.sisa_waktu(), 1) if sesi else None,
                    "pemain": {
                        str(p.nomor): {
                            "skor": p.skor,
                            "benar": p.benar,
                            "sudah_menjawab": p.sudah_menjawab,
                            "jawaban": p.jawaban or None,
                        }
                        for p in sesi.pemain.values()
                    } if sesi else {},
                },
            }

            # Kunci gesture per pemain. Setiap pemain hanya menerima kuncinya
            # sendiri dari stabilizer-nya sendiri (lihat pipeline.pop_locks).
            locks = _pipeline.pop_locks()
            if locks:
                payload["kunci"] = {str(p): g for p, g in locks.items()}
                jawaban: dict[str, dict] = {}
                for p, g in locks.items():
                    entry = _apply_battle_gesture(p, g)
                    if entry:
                        p_state = sesi.pemain[p] if sesi else None
                        jawaban[str(p)] = {
                            "pemain": p,
                            "nama": entry["nama"],
                            "benar": entry["benar"],
                            "jawaban": entry["jawaban"],
                            "jawaban_benar": entry["jawaban_benar"],
                            "poin": entry["poin"],
                            "skor": p_state.skor if p_state else 0,
                            "penjelasan": (
                                f"Tepat! Jawaban benar {entry['jawaban_benar']}."
                                if entry["benar"] else
                                f"Belum tepat. Jawaban benar {entry['jawaban_benar']}."
                            ),
                        }
                if jawaban:
                    payload["jawaban"] = jawaban

            if event:
                payload["game_event"] = event
                # Soal baru: wajib lepas tangan dulu sebelum bisa mengunci lagi.
                # Tanpa ini, tangan yang masih terangkat dari soal sebelumnya
                # bisa langsung menjawab soal berikutnya.
                if event.get("event") in ("berjalan", "timeout"):
                    _pipeline.disarm_stabilizers()

            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("websocket battle ditutup: %s", exc)
