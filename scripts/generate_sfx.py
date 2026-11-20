"""Generator sound effect lokal SKOMDA Gesture Quiz.

Menghasilkan 12 berkas WAV pendek di `frontend/visitor/assets/audio/` memakai
numpy + modul `wave` standar. Tidak ada unduhan, tidak ada layanan eksternal.

Karakter suara: modern, futuristik, ringan, energik, tidak mengagetkan —
karena itu semua efek:
  * pendek (0,04–0,7 detik),
  * memakai sine/triangle + harmonik ringan (bukan sawtooth keras),
  * dinormalisasi ke puncak 0,55 (≈ -5 dBFS) supaya tidak menusuk telinga
    di ruang pameran,
  * diberi fade-in/out 5 ms agar tidak ada "klik" digital.

Jalankan ulang kapan saja bila ingin mengubah karakter suara:

    .venv\\Scripts\\python.exe scripts\\generate_sfx.py

Berkas yang dihasilkan bisa DIGANTI manual dengan aset desain suara tanpa
mengubah kode: selama nama berkasnya sama, sfx.js akan memakai berkas baru.
"""
from __future__ import annotations

import struct
import wave
from pathlib import Path

import numpy as np

SR = 44100
OUT_DIR = Path(__file__).resolve().parent.parent / "frontend" / "visitor" / "assets" / "audio"
PEAK = 0.55


# ------------------------------------------------------------------ sintesis
def _t(dur: float) -> np.ndarray:
    return np.arange(int(SR * dur)) / SR


def nada(
    freq: float,
    dur: float,
    *,
    amp: float = 1.0,
    harmonik: float = 0.18,
    attack: float = 0.006,
    release: float = 0.10,
    glide: float | None = None,
    detune_cents: float = 0.0,
) -> np.ndarray:
    """Satu nada dengan harmonik kedua tipis dan amplop halus.

    `glide` = frekuensi akhir (sweep linear), `detune_cents` memberi sedikit
    "lebar" stereo-like pada mono agar terdengar futuristik tanpa keras.
    """
    t = _t(dur)
    if glide is None:
        f = np.full_like(t, freq)
    else:
        f = np.linspace(freq, glide, t.size)
    phase = 2 * np.pi * np.cumsum(f) / SR
    sinyal = np.sin(phase) + harmonik * np.sin(2 * phase)

    if detune_cents:
        faktor = 2 ** (detune_cents / 1200)
        phase2 = 2 * np.pi * np.cumsum(f * faktor) / SR
        sinyal = sinyal + 0.5 * np.sin(phase2)

    amp_env = np.ones_like(t)
    n = t.size
    # Amplop tidak boleh lebih panjang dari sinyal (mis. nada 45 ms dengan
    # release 100 ms) — dulu ini menyebabkan broadcast error.
    n_a = min(max(1, int(attack * SR)), max(1, n // 2))
    n_r = min(max(1, int(release * SR)), max(1, n - n_a))
    amp_env[:n_a] = np.linspace(0, 1, n_a)
    amp_env[-n_r:] *= np.linspace(1, 0, n_r)
    return amp * sinyal * amp_env


def klik(dur: float = 0.012, amp: float = 0.5) -> np.ndarray:
    """Klik pendek (shutter kamera): derau yang dibatasi + amplop cepat."""
    n = int(SR * dur)
    rng = np.random.default_rng(7)
    derau = rng.normal(0, 1, n)
    # low-pass sederhana: rata-rata bergerak
    kernel = np.ones(6) / 6
    derau = np.convolve(derau, kernel, mode="same")
    env = np.exp(-np.linspace(0, 9, n))
    return amp * derau * env


def gabung(*bagian: tuple[float, np.ndarray]) -> np.ndarray:
    """Tempel sinyal pada offset waktu (detik) lalu jumlahkan."""
    total = 0.0
    akhir = 0.0
    for offset, sinyal in bagian:
        akhir = max(akhir, offset + len(sinyal) / SR)
    buf = np.zeros(int(SR * (akhir + 0.02)))
    for offset, sinyal in bagian:
        i = int(offset * SR)
        buf[i:i + len(sinyal)] += sinyal
    return buf


def arpeggio(freqs, dur=0.13, jeda=0.085, amp=0.9, **kw) -> np.ndarray:
    bagian = []
    for i, f in enumerate(freqs):
        bagian.append((i * jeda, nada(f, dur, amp=amp, **kw)))
    return gabung(*bagian)


def simpan(nama: str, sinyal: np.ndarray) -> Path:
    """Normalisasi -> 16-bit mono -> WAV; fade 5 ms untuk mencegah klik."""
    sinyal = np.asarray(sinyal, dtype=np.float64)
    puncak = float(np.max(np.abs(sinyal))) or 1.0
    sinyal = sinyal / puncak * PEAK
    n_fade = int(0.005 * SR)
    if sinyal.size > 2 * n_fade:
        sinyal[:n_fade] *= np.linspace(0, 1, n_fade)
        sinyal[-n_fade:] *= np.linspace(1, 0, n_fade)
    data = (sinyal * 32767).astype("<i2").tobytes()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / nama
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data)
    return path


# ------------------------------------------------------------------- efek
def efek() -> dict[str, np.ndarray]:
    C5, E5, G5, C6 = 523.25, 659.25, 783.99, 1046.50
    A5, E6 = 880.00, 1318.51

    return {
        # 1. permainan dimulai: arpeggio naik, tegas tapi lembut
        "game_start": arpeggio([C5, E5, G5, C6], dur=0.16, jeda=0.085,
                               amp=0.85, harmonik=0.22),

        # 2. pertanyaan muncul: dua ping pendek
        "question_appear": gabung(
            (0.00, nada(A5, 0.11, amp=0.55, harmonik=0.12)),
            (0.085, nada(E6, 0.13, amp=0.42, harmonik=0.10)),
        ),

        # 3. gesture mulai terdeteksi: blip sangat pendek (sering berulang)
        "gesture_detected": nada(1420, 0.045, amp=0.30, harmonik=0.05,
                                 attack=0.003, release=0.03),

        # 4. jawaban terkunci: konfirmasi dua nada
        "answer_locked": gabung(
            (0.00, nada(660, 0.09, amp=0.6, harmonik=0.1)),
            (0.075, nada(880, 0.12, amp=0.55, harmonik=0.1)),
        ),

        # 5. jawaban benar: akor mayor pendek
        "answer_correct": gabung(
            (0.00, nada(C5, 0.36, amp=0.5, harmonik=0.15)),
            (0.00, nada(E5, 0.36, amp=0.4, harmonik=0.15)),
            (0.00, nada(G5, 0.36, amp=0.35, harmonik=0.15)),
        ),

        # 6. jawaban salah: dua nada turun, volume lebih rendah (tidak menghukum)
        "answer_wrong": gabung(
            (0.00, nada(392, 0.16, amp=0.42, harmonik=0.1, detune_cents=6)),
            (0.13, nada(311, 0.20, amp=0.38, harmonik=0.1, detune_cents=6)),
        ),

        # 7. timer hampir habis: dua beep kecil
        "timer_low": gabung(
            (0.00, nada(880, 0.07, amp=0.35, harmonik=0.06)),
            (0.12, nada(880, 0.07, amp=0.30, harmonik=0.06)),
        ),

        # 8. pergantian pertanyaan: whoosh pendek (sweep naik)
        "question_change": nada(420, 0.22, amp=0.32, harmonik=0.08,
                                glide=980, attack=0.01, release=0.14),

        # 9. pemain menang: fanfare + akor akhir
        "player_win": gabung(
            (0.00, nada(C5, 0.12, amp=0.6, harmonik=0.2)),
            (0.10, nada(E5, 0.12, amp=0.6, harmonik=0.2)),
            (0.20, nada(G5, 0.12, amp=0.6, harmonik=0.2)),
            (0.30, nada(C6, 0.30, amp=0.55, harmonik=0.2)),
            (0.30, nada(E6, 0.30, amp=0.32, harmonik=0.15)),
            (0.30, nada(G5 * 2, 0.30, amp=0.22, harmonik=0.15)),
        ),

        # 10. hasil seri: dua nada setara, netral
        "draw": gabung(
            (0.00, nada(E5, 0.16, amp=0.5, harmonik=0.12)),
            (0.16, nada(C5, 0.20, amp=0.5, harmonik=0.12)),
        ),

        # 11. sesi foto dimulai: klik shutter + nada naik halus
        "photo_start": gabung(
            (0.00, klik(0.014, amp=0.35)),
            (0.03, nada(600, 0.16, amp=0.3, harmonik=0.08, glide=900)),
        ),

        # 12. foto berhasil diambil: klik + lonceng kecil
        "photo_captured": gabung(
            (0.00, klik(0.014, amp=0.45)),
            (0.06, nada(C6, 0.10, amp=0.35, harmonik=0.15)),
            (0.14, nada(E6, 0.22, amp=0.3, harmonik=0.12)),
        ),
    }


def main() -> None:
    hasil = []
    for nama, sinyal in efek().items():
        path = simpan(f"{nama}.wav", sinyal)
        ukuran = path.stat().st_size
        durasi = (ukuran - 44) / 2 / SR
        hasil.append((nama, ukuran, durasi))
    print(f"Folder: {OUT_DIR}")
    for nama, ukuran, durasi in hasil:
        print(f"  {nama:<18} {ukuran / 1024:6.1f} KB  {durasi:4.2f} s")
    print(f"Total {len(hasil)} berkas.")


if __name__ == "__main__":
    main()
