/* =========================================================================
   SKOMDA Gesture Quiz — pemilih jumlah soal (5 / 7 / 10)
   -------------------------------------------------------------------------
   Satu modul untuk kedua kartu mode (Single Player & Battle).

   Prinsip:
   1. Daftar pilihan & nilai default TIDAK di-hardcode di sini: diambil dari
      backend (GET /api/info/jumlah-soal). Tombol di HTML hanya placeholder
      yang disesuaikan saat data tiba.
   2. Pilihan disimpan per mode dan diingat di localStorage, supaya panitia
      tidak perlu memilih ulang setiap pengunjung.
   3. Bila bank soal lebih sedikit dari pilihan (mis. pilih 10, soal aktif 9),
      tombol tetap bisa dipilih tetapi diberi keterangan jujur — permainan
      berjalan dengan soal yang tersedia, bukan error.
   4. Kalau backend tidak bisa dihubungi, nilai default 5 dipakai dan
      permainan tetap bisa dimulai.
   ========================================================================= */
(function () {
  'use strict';

  const API = window.SKOMDA_API || 'http://localhost:8000';
  const FALLBACK = { pilihan: [5, 7, 10], default: 5, tersedia: null };
  const SIMPAN_KEY = 'skomda_jumlah_soal';

  const Q = {
    info: { ...FALLBACK },
    // nilai terpilih per mode
    nilai: { single: 5, battle: 5 },
    siap: false,
  };

  const $ = (s) => document.querySelector(s);

  /* ------------------------------------------------------------ penyimpanan */
  function bacaSimpanan() {
    try {
      const raw = localStorage.getItem(SIMPAN_KEY);
      if (!raw) return;
      const d = JSON.parse(raw);
      if (d && typeof d === 'object') {
        ['single', 'battle'].forEach((m) => {
          const n = Number(d[m]);
          if (Number.isFinite(n) && n > 0) Q.nilai[m] = n;
        });
      }
    } catch (_) { /* localStorage bisa diblokir di kios mode */ }
  }

  function simpan() {
    try {
      localStorage.setItem(SIMPAN_KEY, JSON.stringify(Q.nilai));
    } catch (_) { /* abaikan */ }
  }

  /* ------------------------------------------------------------------ render */
  function kotak(mode) {
    const sel = mode === 'battle' ? '#qtyBattle' : '#qtySingle';
    const wadah = document.querySelector(sel);
    if (!wadah) return null;
    return { wadah, catatan: document.querySelector(
      mode === 'battle' ? '#qtyNoteBattle' : '#qtyNoteSingle') };
  }

  function bangunTombol(mode) {
    const k = kotak(mode);
    if (!k) return;
    const pilihan = Q.info.pilihan.length ? Q.info.pilihan : FALLBACK.pilihan;

    k.wadah.innerHTML = '';
    pilihan.forEach((n) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'qty-opt';
      b.dataset.qty = String(n);
      b.textContent = String(n);
      b.addEventListener('click', () => setNilai(mode, n));
      k.wadah.appendChild(b);
    });

    // Pilihan tersimpan mungkin tidak ada lagi di daftar server.
    if (!pilihan.includes(Q.nilai[mode])) Q.nilai[mode] = Q.info.default;
    tandai(mode);
  }

  function tandai(mode) {
    const k = kotak(mode);
    if (!k) return;
    const aktif = Q.nilai[mode];
    Array.from(k.wadah.querySelectorAll('.qty-opt')).forEach((b) => {
      const on = Number(b.dataset.qty) === aktif;
      b.classList.toggle('is-active', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });

    // Keterangan bila bank soal belum cukup.
    if (k.catatan) {
      const tersedia = Q.info.tersedia;
      if (typeof tersedia === 'number' && tersedia > 0 && aktif > tersedia) {
        k.catatan.textContent =
          `Bank soal baru ${tersedia} soal aktif — permainan memakai ${tersedia} soal.`;
        k.catatan.classList.add('is-warn');
      } else if (typeof tersedia === 'number' && tersedia === 0) {
        k.catatan.textContent = 'Belum ada soal aktif. Tambahkan di panel admin.';
        k.catatan.classList.add('is-warn');
      } else {
        k.catatan.textContent = '';
        k.catatan.classList.remove('is-warn');
      }
    }
  }

  function setNilai(mode, n) {
    const angka = Number(n);
    if (!Number.isFinite(angka)) return;
    Q.nilai[mode] = angka;
    simpan();
    tandai(mode);
  }

  /* -------------------------------------------------------------------- muat */
  async function muat() {
    try {
      const res = await fetch(`${API}/api/info/jumlah-soal`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const d = await res.json();
      const pilihan = Array.isArray(d.pilihan) && d.pilihan.length
        ? d.pilihan.map(Number).filter((n) => n > 0)
        : FALLBACK.pilihan;
      Q.info = {
        pilihan,
        default: Number(d.default) || FALLBACK.default,
        tersedia: typeof d.tersedia === 'number' ? d.tersedia : null,
      };
    } catch (_) {
      // Backend mati: pakai daftar bawaan, permainan tetap bisa dimulai.
      Q.info = { ...FALLBACK };
    }
    // Nilai default mengikuti pengaturan panitia bila belum ada simpanan.
    ['single', 'battle'].forEach((m) => {
      if (!Q.info.pilihan.includes(Q.nilai[m])) Q.nilai[m] = Q.info.default;
      bangunTombol(m);
    });
    Q.siap = true;
  }

  /* -------------------------------------------------------------------- API */
  function jumlah(mode) {
    return Q.nilai[mode === 'battle' ? 'battle' : 'single'] || Q.info.default || 5;
  }

  bacaSimpanan();
  ['single', 'battle'].forEach((m) => {
    if (!Q.info.pilihan.includes(Q.nilai[m])) Q.nilai[m] = FALLBACK.default;
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', muat);
  } else {
    muat();
  }

  window.skomdaJumlahSoal = {
    jumlah,
    set: setNilai,
    info: () => ({ ...Q.info, nilai: { ...Q.nilai } }),
    muat,
    siap: () => Q.siap,
  };
})();
