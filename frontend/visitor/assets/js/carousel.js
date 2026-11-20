/* =========================================================================
   SKOMDA Gesture Quiz — Carousel dokumentasi peserta (hero landing)
   -------------------------------------------------------------------------
   Sumber data: GET /api/galeri/publik (tanpa token admin).
   Backend hanya mengembalikan foto berstatus `publik = 1` — yaitu foto yang
   SUDAH disetujui panitia di panel admin — maksimal 5, terbaru lebih dulu.
   Daftar TIDAK di-hardcode di sini.

   Prinsip implementasi:
   1. Transisi memakai opacity + transform (compositor), bukan animasi layout,
      supaya tidak memicu reflow dan tidak mengganggu FPS kamera.
   2. Autoplay 4,5 detik, berhenti saat kursor/fokus masuk, saat tab
      tersembunyi (document.hidden), dan saat prefers-reduced-motion.
   3. Gambar yang gagal dimuat dibuang dari daftar — carousel tidak pernah
      menampilkan kotak rusak. Bila semua gagal, fallback statis dipakai.
   4. Tidak ada token admin, tidak ada request ke endpoint admin.
   ========================================================================= */
(function () {
  'use strict';

  const API = window.SKOMDA_API || 'http://localhost:8000';
  const INTERVAL_MS = 4500;       // 4–5 detik sesuai spesifikasi
  const MAKS = 5;

  const $ = (s) => document.querySelector(s);

  const C = {
    items: [],          // hanya foto yang berhasil dimuat
    index: 0,
    timer: null,
    paused: false,
    siap: false,
    slides: [],
    gagal: new Set(),
    sidik: '',          // sidik daftar foto, untuk mendeteksi perubahan
  };

  const kurangiGerak = () =>
    window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* --------------------------------------------------------------- render */
  function buatSlide(item, i) {
    const slide = document.createElement('div');
    slide.className = 'carousel-slide' + (i === 0 ? ' is-active' : '');
    slide.setAttribute('role', 'group');
    slide.setAttribute('aria-roledescription', 'slide');
    slide.setAttribute('aria-label', `Foto ${i + 1} dari ${C.items.length}`);

    const img = document.createElement('img');
    img.src = `${API}${item.url}`;
    img.alt = item.mode === 'battle'
      ? 'Dokumentasi peserta mode 2 Player Battle di booth SKOMDA Gesture Quiz'
      : 'Dokumentasi peserta mode Single Player di booth SKOMDA Gesture Quiz';
    img.decoding = 'async';
    img.loading = i === 0 ? 'eager' : 'lazy';
    img.width = 1200;
    img.height = 900;
    // Berkas yang tidak bisa diakses: buang slide-nya, jangan tampilkan rusak.
    img.addEventListener('error', () => hapusSlide(item.nama_file, i));

    slide.appendChild(img);
    return slide;
  }

  function hapusSlide(nama, i) {
    if (C.gagal.has(nama)) return;
    C.gagal.add(nama);
    const sisa = C.items.filter((it) => it.nama_file !== nama);
    if (!sisa.length) {
      tampilkanFallback('Semua foto gagal dimuat.');
      return;
    }
    C.items = sisa;
    renderUlang(Math.min(i, sisa.length - 1));
  }

  function renderUlang(keepIndex) {
    const track = $('#carouselTrack');
    const dots = $('#carouselDots');
    if (!track) return;

    track.innerHTML = '';
    C.slides = C.items.map((item, i) => {
      const s = buatSlide(item, i);
      track.appendChild(s);
      return s;
    });

    if (dots) {
      dots.innerHTML = '';
      C.items.forEach((item, i) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'carousel-dot' + (i === keepIndex ? ' is-active' : '');
        b.setAttribute('role', 'tab');
        b.setAttribute('aria-label', `Tampilkan foto ${i + 1}`);
        b.setAttribute('aria-selected', i === keepIndex ? 'true' : 'false');
        b.addEventListener('click', () => {
          tampil(i, true);
        });
        dots.appendChild(b);
      });
      dots.hidden = C.items.length < 2;
    }

    const prev = $('#carouselPrev');
    const next = $('#carouselNext');
    if (prev) prev.hidden = C.items.length < 2;
    if (next) next.hidden = C.items.length < 2;

    tampil(keepIndex, false);
  }

  function tampil(i, manual) {
    if (!C.slides.length) return;
    const n = C.slides.length;
    C.index = ((i % n) + n) % n;

    C.slides.forEach((s, k) => s.classList.toggle('is-active', k === C.index));

    const dots = $('#carouselDots');
    if (dots) {
      Array.from(dots.children).forEach((d, k) => {
        d.classList.toggle('is-active', k === C.index);
        d.setAttribute('aria-selected', k === C.index ? 'true' : 'false');
      });
    }

    const cap = $('#carouselCaptionText');
    if (cap && C.items[C.index]) {
      const it = C.items[C.index];
      cap.textContent = `${C.index + 1}/${n} · Dokumentasi peserta ${
        it.mode === 'battle' ? 'mode 2 Player Battle' : 'mode Single Player'}.`;
    }

    if (manual) {
      // Navigasi manual mengulang hitungan mundur agar foto tidak langsung
      // berganti tepat setelah pengunjung memilihnya.
      jadwalkan();
    }
  }

  /* ------------------------------------------------------------- autoplay */
  function hentikan() {
    clearInterval(C.timer);
    C.timer = null;
  }

  function mulai() {
    hentikan();
    if (C.paused || kurangiGerak() || document.hidden) return;
    if (C.items.length < 2) return;
    C.timer = setInterval(() => {
      if (C.paused || document.hidden) return;
      tampil(C.index + 1, false);
    }, INTERVAL_MS);
  }

  function jadwalkan() {
    hentikan();
    if (!C.paused) mulai();
  }

  function jeda() {
    C.paused = true;
    hentikan();
  }

  function lanjut() {
    C.paused = false;
    mulai();
  }

  /* -------------------------------------------------------------- fallback */
  function tampilkanFallback(pesan) {
    hentikan();
    const track = $('#carouselTrack');
    const fb = $('#carouselFallback');
    const dots = $('#carouselDots');
    const prev = $('#carouselPrev');
    const next = $('#carouselNext');
    const cap = $('#carouselCaptionText');

    if (track) track.innerHTML = '';
    if (dots) { dots.innerHTML = ''; dots.hidden = true; }
    if (prev) prev.hidden = true;
    if (next) next.hidden = true;
    if (fb) {
      const note = fb.querySelector('.carousel-fallback-note strong');
      if (note && pesan) note.textContent = pesan;
      fb.hidden = false;
    }
    if (cap) cap.textContent = 'Dokumentasi peserta SKOMDA Gesture Quiz.';
    C.siap = false;
  }

  /* ------------------------------------------------------------------ init */
  async function muat() {
    try {
      const res = await fetch(`${API}/api/galeri/publik`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const items = (Array.isArray(data.items) ? data.items : [])
        .filter((it) => it && it.nama_file && it.url)
        .slice(0, MAKS);
      if (!items.length) {
        tampilkanFallback();
        return;
      }
      C.items = items;
      C.gagal.clear();
      const fb = $('#carouselFallback');
      if (fb) fb.hidden = true;

      // Refresh periodik: bila daftar foto TIDAK berubah, jangan render ulang.
      // Tanpa ini, tiap 60 detik carousel melompat kembali ke foto pertama dan
      // menghapus posisi yang sedang dilihat pengunjung.
      const sidik = items.map((it) => it.nama_file).join('|');
      if (sidik === C.sidik && C.slides.length === items.length) {
        C.siap = true;
        if (!C.timer) mulai();
        return;
      }
      const aktifSekarang = C.items[C.index] && C.items[C.index].nama_file;
      C.sidik = sidik;
      renderUlang(0);
      // Pertahankan foto yang sedang aktif bila masih ada di daftar baru.
      if (aktifSekarang) {
        const pos = items.findIndex((it) => it.nama_file === aktifSekarang);
        if (pos > 0) tampil(pos, false);
      }
      C.siap = true;
      mulai();
    } catch (_) {
      // Backend mati / belum ada foto: halaman tetap tampil rapi.
      tampilkanFallback();
    }
  }

  function pasangKontrol() {
    const prev = $('#carouselPrev');
    const next = $('#carouselNext');
    if (prev) prev.addEventListener('click', () => tampil(C.index - 1, true));
    if (next) next.addEventListener('click', () => tampil(C.index + 1, true));

    // Foto fallback bisa ikut hilang (mis. clone repo tanpa fotocontoh.png).
    // Jangan tampilkan ikon gambar rusak: sembunyikan gambarnya saja dan
    // biarkan keterangan tetap terbaca di atas latar navy.
    const fbImg = document.querySelector('#carouselFallback img');
    if (fbImg) {
      const sembunyikan = () => fbImg.classList.add('is-broken');
      fbImg.addEventListener('error', sembunyikan);
      if (fbImg.complete && fbImg.naturalWidth === 0) sembunyikan();
    }

    const card = $('#heroCarousel');
    if (!card) return;
    // Pause saat kursor/fokus masuk, lanjut saat keluar.
    card.addEventListener('mouseenter', jeda);
    card.addEventListener('mouseleave', lanjut);
    card.addEventListener('focusin', jeda);
    card.addEventListener('focusout', () => {
      if (!card.contains(document.activeElement)) lanjut();
    });

    // Tab tersembunyi: jangan buang CPU/baterai untuk animasi.
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) hentikan();
      else if (!C.paused) mulai();
    });

    // Navigasi keyboard saat carousel difokuskan.
    card.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowLeft') { e.preventDefault(); tampil(C.index - 1, true); }
      if (e.key === 'ArrowRight') { e.preventDefault(); tampil(C.index + 1, true); }
    });
  }

  function init() {
    pasangKontrol();
    muat();
    // Segarkan tiap 60 detik: foto yang baru disetujui panitia muncul tanpa
    // pengunjung perlu me-reload halaman.
    setInterval(() => {
      if (document.hidden) return;
      muat();
    }, 60000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Diekspos untuk pengujian manual di konsol.
  window.skomdaCarousel = {
    muat,
    tampil: (i) => tampil(i, true),
    jumlah: () => C.items.length,
    indeks: () => C.index,
    dijeda: () => C.paused,
    autoplayAktif: () => C.timer !== null,
    items: () => C.items.slice(),
  };
})();
