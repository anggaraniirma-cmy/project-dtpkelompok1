"""Endpoint computer vision: kontrol kamera, stream MJPEG, status, WebSocket.

Browser tidak pernah mengirim frame. Backend pemilik kamera:
  * POST /api/cv/start  -> buka webcam + pipeline
  * POST /api/cv/stop   -> tutup pipeline + RELEASE kamera
  * GET  /api/cv/stream -> multipart MJPEG (dipakai <img src> di browser)
  * WS   /api/cv/ws     -> status gesture + event kunci jawaban
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

log = logging.getLogger("skomda.cv")
router = APIRouter(prefix="/api/cv", tags=["cv"])

_pipeline: Optional[VisionPipeline] = None
_lock = threading.Lock()

# Penundaan antara gesture terkunci dan pengiriman jawaban: game engine perlu
# soal yang sedang aktif; bila tidak ada soal berjalan event diabaikan.
GESTURE_LOG: list[dict] = []
MAX_LOG = 50


def get_pipeline() -> Optional[VisionPipeline]:
    return _pipeline


def _new_pipeline() -> VisionPipeline:
    return VisionPipeline(stabilizer=GestureStabilizer(
        hold_seconds=config.GESTURE_HOLD_SECONDS,
        cooldown_seconds=config.GESTURE_COOLDOWN_SECONDS,
        rearm_seconds=config.GESTURE_REARM_SECONDS,
    ))


@router.post("/start")
def start_camera():
    global _pipeline
    with _lock:
        if _pipeline is not None and _pipeline.running:
            return {"ok": True, "pesan": "Kamera sudah aktif", "status": _pipeline.status()}
        try:
            _pipeline = _new_pipeline()
            _pipeline.start()
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
    return {"ok": True, "pesan": "Kamera aktif", "status": _pipeline.status()}


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
    """Teruskan jawaban gesture ke engine; kembalikan feedback bila sah."""
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


@router.websocket("/ws")
async def ws_status(websocket: WebSocket):
    await websocket.accept()
    last_question = None
    try:
        while True:
            if _pipeline is None:
                await websocket.send_text(json.dumps({"tipe": "offline"}))
                await asyncio.sleep(0.4)
                continue

            st = _pipeline.status()
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

            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("websocket ditutup: %s", exc)
