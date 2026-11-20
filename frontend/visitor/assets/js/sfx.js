/* =========================================================================
   SKOMDA Gesture Quiz — SFX (audio lokal)
   -------------------------------------------------------------------------
   Prinsip:
   1. TIDAK autoplay. AudioContext baru dibuat saat pengunjung menekan
      tombol MULAI (gesture pengguna). Sebelum itu semua play() diabaikan.
   2. Semua berkas berasal dari folder lokal assets/audio/ (tanpa internet).
   3. Anti-tumpuk: satu efek punya jeda minimum sendiri, dan jumlah suara
      bersamaan dibatasi, sehingga event berulang tidak menumpuk jadi bising.
   4. Mute & volume disimpan di localStorage.
   Berkas audio dihasilkan scripts/generate_sfx.py dan boleh diganti manual.
   ========================================================================= */
(function () {
  'use strict';

  const FOLDER = 'assets/audio/';
  const NAMA = [
    'game_start', 'question_appear', 'gesture_detected', 'answer_locked',
    'answer_correct', 'answer_wrong', 'timer_low', 'question_change',
    'player_win', 'draw', 'photo_start', 'photo_captured',
  ];

  // Jeda minimum antar pemutaran efek yang sama (ms) dan penguatan relatif.
  const ATURAN = {
    game_start:       { gap: 800, gain: 0.85 },
    question_appear:  { gap: 500, gain: 0.75 },
    gesture_detected: { gap: 320, gain: 0.35 },
    answer_locked:    { gap: 350, gain: 0.8 },
    answer_correct:   { gap: 600, gain: 0.8 },
    answer_wrong:     { gap: 600, gain: 0.7 },
    timer_low:        { gap: 900, gain: 0.6 },
    question_change:  { gap: 500, gain: 0.7 },
    player_win:       { gap: 1500, gain: 0.9 },
    draw:             { gap: 1500, gain: 0.8 },
    photo_start:      { gap: 800, gain: 0.7 },
    photo_captured:   { gap: 800, gain: 0.85 },
  };

  const MAKS_BERSAMAAN = 4;

  const S = {
    ctx: null,
    master: null,
    buffer: {},
    muted: false,
    volume: 0.6,
    unlocked: false,
    aktif: 0,
    terakhir: {},
    memuat: false,
  };

  /* ------------------------------------------------------------- pengaturan */
  function bacaPengaturan() {
    try {
      const m = localStorage.getItem('skomda_sfx_muted');
      if (m !== null) S.muted = m === '1';
      const v = localStorage.getItem('skomda_sfx_volume');
      if (v !== null) {
        const n = Number(v);
        if (Number.isFinite(n)) S.volume = Math.max(0, Math.min(1, n));
      }
    } catch (_) { /* localStorage bisa diblokir di kios mode */ }
  }

  function simpanPengaturan() {
    try {
      localStorage.setItem('skomda_sfx_muted', S.muted ? '1' : '0');
      localStorage.setItem('skomda_sfx_volume', String(S.volume));
    } catch (_) { /* abaikan */ }
  }

  /* ---------------------------------------------------------------- konteks */
  function buatKonteks() {
    if (S.ctx) return S.ctx;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    try {
      S.ctx = new AC();
      S.master = S.ctx.createGain();
      S.master.gain.value = S.muted ? 0 : S.volume;
      S.master.connect(S.ctx.destination);
    } catch (_) {
      S.ctx = null;
      S.master = null;
    }
    return S.ctx;
  }

  async function muatSemua() {
    if (!S.ctx || S.memuat) return;
    S.memuat = true;
    await Promise.all(NAMA.map(async (nama) => {
      if (S.buffer[nama]) return;
      try {
        const res = await fetch(`${FOLDER}${nama}.wav`, { cache: 'force-cache' });
        if (!res.ok) return;
        const data = await res.arrayBuffer();
        S.buffer[nama] = await S.ctx.decodeAudioData(data);
      } catch (_) {
        // Berkas hilang/rusak: permainan tetap jalan tanpa suara itu.
      }
    }));
    S.memuat = false;
  }

  /** Panggil dari gesture pengguna (klik MULAI). Sebelum ini: senyap total. */
  function unlock() {
    if (S.unlocked) {
      if (S.ctx && S.ctx.state === 'suspended') S.ctx.resume().catch(() => {});
      return Promise.resolve();
    }
    const ctx = buatKonteks();
    if (!ctx) return Promise.resolve();
    S.unlocked = true;
    const siap = ctx.state === 'suspended' ? ctx.resume() : Promise.resolve();
    return siap.then(muatSemua).catch(() => {});
  }

  function terapkanVolume() {
    if (!S.master || !S.ctx) return;
    const target = S.muted ? 0 : S.volume;
    try {
      S.master.gain.setTargetAtTime(target, S.ctx.currentTime, 0.02);
    } catch (_) {
      S.master.gain.value = target;
    }
  }

  /* ------------------------------------------------------------------ play */
  function play(nama) {
    if (!S.unlocked || S.muted || S.volume <= 0) return false;
    const buf = S.buffer[nama];
    if (!buf || !S.ctx) return false;

    const aturan = ATURAN[nama] || { gap: 120, gain: 0.7 };
    const now = (window.performance && performance.now) ? performance.now() : Date.now();
    const terakhir = S.terakhir[nama] || 0;
    if (now - terakhir < aturan.gap) return false;      // anti-tumpuk per efek
    if (S.aktif >= MAKS_BERSAMAAN) return false;        // anti-tumpuk global

    try {
      const src = S.ctx.createBufferSource();
      const gain = S.ctx.createGain();
      src.buffer = buf;
      gain.gain.value = Math.max(0, Math.min(1, aturan.gain));
      src.connect(gain).connect(S.master);
      S.aktif += 1;
      src.onended = () => { S.aktif = Math.max(0, S.aktif - 1); };
      src.start();
      S.terakhir[nama] = now;
      return true;
    } catch (_) {
      return false;
    }
  }

  /* -------------------------------------------------------------------- UI */
  function perbaruiUI() {
    const btn = document.getElementById('btnMute');
    const slider = document.getElementById('volumeRange');
    const label = document.getElementById('muteLabel');
    if (btn) {
      btn.classList.toggle('is-muted', S.muted);
      btn.setAttribute('aria-pressed', S.muted ? 'true' : 'false');
      btn.title = S.muted ? 'Suara mati — klik untuk menyalakan' : 'Suara aktif — klik untuk mematikan';
    }
    if (label) label.textContent = S.muted ? 'SFX OFF' : 'SFX ON';
    if (slider && document.activeElement !== slider) {
      slider.value = String(Math.round(S.volume * 100));
    }
    if (slider) slider.disabled = S.muted;
  }

  function setMuted(baru) {
    S.muted = !!baru;
    simpanPengaturan();
    terapkanVolume();
    perbaruiUI();
  }

  function setVolume(nilai) {
    const n = Number(nilai);
    if (!Number.isFinite(n)) return;
    S.volume = Math.max(0, Math.min(1, n));
    if (S.volume > 0 && S.muted) S.muted = false;
    simpanPengaturan();
    terapkanVolume();
    perbaruiUI();
  }

  function initUI() {
    const btn = document.getElementById('btnMute');
    if (btn) {
      btn.addEventListener('click', () => {
        unlock();                       // klik pertama juga membuka audio
        setMuted(!S.muted);
      });
    }
    const slider = document.getElementById('volumeRange');
    if (slider) {
      slider.addEventListener('input', () => setVolume(Number(slider.value) / 100));
      slider.addEventListener('change', () => setVolume(Number(slider.value) / 100));
    }
    perbaruiUI();
  }

  bacaPengaturan();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initUI);
  } else {
    initUI();
  }

  window.skomdaSfx = {
    play,
    unlock,
    setMuted,
    setVolume,
    isMuted: () => S.muted,
    volume: () => S.volume,
    siap: () => S.unlocked,
    daftar: NAMA.slice(),
  };
})();
