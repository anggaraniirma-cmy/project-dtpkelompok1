"""Uji aset audio lokal (sound effect).

Yang diuji: berkas benar-benar ada, WAV valid, durasi wajar, dan daftar nama
di `sfx.js` sinkron dengan berkas di `assets/audio/`. Tidak menguji
"terdengar enak" — itu butuh telinga manusia di lokasi pameran.
"""
from __future__ import annotations

import re
import wave
from pathlib import Path

import pytest

AKAR = Path(__file__).resolve().parent.parent
AUDIO = AKAR / "frontend" / "visitor" / "assets" / "audio"
SFX_JS = AKAR / "frontend" / "visitor" / "assets" / "js" / "sfx.js"

# 12 event yang diminta spesifikasi.
WAJIB = [
    "game_start", "question_appear", "gesture_detected", "answer_locked",
    "answer_correct", "answer_wrong", "timer_low", "question_change",
    "player_win", "draw", "photo_start", "photo_captured",
]


def test_folder_audio_ada():
    assert AUDIO.is_dir(), f"folder audio tidak ada: {AUDIO}"


@pytest.mark.parametrize("nama", WAJIB)
def test_berkas_wav_ada_dan_valid(nama):
    path = AUDIO / f"{nama}.wav"
    assert path.is_file(), f"hilang: {path.name}"
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() in (44100, 48000)
        durasi = w.getnframes() / w.getframerate()
    # Pendek: tidak mengagetkan dan tidak menumpuk di pameran.
    assert 0.03 <= durasi <= 1.2, f"{nama} durasinya {durasi:.2f}s"


def test_daftar_di_sfx_js_sama_dengan_berkas():
    """Nama di JS tidak boleh menyimpang dari berkas nyata."""
    js = SFX_JS.read_text(encoding="utf-8")
    blok = re.search(r"const NAMA = \[(.*?)\];", js, re.S)
    assert blok, "const NAMA tidak ditemukan di sfx.js"
    nama_js = re.findall(r"'([a-z_]+)'", blok.group(1))
    assert nama_js == WAJIB, f"daftar di JS: {nama_js}"

    for nama in nama_js:
        assert (AUDIO / f"{nama}.wav").is_file(), f"{nama}.wav tidak ada"


def test_setiap_efek_punya_aturan_anti_tumpuk():
    js = SFX_JS.read_text(encoding="utf-8")
    for nama in WAJIB:
        assert re.search(rf"\b{nama}:\s*\{{\s*gap:", js), \
            f"{nama} tidak punya aturan gap di ATURAN"


def test_tidak_ada_autoplay_sebelum_unlock():
    """Play harus menolak sebelum unlock() dipanggil (tidak autoplay)."""
    js = SFX_JS.read_text(encoding="utf-8")
    assert "if (!S.unlocked || S.muted" in js
    assert "function unlock()" in js


def test_generator_bisa_dijalankan_ulang():
    """Skrip generator tersedia agar aset bisa dibuat ulang/diganti."""
    gen = AKAR / "scripts" / "generate_sfx.py"
    isi = gen.read_text(encoding="utf-8")
    assert "def efek()" in isi and "wave.open" in isi
    for nama in WAJIB:
        assert f'"{nama}"' in isi, f"{nama} tidak ada di generator"
