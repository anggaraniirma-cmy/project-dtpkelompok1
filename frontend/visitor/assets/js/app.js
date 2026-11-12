/* =========================================================================
   SKOMDA Gesture Quiz — Visitor Panel
   Semua keputusan jawaban berasal dari backend (server-authoritative).
   Browser hanya menampilkan state + menerima event kunci dari WebSocket.
   ========================================================================= */

const API = window.SKOMDA_API || 'http://localhost:8000';
const WS_URL = API.replace(/^http/, 'ws') + '/api/cv/ws';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  screen: 'landing',
  game: null,           // state publik dari /api/game/state
  feedback: null,
  locked: false,        // jawaban soal ini sudah terkunci
  answered: false,
  ws: null,
  wsRetry: 0,
  timerHandle: null,
  deadline: 0,
  duration: 30,
  serveTime: 0,
  manualMode: false,
  manualAllowed: true,
  lastQuestionKey: null,
};

/* ------------------------------------------------------------------ utils */
function toast(msg, isError = false) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.toggle('is-error', isError);
  el.classList.add('is-show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove('is-show'), 3400);
}

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  let data = null;
  try { data = await res.json(); } catch (_) { /* respons tanpa body */ }
  if (!res.ok) {
    const msg = (data && (data.detail || data.message)) || `Permintaan gagal (${res.status})`;
    throw new Error(typeof msg === 'string' ? msg : 'Permintaan gagal');
  }
  return data;
}

function showScreen(name) {
  state.screen = name;
  $$('.screen').forEach((s) => s.classList.toggle('is-active', s.id === `screen-${name}`));
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/* ------------------------------------------------------------ health check */
async function checkApi() {
  const pill = $('#apiPill');
  const text = $('#apiPillText');
  try {
    const h = await api('/api/health');
    pill.classList.remove('is-bad'); pill.classList.add('is-ok');
    text.textContent = h.kamera ? 'Sistem siap' : 'Sistem siap · kamera standby';
    // Panitia bisa mematikan jawab manual (SKOMDA_ALLOW_MANUAL_ANSWER=0);
    // dalam mode itu tombol cadangan disembunyikan agar pengunjung tidak
    // menempuh jalur yang pasti ditolak server.
    state.manualAllowed = h.jawaban_manual !== false;
    if (!state.manualAllowed) $('#btnManual').style.display = 'none';
    return true;
  } catch (err) {
    pill.classList.remove('is-ok'); pill.classList.add('is-bad');
    text.textContent = 'Backend offline';
    return false;
  }
}

/* ------------------------------------------------------------------- game */
async function startGame() {
  const btn = $('#btnStart');
  btn.disabled = true;
  btn.querySelector('span').textContent = 'MENYIAPKAN…';
  try {
    const ok = await checkApi();
    if (!ok) throw new Error('Server backend belum berjalan di ' + API);

    // Nyalakan kamera lebih dulu agar pengunjung langsung melihat gambarnya.
    const cam = await api('/api/cv/start', { method: 'POST' }).catch((e) => {
      toast('Kamera: ' + e.message, true);
      return null;
    });

    // Jumlah soal ditentukan panitia lewat panel admin (pengaturan), jadi
    // backend dipanggil tanpa parameter jumlah_soal.
    const gs = await api('/api/game/start', { method: 'POST', body: '{}' });

    state.game = gs;
    state.locked = false;
    state.answered = false;
    state.feedback = null;
    state.lastQuestionKey = null;
    state.manualMode = false;

    showScreen('game');
    renderQuestion(gs);
    connectWs();
    if (cam) startStream();
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.disabled = false;
    btn.querySelector('span').textContent = 'MULAI BERMAIN';
  }
}

function startStream() {
  const img = $('#camStream');
  const offline = $('#camOffline');
  img.src = `${API}/api/cv/stream?t=${Date.now()}`;
  img.onload = () => {
    offline.classList.add('is-hidden');
  };
  img.onerror = () => {
    offline.classList.remove('is-hidden');
    $('#camOfflineText').textContent =
      'Kamera tidak dapat ditampilkan. Periksa izin kamera & pastikan tidak dipakai aplikasi lain.';
  };
}

function renderQuestion(gs) {
  const soal = gs.soal;
  if (!soal) return;

  state.locked = false;
  state.answered = false;
  state.duration = soal.durasi || 30;
  state.deadline = performance.now() + state.duration * 1000;

  $('#qKategori').textContent = soal.kategori || 'UMUM';
  $('#qIndex').textContent = `SOAL ${String(gs.nomor).padStart(2, '0')}`;
  $('#qText').textContent = soal.pertanyaan;
  $('#progressText').textContent = `${gs.nomor} / ${gs.total_soal}`;
  $('#progressBar').style.width = `${(gs.nomor / gs.total_soal) * 100}%`;
  $('#scoreValue').textContent = gs.skor ?? 0;

  $$('.option').forEach((opt) => {
    const key = opt.dataset.choice;
    opt.querySelector('.opt-text').textContent = soal.pilihan[key] || '—';
    opt.classList.remove('is-locked', 'is-correct', 'is-wrong', 'is-dim', 'is-clickable');
    opt.disabled = true;
    if (state.manualMode) {
      opt.classList.add('is-clickable');
      opt.disabled = false;
    }
  });

  $('#feedback').classList.remove('is-show');
  $('#detectedGesture').textContent = '—';
  $('#detectedGesture').classList.remove('is-live');
  $('#holdBar').style.width = '0%';

  // Animasi masuk kartu soal.
  const card = $('.question-card');
  card.style.animation = 'none';
  void card.offsetWidth;
  card.style.animation = 'screenIn 0.4s var(--ease) both';

  startTimer();
}

/* ------------------------------------------------------------------ timer */
function startTimer() {
  clearInterval(state.timerHandle);
  const tick = () => {
    const left = Math.max(0, (state.deadline - performance.now()) / 1000);
    updateTimerUI(left);
    if (left <= 0) {
      clearInterval(state.timerHandle);
      if (!state.answered) handleTimeout();
    }
  };
  tick();
  state.timerHandle = setInterval(tick, 100);
}

function updateTimerUI(left) {
  const total = state.duration || 30;
  const ratio = Math.max(0, Math.min(1, left / total));
  $('#timerValue').textContent = Math.ceil(left);
  const ring = $('#ringFg');
  if (ring) ring.style.strokeDashoffset = String(97.4 * (1 - ratio));
  $('.stat-timer').classList.toggle('is-low', left <= 5 && left > 0);
}

async function handleTimeout() {
  if (state.answered) return;
  state.answered = true;
  state.locked = true;
  clearInterval(state.timerHandle);
  try {
    await api('/api/game/timeout', { method: 'POST' });
    showFeedback({
      benar: false,
      jawaban: null,
      jawaban_benar: null,
      poin: 0,
      penjelasan: 'Waktu habis! Soal dilewati.',
    }, true);
    setTimeout(advance, 1900);
  } catch (err) {
    toast(err.message, true);
    advance();
  }
}

/* --------------------------------------------------------------- feedback */
function showFeedback(fb, timeout = false) {
  const el = $('#feedback');
  el.classList.toggle('is-wrong', !fb.benar);
  el.classList.add('is-show');
  $('#fbIcon').textContent = fb.benar ? '✓' : '✕';
  $('#fbTitle').textContent = timeout ? 'Waktu habis' : (fb.benar ? 'Jawaban benar!' : 'Belum tepat');
  $('#fbText').textContent = fb.penjelasan || '';
  $('#fbPoints').textContent = fb.poin > 0 ? `+${fb.poin}` : '0';

  if (fb.skor !== undefined && fb.skor !== null) {
    animateNumber($('#scoreValue'), Number($('#scoreValue').textContent) || 0, fb.skor);
  }

  // Tandai opsi
  $$('.option').forEach((opt) => {
    const key = opt.dataset.choice;
    opt.classList.remove('is-locked');
    if (fb.jawaban_benar && key === fb.jawaban_benar) opt.classList.add('is-correct');
    else if (fb.jawaban && key === fb.jawaban) opt.classList.add('is-wrong');
    else opt.classList.add('is-dim');
  });
}

function animateNumber(el, from, to) {
  // Browser boleh menangguhkan requestAnimationFrame (tab disembunyikan /
  // kios dalam mode tertentu). Tanpa jaring pengaman, skor bisa tertinggal di
  // angka lama, jadi angka akhir selalu dipasang lewat timeout.
  const dur = 500;
  const t0 = performance.now();
  let done = false;

  if (typeof requestAnimationFrame !== 'function' || document.visibilityState !== 'visible') {
    el.textContent = to;
    return;
  }

  const step = (t) => {
    if (done) return;
    const p = Math.min(1, (t - t0) / dur);
    el.textContent = Math.round(from + (to - from) * p);
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
  setTimeout(() => { done = true; el.textContent = to; }, dur + 80);
}

/* ---------------------------------------------------------------- advance */
async function advance() {
  try {
    const res = await api('/api/game/next', { method: 'POST' });
    if (res.lanjut === 'selesai') {
      finishGame(res.hasil);
      return;
    }
    state.game = res.state;
    renderQuestion(res.state);
  } catch (err) {
    toast(err.message, true);
  }
}

async function finishGame(hasil) {
  clearInterval(state.timerHandle);
  disconnectWs();
  await api('/api/cv/stop', { method: 'POST' }).catch(() => {});
  $('#camStream').removeAttribute('src');

  if (!hasil) {
    try { hasil = await api('/api/game/result'); } catch (_) { hasil = {}; }
  }

  $('#resSkor').textContent = hasil.skor ?? 0;
  $('#resBenar').textContent = hasil.benar ?? 0;
  $('#resSalah').textContent = hasil.salah ?? 0;
  $('#resPersen').textContent = `${hasil.persen ?? 0}%`;
  $('#resPredikat').textContent = hasil.predikat || 'Selesai';
  $('#resPesan').textContent = hasil.pesan || '';

  const list = $('#resList');
  list.innerHTML = '';
  (hasil.riwayat || []).forEach((r, i) => {
    const div = document.createElement('div');
    div.className = 'res-item' + (r.benar ? '' : ' is-wrong');
    div.innerHTML = `
      <span class="mark">${r.benar ? '✓' : '✕'}</span>
      <span class="txt">${i + 1}. ${escapeHtml(r.pertanyaan || '(tanpa pertanyaan)')}</span>
      <span class="ab">${r.jawaban || '—'} → ${r.jawaban_benar || '—'}</span>`;
    list.appendChild(div);
  });

  const ring = $('#srFg');
  const pct = hasil.persen ?? 0;
  ring.style.strokeDashoffset = String(326.7);
  requestAnimationFrame(() => {
    ring.style.strokeDashoffset = String(326.7 * (1 - pct / 100));
  });

  showScreen('result');
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/* -------------------------------------------------------------- websocket */
function connectWs() {
  disconnectWs();
  try {
    const ws = new WebSocket(WS_URL);
    state.ws = ws;

    ws.onopen = () => { state.wsRetry = 0; };

    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (_) { return; }
      if (msg.tipe === 'offline') {
        $('#camOffline').classList.remove('is-hidden');
        $('#camOfflineText').textContent = 'Kamera belum aktif. Menunggu…';
        return;
      }
      handleStatus(msg);
    };

    ws.onclose = () => {
      state.ws = null;
      if (state.screen !== 'game') return;
      const delay = Math.min(8000, 700 * 2 ** state.wsRetry++);
      setTimeout(() => { if (state.screen === 'game') connectWs(); }, delay);
    };

    ws.onerror = () => { try { ws.close(); } catch (_) {} };
  } catch (err) {
    console.warn('WebSocket gagal:', err);
  }
}

function disconnectWs() {
  if (state.ws) {
    state.ws.onclose = null;
    try { state.ws.close(); } catch (_) {}
    state.ws = null;
  }
}

function handleStatus(msg) {
  const cam = msg.kamera || {};

  // FPS + status kamera
  if (cam.fps) $('#fpsLabel').textContent = `${Math.round(cam.fps)} FPS`;
  if (cam.error) {
    $('#camOffline').classList.remove('is-hidden');
    $('#camOfflineText').textContent = cam.error;
  }

  // Gesture yang sedang terbaca
  const gEl = $('#detectedGesture');
  if (cam.gesture) {
    gEl.textContent = cam.gesture;
    gEl.classList.add('is-live');
  } else {
    gEl.textContent = cam.handedness && cam.handedness !== 'None' ? '…' : '—';
    gEl.classList.remove('is-live');
  }

  // Progress tahan
  const bar = $('#holdBar');
  if (bar) {
    const p = Math.max(0, Math.min(1, cam.progress || 0));
    bar.style.width = `${p * 100}%`;
    bar.style.background = p >= 1 ? 'var(--ok)' : 'var(--red)';
  }

  // Petunjuk kontekstual
  const note = $('#camNote');
  if (note && cam.reason) {
    if (!cam.handedness || cam.handedness === 'None') {
      note.textContent = 'Arahkan tangan kanan ke kamera, ibu jari terlipat.';
    } else {
      note.textContent = cam.gesture
        ? `Terbaca ${cam.gesture} — tahan posisi sampai penuh.`
        : cam.reason;
    }
  }

  // Feedback jawaban dari backend (jawaban terkunci di server)
  if (msg.jawaban && !state.answered) {
    state.answered = true;
    state.locked = true;
    clearInterval(state.timerHandle);
    showFeedback(msg.jawaban);
    setTimeout(advance, 1900);
  }

  // Sinkronkan timer dengan sisa waktu server bila selisih besar
  if (msg.game && typeof msg.game.sisa_waktu === 'number' && !state.answered) {
    const serverLeft = msg.game.sisa_waktu;
    const localLeft = (state.deadline - performance.now()) / 1000;
    if (Math.abs(serverLeft - localLeft) > 1.5) {
      state.deadline = performance.now() + serverLeft * 1000;
    }
  }

  // Event server-side: sumber kebenaran untuk timeout & perpindahan soal.
  // Browser tetap punya timer sendiri untuk tampilan, tetapi bila tab ditutup
  // atau diblokir, server yang memutuskan dan mengabari saat tersambung lagi.
  if (msg.game_event) handleGameEvent(msg.game_event);
}

function handleGameEvent(ev) {
  if (ev.event === 'timeout') {
    if (state.answered) return;
    state.answered = true;
    clearInterval(state.timerHandle);
    showFeedback({
      benar: false,
      jawaban: null,
      jawaban_benar: null,
      poin: 0,
      skor: ev.skor,
      penjelasan: 'Waktu habis! Soal dilewati.',
    }, true);
    return;
  }

  if (ev.event === 'berjalan' && ev.state) {
    // Server sudah memajukan soal; tampilkan tanpa memanggil /next lagi.
    state.answered = false;
    state.game = ev.state;
    if (ev.state.soal) renderQuestion(ev.state);
    return;
  }

  if (ev.event === 'selesai') {
    finishGame(ev.hasil);
  }
}

/* --------------------------------------------------------------- manual opt */
function toggleManual() {
  if (!state.manualAllowed) {
    toast('Jawab manual dinonaktifkan panitia. Gunakan gerakan tangan.', true);
    return;
  }
  state.manualMode = !state.manualMode;
  const on = state.manualMode;
  $('#btnManual').textContent = on
    ? 'Gunakan kamera kembali'
    : 'Kamera bermasalah? Jawab dengan klik';
  $$('.option').forEach((opt) => {
    if (state.answered) return;
    opt.classList.toggle('is-clickable', on);
    opt.disabled = !on;
  });
  toast(on ? 'Mode klik aktif — pilih jawaban dengan menekan opsi.' : 'Mode kamera aktif kembali.');
}

async function manualAnswer(letter) {
  if (!state.manualMode || state.answered) return;
  state.answered = true;
  state.locked = true;
  clearInterval(state.timerHandle);
  $$('.option').forEach((o) => { o.disabled = true; o.classList.remove('is-clickable'); });
  $('.option[data-choice="' + letter + '"]').classList.add('is-locked');
  try {
    const fb = await api('/api/game/answer', {
      method: 'POST',
      body: JSON.stringify({ pilihan: letter }),
    });
    showFeedback(fb);
    setTimeout(advance, 1900);
  } catch (err) {
    toast(err.message, true);
    state.answered = false;
  }
}

/* ------------------------------------------------------------------- exit */
async function quitGame() {
  clearInterval(state.timerHandle);
  disconnectWs();
  $('#camStream').removeAttribute('src');
  await api('/api/game/reset', { method: 'POST' }).catch(() => {});
  await api('/api/cv/stop', { method: 'POST' }).catch(() => {});
  showScreen('landing');
}

async function replay() {
  showScreen('landing');
  await api('/api/game/reset', { method: 'POST' }).catch(() => {});
  startGame();
}

/* ------------------------------------------------------------------- init */
document.addEventListener('DOMContentLoaded', () => {
  $('#footerYear').textContent = `© ${new Date().getFullYear()} SMK Telkom Sidoarjo`;

  $('#btnStart').addEventListener('click', startGame);
  $('#btnReplay').addEventListener('click', replay);
  $('#btnHome').addEventListener('click', quitGame);
  $('#btnQuit').addEventListener('click', quitGame);
  $('#btnManual').addEventListener('click', toggleManual);

  $$('.option').forEach((opt) => {
    opt.addEventListener('click', () => manualAnswer(opt.dataset.choice));
  });

  checkApi();
  setInterval(() => { if (state.screen === 'landing') checkApi(); }, 15000);

  // Lepas kamera bila tab ditutup saat bermain.
  window.addEventListener('pagehide', () => {
    if (state.screen === 'game') {
      navigator.sendBeacon?.(`${API}/api/cv/stop`);
    }
  });
});
