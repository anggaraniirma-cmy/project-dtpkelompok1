"""Aplikasi FastAPI SKOMDA Gesture Quiz.

Satu backend melayani dua frontend terpisah:
  * Admin   : http://localhost:3000
  * Visitor : http://localhost:8080
CORS dikunci ke origin kedua frontend tersebut.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__, config, database
from .routers import admin, auth, cv, game

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("skomda")


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    log.info("Database siap: %s", config.get_db_path())
    log.info("Model MediaPipe: %s", config.MODEL_PATH)
    yield
    # Pastikan kamera dilepas saat server berhenti.
    pipe = cv.get_pipeline()
    if pipe is not None:
        pipe.close()
        log.info("Kamera dilepas")


app = FastAPI(
    title="SKOMDA Gesture Quiz API",
    description="Backend computer vision + kuis SMK Telkom Sidoarjo",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(game.router)
app.include_router(cv.router)


@app.get("/api/health")
def health():
    """Dipanggil visitor page untuk memastikan backend hidup."""
    pipe = cv.get_pipeline()
    return {
        "status": "ok",
        "versi": __version__,
        "kamera": bool(pipe and pipe.running),
        "database": str(config.get_db_path().name),
        "jawaban_manual": config.ALLOW_MANUAL_ANSWER,
    }


@app.get("/api/info")
def info():
    return {
        "sekolah": "SMK Telkom Sidoarjo",
        "aplikasi": "SKOMDA Gesture Quiz",
        "versi": __version__,
        "gesture": {
            "A": "Telunjuk terangkat",
            "B": "Telunjuk + tengah terangkat",
            "C": "Telunjuk + tengah + manis terangkat",
            "D": "Telunjuk + tengah + manis + kelingking terangkat",
        },
    }


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    """Jangan bocorkan stack trace ke pengunjung."""
    log.exception("error pada %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Terjadi kesalahan pada server. Silakan coba lagi."},
    )
