/* =========================================================================
   SKOMDA Gesture Quiz — 2 PLAYER BATTLE
   Sama seperti mode single: browser TIDAK memutuskan jawaban. Semua skor,
   waktu, dan status jawaban datang dari backend (/api/battle/*, WebSocket).
   ========================================================================= */
(function () {
  'use strict';

  const API = window.SKOMDA_API || 'http://localhost:8000';
  const WS_URL = API.replace(/^http/, 'ws') + '/api/cv/ws/battle';
  const $ = (s) => document.querySelector(s);

  const B = {
    ws: null,
    wsRetry: 0,
    active: false,
    game: null,
    timerHandle: null,
    deadline: 0,
    duration: 30,
    answered: { 1: false, 2: false },
    lastIndex: null,
    advanceTimer: null,
    manualMode: false,
    manualAllowed: true,
    result: null,
  };

  function toast(msg, isError) {
    if (window.skomdaToast) return window.skomdaToast(msg, isError);
    const el = $('#toast');
    if (!el) return;
    el.textContent = msg;
    el.classList.toggle('is-error', !!isError);
    el.classList.add('is-show');
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.remove('is-show'), 3400);
  }

  async function api(path, options) {
    if (window.skomdaApi) return window.skomdaApi(path, options);
    const res = await fetch(API + path, {
      headers: { 'Content-Type': 'application/json' },
      ...(options || {}),
    });
    let data = null;
    try { data = await res.json(); } catch (_) {}
    if (!res.ok) {
      const msg = (data && (data.detail || data.message)) || `Permintaan gagal (${res.status})`;
      throw new Error(typeof msg === 'string' ? msg : 'Permintaan gagal');
    }
    return data;
  }

  function showScreen(name) {
    if (window.skomdaShowScreen) return window.skomdaShowScreen(name);
    document.querySelectorAll('.screen').forEach((s) => {
      s.classList.toggle('is-active', s.id === `screen-${name}`);
    });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  /* ------------------------------------------------------------- start */
  async function startBattle() {
    const btn = $('#btnStartBattle');
    const label = btn.querySelector('span');
    const original = label.textContent;
    btn.disabled = true;
    label.textContent = 'MENYIAPKAN…';
    try {
      // Kamera dulu, mode battle -> MediaPipe diminta mendeteksi 2 tangan.
      const cam = await api('/api/cv/start?mode=battle', { method: 'POST' }).catch((e) => {
        toast('Kamera: ' + e.message, true);
        return null;
      });

      const gs = await api('/api/battle/start', { method: 'POST', body: '{}' });
      B.game = gs;
      B.active = true;
      B.answered = { 1: false, 2: false };
      B.lastIndex = null;
      B.manualMode = false;
      $('#bManualWrap').classList.remove('is-show');

      showScreen('battle');
      renderBattleQuestion(gs);
      if (cam) startBattleStream();
      connectBattleWs();
    } catch (err) {
      toast(err.message, true);
    } finally {
      btn.disabled = false;
      label.textContent = original;
    }
  }

  function startBattleStream() {
    const img = $('#bCamStream');
    const offline = $('#bCamOffline');
    img.src = `${API}/api/cv/stream?t=${Date.now()}`;
    img.onload = () => offline.classList.add('is-hidden');
    img.onerror = () => {
      offline.classList.remove('is-hidden');
      $('#bCamOfflineText').textContent =
        'Kamera tidak dapat ditampilkan. Periksa izin kamera & pastikan tidak dipakai aplikasi lain.';
    };
  }

  /* ---------------------------------------------------------- rendering */
  function setPlayerName(n, name) {
    const el = $(`#bName${n}`);
    if (el) el.textContent = name.toUpperCase();
    const pe = $(`#bPanelName${n}`);
    if (pe) pe.textContent = `${name.toUpperCase()} · ${n === 1 ? 'KIRI' : 'KANAN'}`;
  }

  function renderBattleQuestion(gs) {
    if (!gs || !gs.soal) return;
    const soal = gs.soal;
    B.answered = { 1: false, 2: false };
    B.duration = soal.durasi || 30;
    B.deadline = performance.now() + B.duration * 1000;
    B.lastIndex = gs.nomor;

    $('#bKategori').textContent = soal.kategori || 'UMUM';
    $('#bIndex').textContent = `SOAL ${String(gs.nomor).padStart(2, '0')}`;
    $('#bText').textContent = soal.pertanyaan;
    $('#bProgressText').textContent = `${gs.nomor} / ${gs.total_soal}`;
    $('#bProgressBar').style.width = `${(gs.nomor / gs.total_soal) * 100}%`;

    document.querySelectorAll('#bOptions .option').forEach((opt) => {
      const key = opt.dataset.choice;
      opt.querySelector('.opt-text').textContent = soal.pilihan[key] || '—';
      opt.classList.remove('is-correct', 'is-wrong', 'is-dim', 'is-p1', 'is-p2');
      opt.disabled = true;
    });

    document.querySelectorAll('.mini-opt').forEach((b) => { b.disabled = false; });

    [1, 2].forEach((n) => {
      $(`#bFb${n}`).className = 'bp-fb';
      $(`#bFb${n}`).textContent = '';
      $(`#bPanel${n}`).classList.remove('is-locked');
      $(`#bChip${n}`).classList.remove('is-locked');
      $(`#bHold${n}`).style.width = '0%';
      $(`#bGesture${n}`).textContent = '—';
      setPlayerState(n, 'Belum jawab', false);
    });

    updateBattleScores(gs);
    startBattleTimer();
  }

  function setPlayerState(n, text, locked) {
    const el = $(`#bState${n}`);
    if (el) el.textContent = text;
    const chip = $(`#bChip${n}`);
    if (chip) chip.classList.toggle('is-locked', !!locked);
  }

  function updateBattleScores(gs) {
    const p = (gs && gs.pemain) || {};
    [1, 2].forEach((n) => {
      const data = p[String(n)] || p[n];
      if (!data) return;
      setPlayerName(n, data.nama || `Player ${n}`);
      const scoreEl = $(`#bScore${n}`);
      if (scoreEl && scoreEl.textContent !== String(data.skor)) {
        scoreEl.textContent = data.skor;
      }
      if (data.sudah_menjawab) setPlayerState(n, 'Terkunci', true);
    });
  }

  /* -------------------------------------------------------------- timer */
  function startBattleTimer() {
    clearInterval(B.timerHandle);
    const tick = () => {
      const left = Math.max(0, (B.deadline - performance.now()) / 1000);
      const total = B.duration || 30;
      const ratio = Math.max(0, Math.min(1, left / total));
      const val = $('#bTimerValue');
      if (val) val.textContent = Math.ceil(left);
      const ring = $('#bRingFg');
      if (ring) ring.style.strokeDashoffset = String(97.4 * (1 - ratio));
      // Dibatasi ke layar battle: $('#.stat-timer') global akan menunjuk timer
      // mode single player yang juga ada di halaman ini.
      const stat = document.querySelector('#screen-battle .stat-timer');
      if (stat) stat.classList.toggle('is-low', left <= 5 && left > 0);
      if (left <= 0) {
        clearInterval(B.timerHandle);
        // Waktu habis ditangani server (game_event). Browser hanya berhenti.
      }
    };
    tick();
    B.timerHandle = setInterval(tick, 100);
  }

  /* ---------------------------------------------------------- websocket */
  function connectBattleWs() {
    disconnectBattleWs();
    try {
      const ws = new WebSocket(WS_URL);
      B.ws = ws;
      ws.onopen = () => { B.wsRetry = 0; };
      ws.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch (_) { return; }
        if (msg.tipe === 'offline') {
          const off = $('#bCamOffline');
          if (off) {
            off.classList.remove('is-hidden');
            $('#bCamOfflineText').textContent = 'Kamera belum aktif. Menunggu…';
          }
          return;
        }
        if (msg.tipe === 'salah_mode') {
          toast(msg.pesan || 'Mode kamera tidak cocok', true);
          return;
        }
        handleBattleStatus(msg);
      };
      ws.onclose = () => {
        B.ws = null;
        if (!B.active) return;
        const delay = Math.min(8000, 700 * 2 ** B.wsRetry++);
        setTimeout(() => { if (B.active) connectBattleWs(); }, delay);
      };
      ws.onerror = () => { try { ws.close(); } catch (_) {} };
    } catch (err) {
      console.warn('WS battle gagal:', err);
    }
  }

  function disconnectBattleWs() {
    if (B.ws) {
      B.ws.onclose = null;
      try { B.ws.close(); } catch (_) {}
      B.ws = null;
    }
  }

  function handleBattleStatus(msg) {
    const cam = msg.kamera || {};

    if (cam.fps) {
      const el = $('#bFpsLabel');
      if (el) el.textContent = `${Math.round(cam.fps)} FPS`;
    }
    if (cam.error) {
      const off = $('#bCamOffline');
      if (off) {
        off.classList.remove('is-hidden');
        $('#bCamOfflineText').textContent = cam.error;
      }
    }

    // Status per pemain dari pipeline CV (bukan dari jawaban).
    const pemain = cam.pemain || {};
    [1, 2].forEach((n) => {
      const p = pemain[String(n)] || pemain[n];
      if (!p) return;
      const gEl = $(`#bGesture${n}`);
      const noteEl = $(`#bNote${n}`);
      const barEl = $(`#bHold${n}`);
      if (gEl) {
        gEl.textContent = p.gesture || (p.terdeteksi ? '…' : '—');
        gEl.style.color = p.gesture ? '' : 'var(--slate-400)';
      }
      if (barEl) {
        const prog = Math.max(0, Math.min(1, p.progress || 0));
        barEl.style.width = `${prog * 100}%`;
      }
      if (noteEl) {
        let txt = p.reason || '';
        let warn = false;
        if (!p.terdeteksi) {
          txt = 'Tangan belum terdeteksi di zona ini.';
          warn = true;
        } else if (p.zona_ok === false) {
          txt = `Tangan di luar zona — geser ke ${n === 1 ? 'KIRI' : 'KANAN'}.`;
          warn = true;
        } else if (p.gesture) {
          txt = `Terbaca ${p.gesture} — tahan sampai penuh.`;
        }
        noteEl.textContent = txt;
        noteEl.classList.toggle('is-warn', warn);
      }
    });

    if (Array.isArray(cam.peringatan) && cam.peringatan.length) {
      const note = $('#bCamNote');
      if (note) {
        note.textContent = cam.peringatan[0];
        note.classList.add('is-warn');
      }
    }

    // Game state: skor & status jawaban (sumber kebenaran = server).
    if (msg.game) {
      const g = msg.game;
      if (typeof g.nomor === 'number' && B.game) {
        B.game.nomor = g.nomor;
        if (g.total_soal) B.game.total_soal = g.total_soal;
      }
      if (g.pemain) {
        const obj = {};
        Object.keys(g.pemain).forEach((k) => { obj[k] = g.pemain[k]; });
        if (B.game) {
          B.game.pemain = B.game.pemain || {};
          Object.keys(obj).forEach((k) => {
            B.game.pemain[k] = { ...(B.game.pemain[k] || {}), ...obj[k] };
          });
        }
        [1, 2].forEach((n) => {
          const d = obj[String(n)];
          if (!d) return;
          const scoreEl = $(`#bScore${n}`);
          if (scoreEl && d.skor !== undefined) scoreEl.textContent = d.skor;
          if (d.sudah_menjawab) setPlayerState(n, 'Terkunci', true);
        });
      }
      if (typeof g.sisa_waktu === 'number' && !B.answered[1] && !B.answered[2]) {
        const localLeft = (B.deadline - performance.now()) / 1000;
        if (Math.abs(g.sisa_waktu - localLeft) > 1.5) {
          B.deadline = performance.now() + g.sisa_waktu * 1000;
        }
      }
    }

    // Jawaban yang baru terkunci (per pemain).
    if (msg.jawaban) {
      Object.keys(msg.jawaban).forEach((key) => {
        applyBattleFeedback(Number(key), msg.jawaban[key]);
      });
    }

    if (msg.game_event) handleBattleEvent(msg.game_event);
  }

  function applyBattleFeedback(n, fb) {
    if (!fb || B.answered[n]) return;
    B.answered[n] = true;
    setPlayerState(n, 'Terkunci', true);
    const panel = $(`#bPanel${n}`);
    if (panel) panel.classList.add('is-locked');
    const fbEl = $(`#bFb${n}`);
    if (fbEl) {
      fbEl.className = `bp-fb is-show ${fb.benar ? 'is-ok' : 'is-bad'}`;
      fbEl.textContent = fb.benar
        ? `✓ BENAR +${fb.poin} · total ${fb.skor}`
        : `✕ SALAH (kunci: ${fb.jawaban_benar}) · total ${fb.skor}`;
    }
    const scoreEl = $(`#bScore${n}`);
    if (scoreEl && fb.skor !== undefined) scoreEl.textContent = fb.skor;

    // Tandai opsi yang dipilih pemain ini.
    markOption(fb.jawaban, n, fb.benar);
    maybeAdvance();
  }

  function markOption(letter, player, correct) {
    if (!letter) return;
    const opt = document.querySelector(`#bOptions .option[data-choice="${letter}"]`);
    if (!opt) return;
    opt.classList.add(player === 1 ? 'is-p1' : 'is-p2');
    if (correct) opt.classList.add('is-correct');
    else opt.classList.add('is-wrong');
  }

  function maybeAdvance() {
    if (!B.answered[1] || !B.answered[2]) return;
    clearTimeout(B.advanceTimer);
    B.advanceTimer = setTimeout(advanceBattle, 2100);
  }

  function handleBattleEvent(ev) {
    if (ev.event === 'timeout') {
      [1, 2].forEach((n) => {
        if (B.answered[n]) return;
        B.answered[n] = true;
        const fbEl = $(`#bFb${n}`);
        if (fbEl) {
          fbEl.className = 'bp-fb is-show is-wait';
          fbEl.textContent = '⏱ Waktu habis — tidak menjawab';
        }
        setPlayerState(n, 'Waktu habis', true);
      });
      return;
    }
    if (ev.event === 'berjalan' && ev.state) {
      // Abaikan event untuk soal yang sudah ditampilkan (bisa terjadi bila
      // tick server dan panggilan /next tiba hampir bersamaan).
      if (ev.state.nomor === B.lastIndex) return;
      B.game = { ...(B.game || {}), ...ev.state };
      renderBattleQuestion(ev.state);
      return;
    }
    if (ev.event === 'selesai') {
      finishBattle(ev.hasil);
    }
  }

  /* ------------------------------------------------------------ advance */
  async function advanceBattle() {
    clearTimeout(B.advanceTimer);
    try {
      const res = await api('/api/battle/next', { method: 'POST' });
      if (res.lanjut === 'selesai') {
        finishBattle(res.hasil);
        return;
      }
      // Server bisa sudah memajukan soal (tick server-side). Jangan render
      // ulang soal yang sama — itu akan mereset timer & status jawaban.
      const nomor = res.state && res.state.nomor;
      if (res.diabaikan && nomor === B.lastIndex) return;
      B.game = res.state;
      renderBattleQuestion(res.state);
    } catch (err) {
      toast(err.message, true);
    }
  }

  async function finishBattle(hasil) {
    clearInterval(B.timerHandle);
    clearTimeout(B.advanceTimer);
    disconnectBattleWs();
    B.active = false;
    await api('/api/cv/stop', { method: 'POST' }).catch(() => {});
    const img = $('#bCamStream');
    if (img) img.removeAttribute('src');

    if (!hasil) {
      try { hasil = await api('/api/battle/result'); } catch (_) { hasil = null; }
    }
    if (!hasil || !hasil.pemain) {
      showScreen('landing');
      return;
    }
    B.result = hasil;

    [1, 2].forEach((n) => {
      const p = hasil.pemain[String(n)] || hasil.pemain[n];
      if (!p) return;
      $(`#duelName${n}`).textContent = p.nama;
      $(`#duelScore${n}`).textContent = p.skor;
      $(`#duelSub${n}`).textContent =
        `${p.benar} benar · ${p.salah} salah · ${p.persen}% akurasi`;
      const card = $(`#duel${n}`);
      const crown = $(`#crown${n}`);
      const isWinner = hasil.pemenang === n;
      card.classList.toggle('is-winner', isWinner);
      crown.style.display = isWinner ? 'inline-block' : 'none';
    });

    const status = $('#bBattleStatus');
    status.classList.remove('is-win', 'is-draw');
    if (hasil.seri) {
      status.textContent = 'SERI — skor kedua pemain sama.';
      status.classList.add('is-draw');
    } else {
      const p = hasil.pemain[String(hasil.pemenang)] || hasil.pemain[hasil.pemenang];
      status.textContent = `${p.nama} MENANG dengan ${p.skor} poin!`;
      status.classList.add('is-win');
    }

    showScreen('battle-result');
  }

  /* ------------------------------------------------------------- manual */
  function toggleBattleManual() {
    if (!B.manualAllowed) {
      toast('Jawab manual dinonaktifkan panitia. Gunakan gerakan tangan.', true);
      return;
    }
    B.manualMode = !B.manualMode;
    $('#bManualWrap').classList.toggle('is-show', B.manualMode);
    $('#bBtnManual').textContent = B.manualMode
      ? 'Gunakan kamera kembali'
      : 'Kamera bermasalah? Jawab dengan klik';
  }

  async function battleManualAnswer(player, letter) {
    if (!B.manualMode || B.answered[player]) return;
    try {
      const fb = await api('/api/battle/answer', {
        method: 'POST',
        body: JSON.stringify({ pemain: player, pilihan: letter }),
      });
      applyBattleFeedback(player, fb);
      B.game = await api('/api/battle/state');
    } catch (err) {
      toast(err.message, true);
    }
  }

  /* --------------------------------------------------------------- exit */
  async function quitBattle() {
    clearInterval(B.timerHandle);
    clearTimeout(B.advanceTimer);
    disconnectBattleWs();
    B.active = false;
    const img = $('#bCamStream');
    if (img) img.removeAttribute('src');
    await api('/api/battle/reset', { method: 'POST' }).catch(() => {});
    await api('/api/cv/stop', { method: 'POST' }).catch(() => {});
    showScreen('landing');
  }

  /* --------------------------------------------------------------- init */
  function init() {
    const startBtn = $('#btnStartBattle');
    if (startBtn) startBtn.addEventListener('click', startBattle);

    const manual = $('#bBtnManual');
    if (manual) manual.addEventListener('click', toggleBattleManual);

    const quit = $('#bBtnQuit');
    if (quit) quit.addEventListener('click', quitBattle);

    document.querySelectorAll('.manual-col .mini-opts').forEach((group) => {
      const player = Number(group.dataset.player);
      group.querySelectorAll('.mini-opt').forEach((b) => {
        b.addEventListener('click', () => battleManualAnswer(player, b.dataset.choice));
      });
    });

    const replay = $('#btnBattleReplay');
    if (replay) replay.addEventListener('click', async () => {
      await api('/api/battle/reset', { method: 'POST' }).catch(() => {});
      startBattle();
    });

    const home = $('#btnBattleHome');
    if (home) home.addEventListener('click', quitBattle);

    const photo = $('#btnPhotoBattle');
    if (photo) photo.addEventListener('click', () => {
      if (!window.skomdaOpenPhoto || !B.result) return;
      window.skomdaOpenPhoto({ mode: 'battle', hasil: B.result });
    });
  }

  // Ekspos untuk app.js / photo.js (tanpa membuat duplikat logika).
  window.skomdaBattle = {
    start: startBattle,
    quit: quitBattle,
    state: B,
    setManualAllowed(allowed) { B.manualAllowed = allowed; },
  };

  document.addEventListener('DOMContentLoaded', init);
})();
