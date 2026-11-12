"""Penangkapan webcam dengan thread terpisah.

Thread kamera terus mengambil frame terbaru dan menyimpannya. Pipeline CV
tidak pernah membaca kamera langsung, jadi tidak ada back-pressure: bila
pemrosesan lambat, frame lama cukup ditimpa.

Kamera selalu dilepaskan lewat stop(); juga dicoba di __del__ sebagai jaring
pengaman bila proses berakhir normal.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

import cv2
import numpy as np

from .. import config


class CameraError(RuntimeError):
    pass


class CameraStream:
    def __init__(self, index: int = None, width: int = None, height: int = None):
        self.index = config.CAMERA_INDEX if index is None else index
        self.width = config.CAMERA_WIDTH if width is None else width
        self.height = config.CAMERA_HEIGHT if height is None else height
        self._cap: Optional[cv2.VideoCapture] = None
        self._frame: Optional[np.ndarray] = None
        self._frame_id = 0
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._fps = 0.0
        self._error: Optional[str] = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(self.index)  # fallback backend default
        if not cap.isOpened():
            cap.release()
            raise CameraError(
                f"Webcam pada index {self.index} tidak dapat dibuka. "
                "Pastikan kamera tidak dipakai aplikasi lain."
            )
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, config.CAMERA_FPS_TARGET)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._cap = cap

        ok, first = self._read_safe(cap)
        if not ok:
            cap.release()
            self._cap = None
            raise CameraError("Webcam terbuka tetapi tidak menghasilkan frame.")

        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or first.shape[1]
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or first.shape[0]
        self.width, self.height = actual_w, actual_h
        with self._lock:
            self._frame = first
            self._frame_id = 1
        self._error = None
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="camera", daemon=True)
        self._thread.start()

    @staticmethod
    def _read_safe(cap: cv2.VideoCapture):
        try:
            return cap.read()
        except cv2.error:
            return False, None

    def _loop(self) -> None:
        fails = 0
        while self._running and self._cap is not None:
            ok, frame = self._read_safe(self._cap)
            if not ok or frame is None:
                fails += 1
                if fails > 60:
                    self._error = "Kamera berhenti mengirim frame"
                    break
                time.sleep(0.02)
                continue
            fails = 0
            with self._lock:
                self._frame = frame
                self._frame_id += 1

    def read(self) -> tuple[Optional[np.ndarray], int]:
        """Frame terbaru + id-nya (id membantu pipeline melewati frame duplikat)."""
        with self._lock:
            if self._frame is None:
                return None, 0
            return self._frame, self._frame_id

    def stop(self) -> None:
        self._running = False
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.5)
        self._thread = None
        cap, self._cap = self._cap, None
        if cap is not None:
            try:
                cap.release()
            except cv2.error:
                pass
        with self._lock:
            self._frame = None

    # -- info --------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._running

    @property
    def error(self) -> Optional[str]:
        return self._error

    def measure_fps(self, window: float = 1.0) -> float:
        start_id = self.read()[1]
        t0 = time.time()
        time.sleep(window)
        self._fps = (self.read()[1] - start_id) / max(time.time() - t0, 1e-6)
        return self._fps

    def __del__(self):
        try:
            self.stop()
        except Exception:
            pass
