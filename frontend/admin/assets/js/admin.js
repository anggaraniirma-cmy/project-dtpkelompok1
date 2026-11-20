/* =========================================================================
   SKOMDA Gesture Quiz — Admin Panel
   Token JWT disimpan di sessionStorage (hilang saat tab ditutup).
   ========================================================================= */

const API = window.SKOMDA_API || 'http://localhost:8000';
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const TOKEN_KEY = 'skomda_admin_token';

const state = {
  token: sessionStorage.getItem(TOKEN_KEY) || null,
  admin: null,
  view: 'dashboard',
  editingId: null,
  page: 0,
  limit: 10,
  total: 0,
  filters: { q: '', kategori: '', aktif: '' },
  kategori: [],
  pendingDelete: null,
};

/* ------------------------------------------------------------------ utils */
function toast(msg, isError = true) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.toggle('is-error', isError);
  el.classList.add('is-show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove('is-show'), 3600);
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;

  let res;
  try {
    res = await fetch(API + path, { ...options, headers });
  } catch (err) {
    throw new Error('Tidak dapat menghubungi backend di ' + API);
  }

  let data = null;
  try { data = await res.json(); } catch (_) {}

  if (res.status === 401 && path !== '/api/auth/login') {
    logout(true);
    throw new Error('Sesi login berakhir. Silakan masuk kembali.');
  }
  if (!res.ok) {
    let msg = data && data.detail;
    if (Array.isArray(msg)) {
      msg = msg.map((e) => e.msg?.replace(/^Value error, /, '') || 'Input tidak valid').join(', ');
    }
    throw new Error(typeof msg === 'string' ? msg : `Permintaan gagal (${res.status})`);
  }
  return data;
}

/* ------------------------------------------------------------------- auth */
async function doLogin(e) {
  e.preventDefault();
  const btn = $('#btnLogin');
  const errEl = $('#loginError');
  errEl.classList.remove('is-show');
  btn.disabled = true;
  btn.querySelector('span').textContent = 'MEMVERIFIKASI…';

  try {
    const data = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({
        username: $('#loginUser').value.trim(),
        password: $('#loginPass').value,
      }),
    });
    state.token = data.access_token;
    state.admin = data.admin;
    sessionStorage.setItem(TOKEN_KEY, state.token);
    enterApp();
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.add('is-show');
  } finally {
    btn.disabled = false;
    btn.querySelector('span').textContent = 'MASUK';
  }
}

function logout(silent = false) {
  state.token = null;
  state.admin = null;
  sessionStorage.removeItem(TOKEN_KEY);
  $('#app').classList.remove('is-active');
  $('#loginScreen').classList.add('is-active');
  $('#loginPass').value = '';
  if (!silent) toast('Anda telah keluar.', false);
}

async function enterApp() {
  let me;
  try {
    me = await api('/api/auth/me');
  } catch (err) {
    toast(err.message);
    return;
  }
  state.admin = me;
  $('#loginScreen').classList.remove('is-active');
  $('#app').classList.add('is-active');
  $('#sbName').textContent = me.nama || 'Panitia';
  $('#sbUser').textContent = me.username;
  $('#sbAvatar').textContent = (me.nama || me.username || 'P').charAt(0).toUpperCase();
  checkApi();
  loadDashboard();
  loadSettings();   // supaya durasi bawaan soal baru sudah benar sebelum form dibuka
}

async function checkApi() {
  const pill = $('#apiPill');
  const txt = $('#apiText');
  try {
    await fetch(API + '/api/health');
    pill.classList.add('is-ok'); pill.classList.remove('is-bad');
    txt.textContent = 'API terhubung';
  } catch (_) {
    pill.classList.add('is-bad'); pill.classList.remove('is-ok');
    txt.textContent = 'API terputus';
  }
}

/* ---------------------------------------------------------------- routing */
const VIEW_META = {
  dashboard: ['Dashboard', 'Ringkasan bank pertanyaan SKOMDA Gesture Quiz'],
  questions: ['Bank Pertanyaan', 'Kelola semua soal yang dipakai di panel pengunjung'],
  editor: ['Tambah Pertanyaan', 'Buat atau ubah soal beserta kunci jawabannya'],
  sessions: ['Riwayat Sesi', 'Hasil permainan pengunjung yang tersimpan'],
  galeri: ['Galeri Foto', 'Dokumentasi Photo Moment dari pengunjung'],
  settings: ['Pengaturan', 'Atur jalannya permainan dan keamanan akun panitia'],
};

function goTo(view) {
  state.view = view;
  $$('.view').forEach((v) => v.classList.toggle('is-active', v.id === `view-${view}`));
  $$('.nav-item').forEach((b) => b.classList.toggle('is-active', b.dataset.view === view));
  const [title, sub] = VIEW_META[view] || ['', ''];
  $('#viewTitle').textContent = title;
  $('#viewSub').textContent = sub;
  $('#sidebar').classList.remove('is-open');

  if (view === 'dashboard') loadDashboard();
  if (view === 'questions') loadQuestions();
  if (view === 'sessions') loadSessions();
  if (view === 'galeri') loadGaleri();
  if (view === 'settings') loadSettings();
  if (view === 'editor' && !state.editingId) resetForm();
}

/* -------------------------------------------------------------- dashboard */
async function loadDashboard() {
  try {
    const s = await api('/api/admin/stats');
    $('#stTotal').textContent = s.total_pertanyaan;
    $('#stAktif').textContent = `${s.pertanyaan_aktif} aktif`;
    $('#stKategori').textContent = s.total_kategori;
    $('#stSesi').textContent = s.total_sesi;
    $('#stAkurasi').textContent = `${s.akurasi}%`;
    $('#stJawaban').textContent = `${s.total_jawaban} jawaban`;

    const bars = $('#kategoriBars');
    const max = Math.max(1, ...s.kategori.map((k) => k.jumlah));
    bars.innerHTML = s.kategori.length
      ? s.kategori.map((k) => `
          <div class="bar-row">
            <div class="bar-top"><b>${escapeHtml(k.nama)}</b><span>${k.jumlah} soal</span></div>
            <div class="bar-track"><i style="width:${(k.jumlah / max) * 100}%"></i></div>
          </div>`).join('')
      : '<p class="empty">Belum ada kategori.</p>';

    const act = $('#activityList');
    act.innerHTML = s.terbaru.length
      ? s.terbaru.map((q) => `
          <div class="act-row">
            <span class="act-dot"></span>
            <span class="act-txt">${escapeHtml(q.pertanyaan)}</span>
            <span class="act-tag">${escapeHtml(q.kategori)}</span>
          </div>`).join('')
      : '<p class="empty">Belum ada soal.</p>';
  } catch (err) {
    toast(err.message);
  }
}

/* --------------------------------------------------------------- questions */
async function loadKategori() {
  try {
    state.kategori = await api('/api/admin/kategori');
    const sel = $('#filterKategori');
    sel.innerHTML = '<option value="">Semua kategori</option>' +
      state.kategori.map((k) => `<option value="${escapeHtml(k)}">${escapeHtml(k)}</option>`).join('');
    $('#kategoriList').innerHTML =
      state.kategori.map((k) => `<option value="${escapeHtml(k)}"></option>`).join('');
  } catch (_) { /* non-kritis */ }
}

async function loadQuestions() {
  const params = new URLSearchParams({
    limit: String(state.limit),
    offset: String(state.page * state.limit),
  });
  if (state.filters.q) params.set('q', state.filters.q);
  if (state.filters.kategori) params.set('kategori', state.filters.kategori);
  if (state.filters.aktif !== '') params.set('aktif', state.filters.aktif);

  try {
    const data = await api('/api/admin/pertanyaan?' + params.toString());
    state.total = data.total;
    const tbody = $('#questionRows');

    if (!data.items.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="table-empty">Tidak ada pertanyaan yang cocok.</td></tr>';
    } else {
      tbody.innerHTML = data.items.map((q) => `
        <tr>
          <td class="mono" style="color:var(--slate-400)">${q.id}</td>
          <td class="q-cell">
            <b>${escapeHtml(q.pertanyaan)}</b>
            <span>${escapeHtml(q.pilihan[q.jawaban])}</span>
          </td>
          <td><span class="cat-tag">${escapeHtml(q.kategori)}</span></td>
          <td><span class="key-tag">${q.jawaban}</span></td>
          <td class="mono">${q.durasi}s</td>
          <td><span class="status-tag ${q.aktif ? '' : 'is-off'}">${q.aktif ? 'Aktif' : 'Nonaktif'}</span></td>
          <td>
            <div class="row-actions">
              <button class="mini-btn" data-edit="${q.id}">Edit</button>
              <button class="mini-btn danger" data-del="${q.id}">Hapus</button>
            </div>
          </td>
        </tr>`).join('');
    }

    const from = state.total ? state.page * state.limit + 1 : 0;
    const to = Math.min(state.total, (state.page + 1) * state.limit);
    $('#tableCount').textContent = `${from}–${to} dari ${state.total} pertanyaan`;
    const pages = Math.max(1, Math.ceil(state.total / state.limit));
    $('#pageLabel').textContent = `${state.page + 1} / ${pages}`;
    $('#prevPage').disabled = state.page === 0;
    $('#nextPage').disabled = state.page + 1 >= pages;
  } catch (err) {
    toast(err.message);
  }
}

/* ------------------------------------------------------------------ editor */
function resetForm() {
  state.editingId = null;
  $('#questionForm').reset();
  $('#fKategori').value = 'Umum';
  // Durasi bawaan mengikuti pengaturan panitia (bukan angka keras 30).
  $('#fDurasi').value = settingsDefaults ? settingsDefaults.durasi_default : 30;
  $('#fAktif').checked = true;
  $('#switchAktif').setAttribute('aria-checked', 'true');
  $('#switchLabel').textContent = 'Aktif';
  $$('input[name="jawaban"]').forEach((r) => { r.checked = r.value === 'A'; });
  $('#editorTitle').textContent = 'Tambah Pertanyaan';
  $('#editorBadge').textContent = 'BARU';
  $('#btnSave').querySelector('span').textContent = 'Simpan Pertanyaan';
  updatePreview();
}

async function editQuestion(id) {
  try {
    const q = await api(`/api/admin/pertanyaan/${id}`);
    state.editingId = id;
    $('#fPertanyaan').value = q.pertanyaan;
    $('#fA').value = q.pilihan.A;
    $('#fB').value = q.pilihan.B;
    $('#fC').value = q.pilihan.C;
    $('#fD').value = q.pilihan.D;
    $('#fKategori').value = q.kategori;
    $('#fDurasi').value = q.durasi;
    $('#fAktif').checked = q.aktif;
    $('#switchAktif').setAttribute('aria-checked', String(q.aktif));
    $('#switchLabel').textContent = q.aktif ? 'Aktif' : 'Nonaktif';
    $$('input[name="jawaban"]').forEach((r) => { r.checked = r.value === q.jawaban; });
    $('#editorTitle').textContent = `Edit Pertanyaan #${q.id}`;
    $('#editorBadge').textContent = 'EDIT';
    $('#btnSave').querySelector('span').textContent = 'Simpan Perubahan';
    updatePreview();
    goTo('editor');
    $('#fPertanyaan').focus();
  } catch (err) {
    toast(err.message);
  }
}

function formPayload() {
  const jawaban = ($$('input[name="jawaban"]').find((r) => r.checked) || {}).value || 'A';
  return {
    pertanyaan: $('#fPertanyaan').value.trim(),
    pilihan_a: $('#fA').value.trim(),
    pilihan_b: $('#fB').value.trim(),
    pilihan_c: $('#fC').value.trim(),
    pilihan_d: $('#fD').value.trim(),
    jawaban,
    kategori: $('#fKategori').value.trim() || 'Umum',
    durasi: parseInt($('#fDurasi').value, 10) || 30,
    aktif: $('#fAktif').checked,
  };
}

async function saveQuestion(e) {
  e.preventDefault();
  const payload = formPayload();

  // Validasi klien ringan (backend tetap validasi ulang).
  const missing = ['pertanyaan', 'pilihan_a', 'pilihan_b', 'pilihan_c', 'pilihan_d']
    .filter((k) => !payload[k] || payload[k].length < (k === 'pertanyaan' ? 5 : 1));
  if (missing.length) {
    toast('Lengkapi: ' + missing.join(', '));
    return;
  }
  if (payload.pertanyaan.length < 5) {
    toast('Pertanyaan minimal 5 karakter.');
    return;
  }

  const btn = $('#btnSave');
  btn.disabled = true;
  try {
    if (state.editingId) {
      await api(`/api/admin/pertanyaan/${state.editingId}`, {
        method: 'PUT', body: JSON.stringify(payload),
      });
      toast('Perubahan tersimpan permanen.', false);
    } else {
      await api('/api/admin/pertanyaan', {
        method: 'POST', body: JSON.stringify(payload),
      });
      toast('Pertanyaan baru ditambahkan.', false);
    }
    await loadKategori();
    resetForm();
    goTo('questions');
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false;
  }
}

/* ----------------------------------------------------------------- preview */
function updatePreview() {
  const p = formPayload();
  $('#pvKategori').textContent = p.kategori || 'UMUM';
  $('#pvDurasi').textContent = `${p.durasi || 30}s`;
  $('#pvPertanyaan').textContent = p.pertanyaan || 'Pertanyaan akan tampil di sini…';
  const map = { A: p.pilihan_a, B: p.pilihan_b, C: p.pilihan_c, D: p.pilihan_d };
  $$('.pv-opt').forEach((el) => {
    const key = el.querySelector('.l').textContent;
    el.querySelector('.t').textContent = map[key] || `Pilihan ${key}`;
    el.classList.toggle('is-key', key === p.jawaban);
  });
  $('#pvKunci').textContent = p.jawaban || 'A';
  $('#countPertanyaan').textContent = (p.pertanyaan || '').length;
}

/* ------------------------------------------------------------------ delete */
function askDelete(id) {
  const row = document.querySelector(`[data-del="${id}"]`)?.closest('tr');
  const text = row?.querySelector('.q-cell b')?.textContent || '';
  state.pendingDelete = id;
  $('#modalBody').innerHTML =
    `Hapus pertanyaan <b>#${id}</b>?<br><span style="font-size:12px">“${escapeHtml(text)}”</span>
     <br><br>Tindakan ini permanen dan soal tidak akan muncul lagi di kuis.`;
  $('#modal').classList.add('is-show');
}

async function confirmDelete() {
  const id = state.pendingDelete;
  $('#modal').classList.remove('is-show');
  if (!id) return;
  try {
    await api(`/api/admin/pertanyaan/${id}`, { method: 'DELETE' });
    toast('Pertanyaan dihapus.', false);
    if (state.editingId === id) resetForm();
    loadQuestions();
    loadDashboard();
  } catch (err) {
    toast(err.message);
  } finally {
    state.pendingDelete = null;
  }
}

/* --------------------------------------------------------------- settings */
let settingsDefaults = null;

async function loadSettings() {
  try {
    const d = await api('/api/admin/pengaturan');
    settingsDefaults = d.default;
    const v = d.nilai;
    $('#setJumlah').value = v.jumlah_soal;
    $('#setDurasi').value = v.durasi_default;
    $('#setHold').value = v.hold_detik;
    $('#setCooldown').value = v.cooldown_detik;
    // Batas dari backend dipasang ke input supaya form tidak bisa diisi
    // nilai yang pasti ditolak server.
    Object.entries(d.batas).forEach(([kunci, b]) => {
      const map = { jumlah_soal: '#setJumlah', durasi_default: '#setDurasi',
                    hold_detik: '#setHold', cooldown_detik: '#setCooldown' };
      const el = $(map[kunci]);
      if (el) { el.min = b.min; el.max = b.max; }
    });
    setSettingsBadge('TERSIMPAN');
    loadSystemInfo();
  } catch (err) {
    toast(err.message);
  }
}

function setSettingsBadge(text) {
  const el = $('#settingsBadge');
  if (!el) return;
  el.textContent = text;
  el.style.background = text === 'TERSIMPAN' ? 'var(--ok-tint)' : 'var(--red-tint)';
  el.style.color = text === 'TERSIMPAN' ? 'var(--ok)' : 'var(--red)';
}

async function saveSettings(e) {
  e.preventDefault();
  const payload = {
    jumlah_soal: parseInt($('#setJumlah').value, 10),
    durasi_default: parseInt($('#setDurasi').value, 10),
    hold_detik: parseFloat($('#setHold').value),
    cooldown_detik: parseFloat($('#setCooldown').value),
  };
  const btn = $('#btnSaveSettings');
  btn.disabled = true;
  try {
    const res = await api('/api/admin/pengaturan', {
      method: 'PUT', body: JSON.stringify(payload),
    });
    const v = res.nilai;
    $('#setJumlah').value = v.jumlah_soal;
    $('#setDurasi').value = v.durasi_default;
    $('#setHold').value = v.hold_detik;
    $('#setCooldown').value = v.cooldown_detik;
    setSettingsBadge('TERSIMPAN');
    toast('Pengaturan tersimpan permanen.', false);
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false;
  }
}

function resetSettings() {
  if (!settingsDefaults) return;
  $('#setJumlah').value = settingsDefaults.jumlah_soal;
  $('#setDurasi').value = settingsDefaults.durasi_default;
  $('#setHold').value = settingsDefaults.hold_detik;
  $('#setCooldown').value = settingsDefaults.cooldown_detik;
  setSettingsBadge('BELUM DISIMPAN');
  toast('Nilai awal dimuat. Tekan Simpan untuk menerapkan.', false);
}

async function loadSystemInfo() {
  $('#infoApi').textContent = API.replace(/^https?:\/\//, '');
  try {
    const h = await fetchHealth();
    $('#infoDb').textContent = h.database || '—';
    $('#infoCam').textContent = h.kamera ? 'Aktif' : 'Standby';
    $('#infoVer').textContent = h.versi || '—';
  } catch (_) {
    $('#infoDb').textContent = '—';
    $('#infoCam').textContent = 'Tidak terhubung';
  }
}

async function fetchHealth() {
  const res = await fetch(API + '/api/health');
  if (!res.ok) throw new Error('health gagal');
  return res.json();
}

async function savePassword(e) {
  e.preventDefault();
  const lama = $('#pwLama').value;
  const baru = $('#pwBaru').value;
  const ulang = $('#pwUlang').value;

  if (baru !== ulang) {
    toast('Konfirmasi password baru tidak sama.');
    return;
  }
  if (!/[A-Za-z]/.test(baru) || !/\d/.test(baru)) {
    toast('Password baru harus mengandung huruf dan angka.');
    return;
  }

  const btn = $('#btnSavePassword');
  btn.disabled = true;
  try {
    await api('/api/admin/password', {
      method: 'POST',
      body: JSON.stringify({ password_lama: lama, password_baru: baru }),
    });
    $('#passwordForm').reset();
    toast('Password berhasil diperbarui.', false);
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false;
  }
}

/* ---------------------------------------------------------------- sessions */
/** Ringkas satu baris sesi: mode single/battle + skor per pemain. */
function ringkasSesi(s) {
  const mode = (s.mode || 'single').toLowerCase();
  if (mode === 'battle') {
    const p1 = { nama: s.pemain_1 || 'Player 1', skor: s.skor_1 ?? 0 };
    const p2 = { nama: s.pemain_2 || 'Player 2', skor: s.skor_2 ?? 0 };
    const label = p1.skor === p2.skor
      ? 'SERI'
      : (p1.skor > p2.skor ? p1.nama : p2.nama) + ' menang';
    return `
      <div style="font-size:11px;line-height:1.5">
        <div>${escapeHtml(p1.nama)}: <b>${p1.skor}</b></div>
        <div>${escapeHtml(p2.nama)}: <b>${p2.skor}</b></div>
        <div style="color:var(--slate);font-size:10px">${escapeHtml(label)}</div>
      </div>`;
  }
  return `<b class="mono">${s.skor ?? 0}</b>
    <div style="font-size:10px;color:var(--slate)">${s.benar ?? 0} benar</div>`;
}

async function loadSessions() {
  try {
    const rows = await api('/api/admin/sesi?limit=20');
    const tbody = $('#sessionRows');
    tbody.innerHTML = rows.length
      ? rows.map((s) => {
        const mode = (s.mode || 'single').toLowerCase();
        return `
        <tr>
          <td class="mono" style="font-size:11px">${escapeHtml(s.id)}</td>
          <td><span class="status-tag ${mode === 'battle' ? '' : 'is-off'}"
                    style="${mode === 'battle' ? 'background:var(--red-tint);color:var(--red)' : ''}">
            ${mode === 'battle' ? '2P' : '1P'}</span></td>
          <td class="mono">${s.total_soal}</td>
          <td>${ringkasSesi(s)}</td>
          <td><span class="status-tag ${s.status === 'selesai' ? '' : 'is-off'}">${escapeHtml(s.status)}</span></td>
          <td style="font-size:11px;color:var(--slate)">${escapeHtml(s.started_at || '—')}</td>
          <td style="font-size:11px;color:var(--slate)">${escapeHtml(s.finished_at || '—')}</td>
        </tr>`;
      }).join('')
      : '<tr><td colspan="7" class="table-empty">Belum ada sesi permainan.</td></tr>';
  } catch (err) {
    toast(err.message);
  }
}

/* -------------------------------------------------------------- galeri foto */
const galeriState = { items: [], total: 0, mode: '', limit: 60 };

function ukuranTeks(bytes) {
  if (!bytes) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function tanggalTeks(iso) {
  if (!iso) return '—';
  // "2026-11-19 08:15:00" -> "19 Nov 2026 · 08.15"
  const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!m) return iso;
  const bulan = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun',
                 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];
  return `${Number(m[3])} ${bulan[Number(m[2]) - 1]} ${m[1]} · ${m[4]}.${m[5]}`;
}

/** URL berkas foto — token dikirim sebagai query agar bisa dipakai di <img>. */
function fotoUrl(nama, thumb = false) {
  const q = `token=${encodeURIComponent(state.token)}` + (thumb ? '&thumb=1' : '');
  return `${API}/api/admin/galeri/${encodeURIComponent(nama)}?${q}`;
}

function kartuFoto(f) {
  const isBattle = f.mode === 'battle';
  let judul;
  let sub;
  if (isBattle) {
    judul = `${escapeHtml(f.pemain_1 || 'Player 1')} vs ${escapeHtml(f.pemain_2 || 'Player 2')}`;
    sub = `<b>${f.skor_1 ?? 0}</b> – <b>${f.skor_2 ?? 0}</b> · ${
      f.pemenang === 'SERI' ? 'SERI' : `menang: ${escapeHtml(f.pemenang || '—')}`}`;
  } else {
    judul = escapeHtml(f.pemain_1 || 'Single Player');
    sub = `Skor <b>${f.skor_1 ?? 0}</b> · ${escapeHtml(f.pemenang || 'SELESAI')}`;
  }
  const tagClass = isBattle
    ? (f.pemenang === 'SERI' ? 'hasil-tag is-seri' : 'hasil-tag is-battle')
    : 'hasil-tag';

  return `
    <article class="foto-card" data-id="${f.id}" data-nama="${escapeHtml(f.nama_file)}">
      <button class="foto-thumb" data-zoom="${escapeHtml(f.nama_file)}" type="button"
              aria-label="Perbesar foto ${escapeHtml(f.nama_file)}">
        <span class="foto-badge ${isBattle ? 'is-battle' : ''}">${isBattle ? '2P' : '1P'}</span>
        ${f.publik ? '<span class="foto-badge is-publik" title="Tampil di carousel publik">PUBLIK</span>' : ''}
        <img src="${fotoUrl(f.nama_file, true)}" alt="Foto dokumentasi ${escapeHtml(f.nama_file)}"
             loading="eager" decoding="async" />
        <span class="zoom-hint">KLIK UNTUK PERBESAR</span>
      </button>
      <div class="foto-body">
        <span class="${tagClass}">${isBattle ? '2 PLAYER BATTLE' : 'SINGLE PLAYER'}</span>
        <span class="foto-title">${judul}</span>
        <span class="foto-sub">${sub}</span>
        <span class="foto-meta">${tanggalTeks(f.created_at)} · ${ukuranTeks(f.ukuran)}</span>
        <div class="foto-actions">
          <button class="btn btn-ghost" data-publik="${f.id}" data-nilai="${f.publik ? '0' : '1'}">
            ${f.publik ? 'Sembunyikan dari hero' : 'Tampilkan di hero'}
          </button>
          <a class="btn btn-ghost" href="${fotoUrl(f.nama_file)}"
             download="${escapeHtml(f.nama_file)}">Unduh</a>
          <button class="btn btn-ghost" data-hapus="${f.id}">Hapus</button>
        </div>
      </div>
    </article>`;
}

async function loadGaleri() {
  const grid = $('#galeriGrid');
  if (!grid) return;
  galeriState.mode = $('#galeriMode') ? $('#galeriMode').value : '';
  grid.innerHTML = '<p class="empty">Memuat foto…</p>';
  try {
    const qs = new URLSearchParams({ limit: String(galeriState.limit) });
    if (galeriState.mode) qs.set('mode', galeriState.mode);
    const d = await api('/api/admin/galeri?' + qs.toString());
    galeriState.items = d.items || [];
    galeriState.total = d.total || 0;

    grid.innerHTML = galeriState.items.length
      ? galeriState.items.map(kartuFoto).join('')
      : `<p class="empty">Belum ada foto. Foto masuk setelah pengunjung menekan
           <b>KIRIM KE GALERI PANITIA</b> pada sesi Photo Moment.</p>`;

    const info = $('#galeriInfo');
    if (info) {
      info.textContent = galeriState.items.length
        ? `Menampilkan ${galeriState.items.length} dari ${galeriState.total} foto`
        : `0 foto`;
    }

    // Tandai thumbnail yang gagal dimuat agar tidak tampak kotak kosong.
    grid.querySelectorAll('.foto-thumb img').forEach((img) => {
      img.addEventListener('error', () => {
        const thumb = img.closest('.foto-thumb');
        if (!thumb || thumb.classList.contains('is-broken')) return;
        thumb.classList.add('is-broken');
        img.remove();
        thumb.insertAdjacentHTML('beforeend', '<span>Berkas tidak ditemukan</span>');
      });
    });
  } catch (err) {
    grid.innerHTML = `<p class="empty">${escapeHtml(err.message)}</p>`;
    toast(err.message);
  }
}

function bukaLightbox(nama) {
  const item = galeriState.items.find((f) => f.nama_file === nama);
  const box = $('#lightbox');
  const img = $('#lightboxImg');
  if (!box || !img) return;
  img.src = fotoUrl(nama);
  $('#lightboxInfo').textContent = item
    ? `${item.mode === 'battle'
        ? `${item.pemain_1 || 'P1'} ${item.skor_1 ?? 0} – ${item.skor_2 ?? 0} ${item.pemain_2 || 'P2'}`
        : `Single Player · ${item.skor_1 ?? 0} poin`} · ${tanggalTeks(item.created_at)}`
    : nama;
  const dl = $('#lightboxDownload');
  if (dl) { dl.href = fotoUrl(nama); dl.download = nama; }
  box.classList.add('is-show');
}

function tutupLightbox() {
  const box = $('#lightbox');
  if (box) box.classList.remove('is-show');
}

async function setPublikFoto(id, nilai) {
  try {
    const res = await api(`/api/admin/galeri/${id}/publik`, {
      method: 'PUT',
      body: JSON.stringify({ publik: nilai === '1' }),
    });
    toast(res.publik
      ? 'Foto ditampilkan di carousel hero pengunjung.'
      : 'Foto disembunyikan dari carousel hero.', false);
    loadGaleri();
  } catch (err) {
    toast(err.message);
  }
}

async function hapusFoto(id, nama) {
  if (!confirm(`Hapus foto ${nama}?\n\nBerkas akan dihapus permanen dari komputer ini.`)) return;
  try {
    await api(`/api/admin/galeri/${id}`, { method: 'DELETE' });
    toast('Foto dihapus.', false);
    loadGaleri();
  } catch (err) {
    toast(err.message);
  }
}

/** Unduh daftar foto sebagai CSV — untuk laporan dokumentasi pameran. */
async function unduhCsvGaleri() {
  let items = galeriState.items;
  if (!items.length) {
    toast('Belum ada foto untuk diekspor.');
    return;
  }
  // Ambil sampai 200 baris agar ekspor tidak terpotong batas tampilan.
  try {
    const qs = new URLSearchParams({ limit: '200' });
    if (galeriState.mode) qs.set('mode', galeriState.mode);
    const d = await api('/api/admin/galeri?' + qs.toString());
    if (d.items && d.items.length) items = d.items;
  } catch (_) { /* pakai data yang sudah tampil */ }
  const header = ['id', 'nama_file', 'mode', 'pemain_1', 'pemain_2',
                  'skor_1', 'skor_2', 'pemenang', 'ukuran_byte', 'waktu', 'sesi_id'];
  const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const lines = [header.join(',')].concat(items.map((f) => [
    f.id, f.nama_file, f.mode, f.pemain_1, f.pemain_2, f.skor_1, f.skor_2,
    f.pemenang, f.ukuran, f.created_at, f.sesi_id,
  ].map(esc).join(',')));

  const ts = new Date();
  const pad = (v) => String(v).padStart(2, '0');
  const stamp = `${ts.getFullYear()}${pad(ts.getMonth() + 1)}${pad(ts.getDate())}`
    + `-${pad(ts.getHours())}${pad(ts.getMinutes())}`;
  const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `skomda-galeri-${stamp}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  toast('Daftar foto diekspor sebagai CSV.', false);
}

/* -------------------------------------------------------------- listeners */
function bind() {
  $('#loginForm').addEventListener('submit', doLogin);
  $('#btnLogout').addEventListener('click', () => logout());
  $('#pwToggle').addEventListener('click', () => {
    const inp = $('#loginPass');
    const show = inp.type === 'password';
    inp.type = show ? 'text' : 'password';
    $('#pwToggle').textContent = show ? 'Sembunyi' : 'Lihat';
  });

  $$('.nav-item').forEach((b) => b.addEventListener('click', () => goTo(b.dataset.view)));
  $$('[data-goto]').forEach((b) => b.addEventListener('click', () => goTo(b.dataset.goto)));
  $('#burger').addEventListener('click', () => $('#sidebar').classList.toggle('is-open'));

  // questions table (delegasi)
  $('#questionRows').addEventListener('click', (e) => {
    const ed = e.target.closest('[data-edit]');
    const dl = e.target.closest('[data-del]');
    if (ed) editQuestion(Number(ed.dataset.edit));
    if (dl) askDelete(Number(dl.dataset.del));
  });

  // filter + search
  let searchTimer = null;
  $('#searchInput').addEventListener('input', (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.filters.q = e.target.value.trim();
      state.page = 0;
      loadQuestions();
    }, 280);
  });
  $('#filterKategori').addEventListener('change', (e) => {
    state.filters.kategori = e.target.value;
    state.page = 0;
    loadQuestions();
  });
  $('#filterAktif').addEventListener('change', (e) => {
    state.filters.aktif = e.target.value;
    state.page = 0;
    loadQuestions();
  });
  $('#prevPage').addEventListener('click', () => {
    if (state.page > 0) { state.page -= 1; loadQuestions(); }
  });
  $('#nextPage').addEventListener('click', () => {
    if ((state.page + 1) * state.limit < state.total) { state.page += 1; loadQuestions(); }
  });

  // editor
  $('#questionForm').addEventListener('submit', saveQuestion);
  $('#settingsForm').addEventListener('submit', saveSettings);
  $('#btnResetSettings').addEventListener('click', resetSettings);
  $('#passwordForm').addEventListener('submit', savePassword);
  ['setJumlah', 'setDurasi', 'setHold', 'setCooldown'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('input', () => setSettingsBadge('BELUM DISIMPAN'));
  });
  $('#btnCancel').addEventListener('click', () => { resetForm(); goTo('questions'); });
  $('#btnResetForm').addEventListener('click', resetForm);
  $('#switchAktif').addEventListener('click', () => {
    const on = $('#switchAktif').getAttribute('aria-checked') !== 'true';
    $('#switchAktif').setAttribute('aria-checked', String(on));
    $('#switchLabel').textContent = on ? 'Aktif' : 'Nonaktif';
    $('#fAktif').checked = on;
  });
  ['fPertanyaan', 'fA', 'fB', 'fC', 'fD', 'fKategori', 'fDurasi'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('input', updatePreview);
  });
  $$('input[name="jawaban"]').forEach((r) => r.addEventListener('change', updatePreview));

  // modal
  $('#modalClose').addEventListener('click', () => $('#modal').classList.remove('is-show'));
  $('#modalCancel').addEventListener('click', () => $('#modal').classList.remove('is-show'));
  $('#modalConfirm').addEventListener('click', confirmDelete);
  $('#modal').addEventListener('click', (e) => {
    if (e.target.id === 'modal') $('#modal').classList.remove('is-show');
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') $('#modal').classList.remove('is-show');
  });

  $('#btnRefreshSesi').addEventListener('click', loadSessions);

  // galeri foto
  const refreshGaleri = $('#btnRefreshGaleri');
  if (refreshGaleri) refreshGaleri.addEventListener('click', loadGaleri);
  const galeriMode = $('#galeriMode');
  if (galeriMode) galeriMode.addEventListener('change', loadGaleri);
  const csvBtn = $('#btnUnduhSemua');
  if (csvBtn) csvBtn.addEventListener('click', unduhCsvGaleri);

  const grid = $('#galeriGrid');
  if (grid) {
    grid.addEventListener('click', (e) => {
      const zoom = e.target.closest('[data-zoom]');
      const del = e.target.closest('[data-hapus]');
      const pub = e.target.closest('[data-publik]');
      if (zoom) bukaLightbox(zoom.dataset.zoom);
      if (pub) setPublikFoto(Number(pub.dataset.publik), pub.dataset.nilai);
      if (del) {
        const card = del.closest('.foto-card');
        hapusFoto(Number(del.dataset.hapus), card ? card.dataset.nama : '');
      }
    });
  }

  const lbClose = $('#lightboxClose');
  if (lbClose) lbClose.addEventListener('click', tutupLightbox);
  const lightbox = $('#lightbox');
  if (lightbox) {
    lightbox.addEventListener('click', (e) => {
      if (e.target.id === 'lightbox') tutupLightbox();
    });
  }
}

/* ------------------------------------------------------------------- init */
document.addEventListener('DOMContentLoaded', async () => {
  bind();
  updatePreview();
  loadKategori();

  const fy = document.getElementById('adminFooterYear');
  if (fy) fy.textContent = `© ${new Date().getFullYear()} SMK Telkom Sidoarjo`;

  if (state.token) {
    await enterApp();
  }
});
