"""Pipeline komputer visi: kamera -> MediaPipe -> klasifikasi -> stabilisasi.

Satu thread melakukan seluruh siklus pada frame terbaru:
  1. frame diambil dari CameraStream (di-flip oleh detector)
  2. HandLandmarker mendeteksi 21 landmark (1 tangan / maksimal `num_hands`)
  3. GestureClassifier menilai tiap jari
  4. GestureStabilizer menahan ~1 detik lalu mengunci
  5. frame + overlay dikodekan JPEG untuk MJPEG stream

DUA MODE
  * mode="single" : perilaku lama, tidak diubah. Satu tangan, satu stabilizer,
    satu antrean kunci (`pop_lock()`).
  * mode="battle" : dua tangan, `PlayerSplitter` memisahkan pemain berdasarkan
    posisi, dan SETIAP pemain punya stabilizer + antrean kunci sendiri
    (`pop_locks()`). Satu tangan tidak pernah bisa mengunci dua pemain.

Konsumsi event kunci dilakukan oleh game engine lewat `pop_lock()` /
`pop_locks()`; pipeline tidak tahu apa-apa soal kuis (pemisahan tanggung jawab).
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

import cv2
import numpy as np

from .. import config
from . import overlay
from .camera import CameraError, CameraStream
from .gesture import GestureClassifier, GestureResult
from .landmarks import HandDetector, HandObservation
from .players import PlayerSplitter, PlayerTracker
from .stabilizer import GestureStabilizer
from .tracking import FilterPenolakan, HandFilter, HandTracker, TrackedHand, palm_width_norm


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
    mode: str = "single"
    # mode battle: {"1": {...}, "2": {...}} — lihat _process_battle()
    pemain: dict[str, dict[str, Any]] = field(default_factory=dict)
    peringatan: list[str] = field(default_factory=list)
    # --- seleksi tangan (mode keramaian pameran) --------------------------
    # Jumlah tangan yang BENAR-BENAR dipakai sebagai input pemain.
    tangan_terlihat: int = 0
    # Jumlah kandidat mentah dari MediaPipe sebelum difilter.
    tangan_mentah: int = 0
    # Kandidat yang ditolak, dirinci per alasan: terlalu_kecil / luar_area /
    # skor_rendah. Dipakai UI untuk menjelaskan kenapa tangan tidak terbaca.
    tangan_ditolak: dict[str, int] = field(default_factory=dict)
    # Status satu pemain (single player): lihat KODE_STATUS di pipeline.
    status: str = "tidak_ada"
    # Apakah ada tangan pemain yang benar-benar terdeteksi di frame ini.
    terdeteksi: bool = False


class VisionPipeline:
    def __init__(self, camera: Optional[CameraStream] = None,
                 detector: Optional[HandDetector] = None,
                 classifier: Optional[GestureClassifier] = None,
                 stabilizer: Optional[GestureStabilizer] = None,
                 on_lock: Optional[Callable[[str], None]] = None,
                 mode: str = "single",
                 hold_seconds: Optional[float] = None,
                 cooldown_seconds: Optional[float] = None,
                 rearm_seconds: Optional[float] = None):
        self.mode = "battle" if mode == "battle" else "single"
        self.camera = camera or CameraStream()
        # Mode single sengaja meminta BEBERAPA kandidat: sistem harus bisa
        # melihat tangan orang di latar belakang lalu MENOLAKNYA, bukan
        # menerimanya sebagai satu-satunya hasil deteksi.
        num_hands = config.MAX_HANDS_BATTLE if self.mode == "battle" else config.MAX_HANDS_SINGLE
        self.detector = detector or HandDetector(num_hands=num_hands)
        self.classifier = classifier or GestureClassifier()

        # Gerbang kualitas + tracking identitas (lihat cv/tracking.py).
        self.filter = HandFilter(
            roi=config.HAND_ROI,
            min_palm_width=config.HAND_MIN_PALM_WIDTH,
        )
        self.tracker = HandTracker(
            max_miss_seconds=config.TRACK_MAX_MISS_SECONDS,
            dist_max=config.TRACK_DIST_MAX,
        )
        self.player_tracker = PlayerTracker(memory_seconds=config.PLAYER_MEMORY_SECONDS)
        # Pemilihan tangan utama (mode single) dipertahankan antar frame.
        self._primary_track: Optional[int] = None
        self._tolak_terakhir = FilterPenolakan()
        self._mentah_terakhir = 0
        self._tracked_terakhir: list[TrackedHand] = []

        # Parameter stabilizer dipakai lagi untuk pemain ke-2 di mode battle
        # supaya kedua pemain punya kepekaan yang identik.
        self._hold = config.GESTURE_HOLD_SECONDS if hold_seconds is None else hold_seconds
        self._cooldown = config.GESTURE_COOLDOWN_SECONDS if cooldown_seconds is None else cooldown_seconds
        self._rearm = config.GESTURE_REARM_SECONDS if rearm_seconds is None else rearm_seconds

        self.stabilizer = stabilizer or GestureStabilizer(
            hold_seconds=self._hold,
            cooldown_seconds=self._cooldown,
            rearm_seconds=self._rearm,
        )
        # Stabilizer per pemain (mode battle). Stabilizer tunggal di atas tetap
        # dipakai mode single supaya perilakunya persis sama seperti sebelumnya.
        self.stabilizers: dict[int, GestureStabilizer] = {
            1: self.stabilizer,
            2: GestureStabilizer(
                hold_seconds=self._hold,
                cooldown_seconds=self._cooldown,
                rearm_seconds=self._rearm,
            ),
        }
        self.splitter = PlayerSplitter()

        self._lock = threading.Lock()
        self._on_lock = on_lock or (lambda _g: None)
        self._state = PipelineStatus(mode=self.mode)
        self._obs: Optional[HandObservation] = None
        self._result: Optional[GestureResult] = None
        self._jpeg: Optional[bytes] = None
        self._raw_jpeg: Optional[bytes] = None
        self._fps = 0.0
        self._frames = 0
        self._fps_t0 = time.time()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._pending_lock: Optional[str] = None
        self._pending_player_locks: dict[int, str] = {}
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

    def reset_stabilizers(self) -> None:
        """Panggil saat soal berganti: bersihkan latch kedua pemain.

        Tanpa ini, tangan yang masih terangkat di soal berikutnya bisa langsung
        menjawab karena progres tahan dari soal sebelumnya masih tersimpan.
        """
        for s in self.stabilizers.values():
            s.reset()

    def disarm_stabilizers(self) -> None:
        """Wajib lepas tangan dulu sebelum bisa mengunci lagi."""
        for s in self.stabilizers.values():
            s.disarm()

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
                if self.mode == "battle":
                    self._process_battle(frame, frame_id)
                else:
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

    def _hitung_fps(self) -> float:
        self._frames += 1
        now = time.time()
        if now - self._fps_t0 >= 0.5:
            self._fps = self._frames / (now - self._fps_t0)
            self._frames = 0
            self._fps_t0 = now
        return self._fps

    @staticmethod
    def _encode(img: np.ndarray, quality_override: Optional[int] = None) -> Optional[bytes]:
        q = config.STREAM_QUALITY if quality_override is None else quality_override
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), q])
        return buf.tobytes() if ok else None

    # -- seleksi tangan (dipakai kedua mode) --------------------------------
    def _kandidat(self, frame: np.ndarray) -> list[TrackedHand]:
        """Deteksi -> gerbang kualitas -> tracking identitas antar frame.

        Ini titik masuk semua input gesture. Tangan yang terlalu jauh, di luar
        area permainan, atau di bawah ambang keyakinan dibuang DI SINI, sebelum
        klasifikasi dan sebelum pemilihan pemain.
        """
        mentah = self.detector.detect_many(frame)
        lolos, tolak = self.filter.saring(mentah)
        tracked = self.tracker.update(lolos)
        self._tolak_terakhir = tolak
        self._mentah_terakhir = len(mentah)
        self._tracked_terakhir = tracked
        return tracked

    def _pilih_utama(self, tracked: list[TrackedHand]) -> Optional[TrackedHand]:
        """Tangan utama mode single: yang terbesar (paling dekat kamera).

        Identitasnya dipertahankan antar frame; bila tangan pemain hilang
        sebentar, sistem TIDAK langsung berpindah ke tangan orang lain di
        belakang (itu justru sumber jawaban palsu).
        """
        by_id = {tr.id: tr for tr in tracked}
        if self._primary_track in by_id:
            return by_id[self._primary_track]
        if self._primary_track is not None and self.tracker.alive(self._primary_track):
            return None
        if not tracked:
            self._primary_track = None
            return None
        utama = max(tracked, key=lambda tr: (palm_width_norm(tr.obs), tr.obs.score))
        self._primary_track = utama.id
        return utama

    @staticmethod
    def _kode_status(
        obs: Optional[HandObservation],
        res: Optional[GestureResult],
        stable,
        zone_ok: bool = True,
        memori: bool = False,
        terkunci: bool = False,
    ) -> str:
        """Status ringkas untuk UI: satu kode, satu pesan.

        Kode: tidak_ada | memori | zona_salah | tangan_kiri | belum_valid |
        mengenali | menahan | terkunci
        """
        if obs is None:
            return "memori" if memori else "tidak_ada"
        if not zone_ok:
            return "zona_salah"
        if terkunci or stable.progress >= 0.999:
            return "terkunci"
        if stable.gesture:
            return "menahan" if stable.progress > 0 else "mengenali"
        if res is not None and not res.hand_ok:
            return "tangan_kiri"
        return "belum_valid"

    def _catatan_tolak(self) -> str:
        t = self._tolak_terakhir
        if t.total <= 0:
            return ""
        bagian = []
        if t.terlalu_kecil:
            bagian.append(f"{t.terlalu_kecil} terlalu jauh")
        if t.luar_area:
            bagian.append(f"{t.luar_area} di luar area")
        if t.skor_rendah:
            bagian.append(f"{t.skor_rendah} kurang yakin")
        return "Tangan diabaikan (" + ", ".join(bagian) + ") — dekatkan ke kamera."

    def reset_tracking(self) -> None:
        """Sesi baru: lupakan identitas tangan & pemain."""
        self.tracker.reset()
        self.player_tracker.reset()
        self._primary_track = None

    # -- pemrosesan: satu pemain -------------------------------------------
    def _process(self, frame: np.ndarray, frame_id: int) -> None:
        tracked = self._kandidat(frame)
        utama = self._pilih_utama(tracked)
        obs: Optional[HandObservation] = utama.obs if utama is not None else None

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

        self._hitung_fps()

        # Overlay digambar pada frame yang sudah di-mirror agar posisi landmark
        # (koordinat hasil inferensi mirror) jatuh tepat di atas gambar.
        mirrored = cv2.flip(frame, 1)
        flash = stable.locked if time.time() < self._lock_flash_until else None
        if result is not None and obs is not None:
            overlay.draw_landmarks(mirrored, obs, result)
        overlay.draw_hud(
            mirrored, result, stable.gesture, stable.progress,
            self.stabilizer.cooldown_remaining, self._fps, flash,
            catatan=self._catatan_tolak(),
        )
        jpeg = self._encode(mirrored)
        raw = self._encode(mirrored, quality_override=92)

        if result is not None:
            reason = result.reason
        elif self._tolak_terakhir.total:
            reason = "Tangan di luar area permainan atau terlalu jauh"
        else:
            reason = "Tangan tidak terdeteksi"

        fingers = {k: v.extended for k, v in (result.fingers.items() if result else [])}
        with self._lock:
            self._jpeg = jpeg
            self._raw_jpeg = raw
            self._obs = obs
            self._result = result
            self._state = PipelineStatus(
                running=True,
                fps=round(self._fps, 1),
                gesture=gesture,
                gesture_label=result.label if result else "",
                progress=round(stable.progress, 3),
                reason=reason,
                fingers=fingers,
                thumb_folded=result.thumb_folded if result else True,
                handedness=obs.handedness if obs else "None",
                cooldown=round(self.stabilizer.cooldown_remaining, 2),
                error=None,
                frame_id=frame_id,
                mode="single",
                terdeteksi=obs is not None,
                tangan_terlihat=1 if obs is not None else 0,
                tangan_mentah=self._mentah_terakhir,
                tangan_ditolak=self._tolak_terakhir.as_dict(),
                status=self._kode_status(obs, result, stable,
                                         terkunci=bool(stable.locked)),
            )

    # -- pemrosesan: dua pemain --------------------------------------------
    def _process_battle(self, frame: np.ndarray, frame_id: int) -> None:
        tracked = self._kandidat(frame)
        # Identitas pemain ditentukan PlayerTracker (stateful), BUKAN urutan
        # hasil MediaPipe dan bukan posisi x mentah per frame.
        split = self.player_tracker.assign(tracked)
        split.kandidat = self._mentah_terakhir
        virtual, vgesture = self._active_virtual()

        # 1) Klasifikasi sekali per pemain, lalu putuskan gesture yang sah.
        hasil: dict[int, tuple[Optional[HandObservation], Optional[GestureResult], Optional[str]]] = {}
        for p in (1, 2):
            obs = split.hands.get(p)
            res: Optional[GestureResult] = None
            gesture: Optional[str] = None
            if obs is not None:
                res = self.classifier.classify(obs, require_right=config.REQUIRE_RIGHT_HAND)
                gesture = res.gesture
                # Tangan di zona pemain yang salah tidak boleh menjawab.
                if not split.zone_ok.get(p, True):
                    gesture = None
            if virtual:
                gesture = vgesture if obs is not None else None
            hasil[p] = (obs, res, gesture)

        # 2) Stabilizer DIJALANKAN SELALU untuk kedua pemain, termasuk saat
        #    tangan tidak terdeteksi (gesture None) — itulah yang membuat latch
        #    "wajib lepas tangan" dan re-arm bekerja secara independen.
        stable_map = {}
        for p in (1, 2):
            stable = self.stabilizers[p].update(hasil[p][2])
            stable_map[p] = stable
            if stable.locked:
                with self._lock:
                    self._pending_player_locks[p] = stable.locked
                self._lock_flash_until = time.time() + 0.6

        self._hitung_fps()

        # 3) Overlay dua zona.
        mirrored = cv2.flip(frame, 1)
        flash: Optional[dict[int, str]] = None
        if time.time() < self._lock_flash_until:
            flash = {p: stable_map[p].locked for p in (1, 2) if stable_map[p].locked}
        overlay.draw_battle_overlay(
            mirrored,
            split,
            {p: hasil[p][1] for p in (1, 2)},
            {p: stable_map[p].progress for p in (1, 2)},
            {p: stable_map[p].gesture for p in (1, 2)},
            self._fps,
            flash=flash or None,
            catatan=self._catatan_tolak(),
        )
        jpeg = self._encode(mirrored)
        raw = self._encode(mirrored, quality_override=92)

        pemain_state: dict[str, dict[str, Any]] = {}
        for p in (1, 2):
            obs, res, gesture_mentah = hasil[p]
            st = stable_map[p]
            memori = bool(split.memori.get(p, False))
            reason = (res.reason if res else (
                "Tangan hilang sesaat — tetap di posisi"
                if memori else "Tangan tidak terdeteksi"))
            pemain_state[str(p)] = {
                "nomor": p,
                "terdeteksi": obs is not None,
                "gesture": st.gesture,
                "progress": round(st.progress, 3),
                "reason": reason,
                "label": res.label if res else "",
                "zona_ok": bool(split.zone_ok.get(p, True)),
                "palm_x": round(split.palm_x[p], 4) if p in split.palm_x else None,
                "cooldown": round(self.stabilizers[p].cooldown_remaining, 2),
                "handedness": obs.handedness if obs else "None",
                "track_id": split.track_id.get(p),
                "memori": memori,
                "status": self._kode_status(
                    obs, res, st,
                    zone_ok=bool(split.zone_ok.get(p, True)),
                    memori=memori,
                    terkunci=bool(st.locked),
                ),
            }

        with self._lock:
            self._jpeg = jpeg
            self._raw_jpeg = raw
            self._obs = split.hands.get(1) or split.hands.get(2)
            self._result = None
            self._state = PipelineStatus(
                running=True,
                fps=round(self._fps, 1),
                gesture=pemain_state["1"]["gesture"],
                progress=round(stable_map[1].progress, 3),
                reason=pemain_state["1"]["reason"],
                handedness=pemain_state["1"]["handedness"],
                cooldown=round(self.stabilizers[1].cooldown_remaining, 2),
                error=None,
                frame_id=frame_id,
                mode="battle",
                status=pemain_state["1"]["status"],
                terdeteksi=bool(pemain_state["1"]["terdeteksi"]),
                tangan_terlihat=len(tracked),
                tangan_mentah=self._mentah_terakhir,
                tangan_ditolak=self._tolak_terakhir.as_dict(),
                pemain=pemain_state,
                peringatan=list(split.warnings),
            )

    # -- konsumsi state ----------------------------------------------------
    def status(self) -> dict[str, Any]:
        with self._lock:
            data = asdict(self._state)
        return data

    def frame_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._jpeg

    def photo_jpeg(self) -> Optional[bytes]:
        """Frame terakhir TANPA overlay, kualitas tinggi — untuk Photo Moment.

        Dipakai endpoint /api/cv/photo. Foto diolah & disimpan di browser
        (kanvas), jadi tidak pernah dikirim ke layanan luar.
        """
        with self._lock:
            return self._raw_jpeg or self._jpeg

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
        """Event gesture terkunci mode single; diambil sekali (game engine)."""
        with self._lock:
            g, self._pending_lock = self._pending_lock, None
        return g

    def pop_locks(self) -> dict[int, str]:
        """Event kunci per pemain mode battle; diambil sekali."""
        with self._lock:
            d, self._pending_player_locks = self._pending_player_locks, {}
        return d

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
