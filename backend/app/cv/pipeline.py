"""Pipeline komputer visi: kamera -> MediaPipe -> klasifikasi -> stabilisasi.

Satu thread melakukan seluruh siklus pada frame terbaru:
  1. frame diambil dari CameraStream (di-flip oleh detector)
  2. HandLandmarker mendeteksi 21 landmark
  3. GestureClassifier menilai tiap jari
  4. GestureStabilizer menahan ~1 detik lalu mengunci
  5. frame + overlay dikodekan JPEG untuk MJPEG stream

Konsumsi event kunci dilakukan oleh game engine lewat `pop_lock()`; pipeline
tidak tahu apa-apa soal kuis (pemisahan tanggung jawab).
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import cv2
import numpy as np

from .. import config
from . import overlay
from .camera import CameraError, CameraStream
from .gesture import GestureClassifier, GestureResult
from .landmarks import HandDetector, HandObservation
from .stabilizer import GestureStabilizer


@dataclass
class PipelineStatus:
    running: bool = False
    fps: float = 0.0
    gesture: Optional[str] = None
    gesture_label: str = ""
    progress: float = 0.0
    reason: str = ""
    fingers: dict[str, bool] = field(default_factory=dict)
    thumb_folded: bool = True
    handedness: str = "None"
    cooldown: float = 0.0
    error: Optional[str] = None
    frame_id: int = 0


class VisionPipeline:
    def __init__(self, camera: Optional[CameraStream] = None,
                 detector: Optional[HandDetector] = None,
                 classifier: Optional[GestureClassifier] = None,
                 stabilizer: Optional[GestureStabilizer] = None,
                 on_lock: Optional[Callable[[str], None]] = None):
        self.camera = camera or CameraStream()
        self.detector = detector or HandDetector()
        self.classifier = classifier or GestureClassifier()
        self.stabilizer = stabilizer or GestureStabilizer(
            hold_seconds=config.GESTURE_HOLD_SECONDS,
            cooldown_seconds=config.GESTURE_COOLDOWN_SECONDS,
            rearm_seconds=config.GESTURE_REARM_SECONDS,
        )

        self._lock = threading.Lock()
        self._on_lock = on_lock or (lambda _g: None)
        self._state = PipelineStatus()
        self._obs: Optional[HandObservation] = None
        self._result: Optional[GestureResult] = None
        self._jpeg: Optional[bytes] = None
        self._fps = 0.0
        self._frames = 0
        self._fps_t0 = time.time()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._pending_lock: Optional[str] = None
        self._lock_flash_until = 0.0
        self._last_frame_id = 0
        # Sumber gesture virtual (khusus demo/pengujian): saat aktif, loop
        # memakai gesture ini alih-alih hasil kamera, sehingga stabilisasi &
        # cooldown tetap berjalan lewat jalur yang sama.
        self._virtual_gesture: Optional[str] = None
        self._virtual_until = 0.0

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self.camera.start()
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="vision", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=2.0)
        self._thread = None
        try:
            self.camera.stop()
        finally:
            with self._lock:
                self._state.running = False
                self._obs = None
                self._result = None

    def close(self) -> None:
        self.stop()
        try:
            self.detector.close()
        except Exception:
            pass

    @property
    def running(self) -> bool:
        return self._running

    # -- main loop ---------------------------------------------------------
    def _loop(self) -> None:
        with self._lock:
            self._state.running = True
        while self._running:
            frame, frame_id = self.camera.read()
            if frame is None or frame_id == self._last_frame_id:
                time.sleep(0.005)
                if self.camera.error:
                    with self._lock:
                        self._state.error = self.camera.error
                continue
            self._last_frame_id = frame_id
            try:
                self._process(frame, frame_id)
            except Exception as exc:  # jangan sampai thread mati diam-diam
                with self._lock:
                    self._state.error = f"Kesalahan pemrosesan: {exc}"
                time.sleep(0.05)

    def set_virtual_gesture(self, gesture: Optional[str], seconds: float = 0.4) -> None:
        """Pasok gesture sintetis sementara (hanya dipakai endpoint demo).

        Bertahan `seconds` supaya stabilizer sempat mengumpulkan sampel sebelum
        kembali ke hasil kamera. Nilai None tetap dianggap "tangan tidak ada"
        setelah masa berlaku habis.
        """
        with self._lock:
            self._virtual_gesture = gesture
            self._virtual_until = time.time() + seconds

    def _active_virtual(self) -> tuple[bool, Optional[str]]:
        with self._lock:
            if self._virtual_gesture is not None and time.time() < self._virtual_until:
                return True, self._virtual_gesture
            return False, None

    def _process(self, frame: np.ndarray, frame_id: int) -> None:
        obs = self.detector.detect(frame)
        result: Optional[GestureResult] = None
        gesture: Optional[str] = None
        if obs is not None:
            result = self.classifier.classify(obs, require_right=config.REQUIRE_RIGHT_HAND)
            gesture = result.gesture

        virtual, vgesture = self._active_virtual()
        if virtual:
            gesture = vgesture

        stable = self.stabilizer.update(gesture)
        if stable.locked:
            with self._lock:
                self._pending_lock = stable.locked
            self._lock_flash_until = time.time() + 0.6
            # Teruskan ke game engine SEKARANG, di thread vision, bukan menunggu
            # browser terhubung. WebSocket hanya menampilkan hasilnya.
            self._on_lock(stable.locked)

        self._frames += 1
        now = time.time()
        if now - self._fps_t0 >= 0.5:
            self._fps = self._frames / (now - self._fps_t0)
            self._frames = 0
            self._fps_t0 = now

        # Overlay digambar pada frame yang sudah di-mirror agar posisi landmark
        # (koordinat hasil inferensi mirror) jatuh tepat di atas gambar.
        mirrored = cv2.flip(frame, 1)
        flash = stable.locked if time.time() < self._lock_flash_until else None
        if result is not None and obs is not None:
            overlay.draw_landmarks(mirrored, obs, result)
        overlay.draw_hud(
            mirrored, result, stable.gesture, stable.progress,
            self.stabilizer.cooldown_remaining, self._fps, flash,
        )
        ok, buf = cv2.imencode(".jpg", mirrored, [int(cv2.IMWRITE_JPEG_QUALITY), config.STREAM_QUALITY])
        jpeg = buf.tobytes() if ok else None

        fingers = {k: v.extended for k, v in (result.fingers.items() if result else [])}
        with self._lock:
            self._jpeg = jpeg
            self._obs = obs
            self._result = result
            self._state = PipelineStatus(
                running=True,
                fps=round(self._fps, 1),
                gesture=gesture,
                gesture_label=result.label if result else "",
                progress=round(stable.progress, 3),
                reason=result.reason if result else "Tangan tidak terdeteksi",
                fingers=fingers,
                thumb_folded=result.thumb_folded if result else True,
                handedness=obs.handedness if obs else "None",
                cooldown=round(self.stabilizer.cooldown_remaining, 2),
                error=None,
                frame_id=frame_id,
            )

    # -- konsumsi state ----------------------------------------------------
    def status(self) -> dict[str, Any]:
        with self._lock:
            data = asdict(self._state)
        return data

    def frame_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._jpeg

    def landmarks(self) -> Optional[dict[str, Any]]:
        with self._lock:
            obs, result = self._obs, self._result
        if obs is None:
            return None
        return {
            "landmarks": obs.as_list(),
            "handedness": obs.handedness,
            "score": round(obs.score, 3),
            "gesture": result.gesture if result else None,
            "fingers": {k: v.extended for k, v in (result.fingers.items() if result else [])},
        }

    def pop_lock(self) -> Optional[str]:
        """Event gesture terkunci; diambil sekali (dipakai game engine)."""
        with self._lock:
            g, self._pending_lock = self._pending_lock, None
        return g

    def mjpeg_frames(self):
        """Generator multipart MJPEG untuk browser.

        Frame yang sama tidak dikirim dua kali (dibandingkan lewat frame_id),
        sehingga browser tidak menampilkan gambar basi saat inferensi lambat.
        """
        last_sent = -1
        placeholder = cv2.imencode(".jpg", overlay.placeholder(
            np.zeros((config.CAMERA_HEIGHT, config.CAMERA_WIDTH, 3), np.uint8),
            "Menyiapkan kamera..."))[1].tobytes()

        while self._running:
            with self._lock:
                jpeg = self._jpeg
                frame_id = self._state.frame_id
            if jpeg is None:
                jpeg, frame_id = placeholder, -2
            if frame_id != last_sent:
                last_sent = frame_id
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n"
                       b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                       + jpeg + b"\r\n")
            time.sleep(1 / max(config.CAMERA_FPS_TARGET, 10))
