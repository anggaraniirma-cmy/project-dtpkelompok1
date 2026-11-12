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
  $('#fDurasi').value = 30;
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

/* ---------------------------------------------------------------- sessions */
async function loadSessions() {
  try {
    const rows = await api('/api/admin/sesi?limit=20');
    const tbody = $('#sessionRows');
    tbody.innerHTML = rows.length
      ? rows.map((s) => `
        <tr>
          <td class="mono" style="font-size:11px">${escapeHtml(s.id)}</td>
          <td class="mono">${s.total_soal}</td>
          <td class="mono">${s.benar}</td>
          <td class="mono"><b>${s.skor}</b></td>
          <td><span class="status-tag ${s.status === 'selesai' ? '' : 'is-off'}">${escapeHtml(s.status)}</span></td>
          <td style="font-size:11px;color:var(--slate)">${escapeHtml(s.started_at || '—')}</td>
          <td style="font-size:11px;color:var(--slate)">${escapeHtml(s.finished_at || '—')}</td>
        </tr>`).join('')
      : '<tr><td colspan="7" class="table-empty">Belum ada sesi permainan.</td></tr>';
  } catch (err) {
    toast(err.message);
  }
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
}

/* ------------------------------------------------------------------- init */
document.addEventListener('DOMContentLoaded', async () => {
  bind();
  updatePreview();
  loadKategori();

  if (state.token) {
    await enterApp();
  }
});
