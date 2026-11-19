/* =========================================================================
   SKOMDA Gesture Quiz — PHOTO MOMENT
   Mengambil frame terakhir dari backend (kamera tetap milik server), menyusun
   overlay SKOMDA di <canvas>, dan menyimpan hasilnya sebagai PNG lokal.

   PRINSIP (mengikuti instruksi proyek):
     * Foto TIDAK PERNAH diambil otomatis — selalu lewat tombol AMBIL FOTO.
     * Foto TIDAK disimpan sebelum pengunjung menekan SIMPAN FOTO.
     * Foto TIDAK dikirim ke layanan mana pun; unduhan dibuat dari canvas.
     * Kamera dilepas setelah sesi foto (memanggil /api/cv/stop).
   ========================================================================= */
(function () {
  'use strict';

  const API = window.SKOMDA_API || 'http://localhost:8000';
  const $ = (s) => document.querySelector(s);

  const W = 1200;
  const H = 900;
  const COUNTDOWN_FROM = 3;

  const RED = '#E4002B';
  const NAVY = '#0B1526';
  const WHITE = '#FFFFFF';
  const SLATE = '#8A94A6';
  const P2 = '#2F7FD1';

  const P = {
    ctx: null,
    frame: null,        // ImageBitmap/Image frame mentah yang sudah diambil
    context: null,      // { mode, hasil }
    snapshotted: false,
    saving: false,
    sent: false,        // sudah dikirim ke galeri panitia (sekali per foto)
    countdownTimer: null,
    logo: null,         // HTMLImageElement logo sekolah (bila tersedia)
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

  /** Fallback bila app.js belum/tidak memuat helper bersama. */
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

  /* -------------------------------------------------------- logo (opsional) */
  function loadLogo() {
    if (P.logo) return Promise.resolve(P.logo);
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => { P.logo = img; resolve(img); };
      img.onerror = () => { P.logo = null; resolve(null); };
      img.src = 'assets/img/logo-sekolah.png';
    });
  }

  /* ------------------------------------------------------- frame kamera */
  async function fetchFrame() {
    const res = await fetch(`${API}/api/cv/photo-frame?t=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) {
      let detail = 'Kamera belum siap.';
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    try {
      const img = new Image();
      img.decoding = 'sync';
      await new Promise((resolve, reject) => {
        img.onload = resolve;
        img.onerror = () => reject(new Error('Frame kamera tidak dapat dibaca.'));
        img.src = url;
      });
      // Salin ke canvas agar bitmap tidak bergantung pada object URL.
      const c = document.createElement('canvas');
      c.width = img.naturalWidth || W;
      c.height = img.naturalHeight || H;
      c.getContext('2d').drawImage(img, 0, 0);
      return c;
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  /* -------------------------------------------------------------- overlay */
  function roundRect(ctx, x, y, w, h, r) {
    const rr = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + rr, y);
    ctx.lineTo(x + w - rr, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + rr);
    ctx.lineTo(x + w, y + h - rr);
    ctx.quadraticCurveTo(x + w, y + h, x + w - rr, y + h);
    ctx.lineTo(x + rr, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - rr);
    ctx.lineTo(x, y + rr);
    ctx.quadraticCurveTo(x, y, x + rr, y);
    ctx.closePath();
  }

  function drawCover(ctx, img, x, y, w, h) {
    const iw = img.width || img.naturalWidth;
    const ih = img.height || img.naturalHeight;
    const scale = Math.max(w / iw, h / ih);
    const sw = w / scale;
    const sh = h / scale;
    const sx = (iw - sw) / 2;
    const sy = (ih - sh) / 2;
    ctx.drawImage(img, sx, sy, sw, sh, x, y, w, h);
  }

  function drawLogoMark(ctx, x, y, size) {
    if (P.logo) {
      ctx.save();
      roundRect(ctx, x, y, size, size, size * 0.22);
      ctx.clip();
      ctx.fillStyle = WHITE;
      ctx.fillRect(x, y, size, size);
      ctx.drawImage(P.logo, x + 2, y + 2, size - 4, size - 4);
      ctx.restore();
      return;
    }
    ctx.save();
    roundRect(ctx, x, y, size, size, size * 0.22);
    ctx.fillStyle = RED;
    ctx.fill();
    ctx.fillStyle = WHITE;
    ctx.font = `800 ${Math.round(size * 0.34)}px "Plus Jakarta Sans", system-ui, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('SMK', x + size / 2, y + size / 2 + 1);
    ctx.restore();
  }

  /**
   * Gambar hasil foto lengkap: foto sebagai elemen utama, overlay branding
   * SKOMDA + identitas sekolah + skor. Tidak ada data yang meninggalkan canvas.
   */
  function composePhoto(frame, context) {
    const ctx = P.ctx;
    ctx.clearRect(0, 0, W, H);

    const pad = 34;
    const headerH = 132;
    const footerH = context.mode === 'battle' ? 218 : 178;
    const photoX = pad;
    const photoY = headerH + 18;
    const photoW = W - pad * 2;
    const photoH = H - photoY - footerH;

    // Latar: navy dengan aksen merah diagonal.
    ctx.fillStyle = NAVY;
    ctx.fillRect(0, 0, W, H);
    const grad = ctx.createLinearGradient(0, 0, W, H);
    grad.addColorStop(0, 'rgba(228,0,43,0.30)');
    grad.addColorStop(0.55, 'rgba(228,0,43,0.03)');
    grad.addColorStop(1, 'rgba(47,127,209,0.18)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, H);

    // Grid teknologi halus.
    ctx.strokeStyle = 'rgba(255,255,255,0.045)';
    ctx.lineWidth = 1;
    for (let x = 0; x < W; x += 48) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
    }
    for (let y = 0; y < H; y += 48) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    }

    // Foto.
    if (frame) {
      drawCover(ctx, frame, photoX, photoY, photoW, photoH);
    } else {
      ctx.fillStyle = '#060C16';
      ctx.fillRect(photoX, photoY, photoW, photoH);
      ctx.fillStyle = SLATE;
      ctx.font = '600 26px "Plus Jakarta Sans", system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Tidak ada frame kamera', photoX + photoW / 2, photoY + photoH / 2);
    }

    // Bingkai foto + sudut aksen.
    ctx.strokeStyle = 'rgba(255,255,255,0.22)';
    ctx.lineWidth = 3;
    roundRect(ctx, photoX, photoY, photoW, photoH, 22);
    ctx.stroke();
    ctx.strokeStyle = RED;
    ctx.lineWidth = 5;
    const corner = 46;
    [[photoX, photoY, 1, 1], [photoX + photoW, photoY, -1, 1],
     [photoX, photoY + photoH, 1, -1], [photoX + photoW, photoY + photoH, -1, -1]]
      .forEach(([cx, cy, dx, dy]) => {
        ctx.beginPath();
        ctx.moveTo(cx + dx * corner, cy);
        ctx.lineTo(cx, cy);
        ctx.lineTo(cx, cy + dy * corner);
        ctx.stroke();
      });

    // Gradien bawah foto agar teks skor terbaca.
    const shade = ctx.createLinearGradient(0, photoY + photoH - 140, 0, photoY + photoH);
    shade.addColorStop(0, 'rgba(6,12,22,0)');
    shade.addColorStop(1, 'rgba(6,12,22,0.72)');
    ctx.fillStyle = shade;
    ctx.fillRect(photoX, photoY + photoH - 140, photoW, 140);

    /* ---------------------------------------------------------- header */
    drawLogoMark(ctx, pad + 4, 34, 66);

    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';
    ctx.fillStyle = WHITE;
    ctx.font = '800 27px "Plus Jakarta Sans", system-ui, sans-serif';
    ctx.fillText('SMK TELKOM SIDOARJO', pad + 88, 68);

    ctx.fillStyle = RED;
    ctx.font = '700 15px "JetBrains Mono", ui-monospace, monospace';
    ctx.fillText('SKOMDA GESTURE QUIZ', pad + 88, 92);
    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    ctx.font = '500 13px "Plus Jakarta Sans", system-ui, sans-serif';
    ctx.fillText('PAMERAN TEKNOLOGI · COMPUTER VISION', pad + 88, 112);

    // Stempel tanggal di kanan atas.
    const now = new Date();
    const stamp = now.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' });
    ctx.textAlign = 'right';
    ctx.fillStyle = 'rgba(255,255,255,0.62)';
    ctx.font = '600 13px "JetBrains Mono", ui-monospace, monospace';
    ctx.fillText(stamp, W - pad, 60);
    ctx.fillStyle = 'rgba(255,255,255,0.38)';
    ctx.font = '500 12px "Plus Jakarta Sans", system-ui, sans-serif';
    ctx.fillText(context.mode === 'battle' ? 'MODE 2 PLAYER BATTLE' : 'MODE SINGLE PLAYER', W - pad, 82);

    // Garis pemisah header.
    ctx.strokeStyle = 'rgba(255,255,255,0.16)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(pad, headerH);
    ctx.lineTo(W - pad, headerH);
    ctx.stroke();

    /* ---------------------------------------------------------- footer */
    const fy = H - footerH + 8;

    if (context.mode === 'battle' && context.hasil) {
      const h = context.hasil;
      const p1 = h.pemain['1'] || h.pemain[1];
      const p2 = h.pemain['2'] || h.pemain[2];

      const colW = (W - pad * 2 - 24) / 2;
      [{
        x: pad, color: RED, tag: 'PLAYER 1', data: p1, winner: h.pemenang === 1,
      }, {
        x: pad + colW + 24, color: P2, tag: 'PLAYER 2', data: p2, winner: h.pemenang === 2,
      }].forEach((col) => {
        roundRect(ctx, col.x, fy, colW, 96, 16);
        ctx.fillStyle = 'rgba(255,255,255,0.06)';
        ctx.fill();
        ctx.strokeStyle = col.winner ? col.color : 'rgba(255,255,255,0.14)';
        ctx.lineWidth = col.winner ? 3 : 1.5;
        ctx.stroke();

        // Bar warna identitas di kiri kartu.
        ctx.fillStyle = col.color;
        roundRect(ctx, col.x, fy, 7, 96, 4);
        ctx.fill();

        ctx.textAlign = 'left';
        ctx.fillStyle = col.color;
        ctx.font = '800 15px "JetBrains Mono", ui-monospace, monospace';
        ctx.fillText(col.tag + (col.winner ? ' · PEMENANG' : ''), col.x + 22, fy + 32);

        ctx.fillStyle = WHITE;
        ctx.font = '700 24px "Plus Jakarta Sans", system-ui, sans-serif';
        ctx.fillText(String((col.data && col.data.nama) || col.tag), col.x + 22, fy + 64);

        ctx.textAlign = 'right';
        ctx.fillStyle = WHITE;
        ctx.font = '700 40px "JetBrains Mono", ui-monospace, monospace';
        ctx.fillText(String((col.data && col.data.skor) ?? 0), col.x + colW - 22, fy + 60);

        ctx.fillStyle = 'rgba(255,255,255,0.55)';
        ctx.font = '600 13px "Plus Jakarta Sans", system-ui, sans-serif';
        ctx.fillText(
          `${(col.data && col.data.benar) ?? 0} benar · ${(col.data && col.data.persen) ?? 0}%`,
          col.x + colW - 22, fy + 82,
        );
      });

      // Status pemenang / seri.
      ctx.textAlign = 'center';
      if (h.seri) {
        ctx.fillStyle = '#F5A524';
        ctx.font = '800 21px "Plus Jakarta Sans", system-ui, sans-serif';
        ctx.fillText('SERI — KEDUA PEMAIN IMBANG', W / 2, H - 44);
      } else {
        const w = h.pemain[String(h.pemenang)] || h.pemain[h.pemenang];
        ctx.fillStyle = WHITE;
        ctx.font = '800 21px "Plus Jakarta Sans", system-ui, sans-serif';
        ctx.fillText(`🏆 ${(w && w.nama) || 'PEMAIN'} MENANG`, W / 2, H - 44);
      }
      ctx.fillStyle = 'rgba(255,255,255,0.34)';
      ctx.font = '500 12px "Plus Jakarta Sans", system-ui, sans-serif';
      ctx.fillText('SKOMDA GESTURE QUIZ · SMK TELKOM SIDOARJO', W / 2, H - 20);
    } else {
      const h = context.hasil || {};
      roundRect(ctx, pad, fy, W - pad * 2, 92, 16);
      ctx.fillStyle = 'rgba(255,255,255,0.06)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,255,255,0.14)';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      ctx.textAlign = 'left';
      ctx.fillStyle = RED;
      ctx.font = '800 15px "JetBrains Mono", ui-monospace, monospace';
      ctx.fillText('HASIL PERMAINAN', pad + 24, fy + 32);

      ctx.fillStyle = WHITE;
      ctx.font = '700 26px "Plus Jakarta Sans", system-ui, sans-serif';
      ctx.fillText(h.predikat || 'SELESAI', pad + 24, fy + 66);

      ctx.textAlign = 'right';
      ctx.fillStyle = WHITE;
      ctx.font = '700 46px "JetBrains Mono", ui-monospace, monospace';
      ctx.fillText(String(h.skor ?? 0), W - pad - 24, fy + 62);

      ctx.fillStyle = 'rgba(255,255,255,0.55)';
      ctx.font = '600 13px "Plus Jakarta Sans", system-ui, sans-serif';
      ctx.fillText(
        `${h.benar ?? 0} benar · ${h.salah ?? 0} salah · ${h.persen ?? 0}%`,
        W - pad - 24, fy + 82,
      );

      ctx.textAlign = 'center';
      ctx.fillStyle = 'rgba(255,255,255,0.34)';
      ctx.font = '500 12px "Plus Jakarta Sans", system-ui, sans-serif';
      ctx.fillText('SKOMDA GESTURE QUIZ · SMK TELKOM SIDOARJO', W / 2, H - 18);
    }
  }

  /* ---------------------------------------------------------- live preview */
  function renderEmpty() {
    const ctx = P.ctx;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#060C16';
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = SLATE;
    ctx.font = '600 22px "Plus Jakarta Sans", system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Pratinjau kamera akan tampil di sini', W / 2, H / 2 - 8);
    ctx.font = '500 16px "Plus Jakarta Sans", system-ui, sans-serif';
    ctx.fillText('Tekan AMBIL FOTO bila semua sudah siap.', W / 2, H / 2 + 22);
  }

  function setPlaceholder(text) {
    const ph = $('#photoPlaceholder');
    if (!ph) return;
    if (text) {
      $('#photoPlaceholderText').textContent = text;
      ph.classList.remove('is-hidden');
    } else {
      ph.classList.add('is-hidden');
    }
  }

  function setButtons(state) {
    const snap = $('#btnSnap');
    const retake = $('#btnRetake');
    const save = $('#btnSavePhoto');
    const send = $('#btnSendPhoto');
    if (snap) snap.disabled = !state.canSnap;
    if (retake) retake.disabled = !state.canRetake;
    if (save) save.disabled = !state.canSave;
    if (send) send.disabled = !state.canSave || P.sent;
  }

  /* -------------------------------------------------------------- actions */
  async function doSnap(useCountdown) {
    const countdown = $('#photoCountdown');
    const btn = $('#btnSnap');

    const take = async () => {
      countdown.classList.remove('is-show');
      try {
        setPlaceholder('Mengambil foto…');
        const frame = await fetchFrame();
        P.frame = frame;
        P.snapshotted = true;
        composePhoto(frame, P.context);
        setPlaceholder(null);
        setButtons({ canSnap: true, canRetake: true, canSave: true });
        P.sent = false;
        if (btn) btn.textContent = 'AMBIL FOTO';
        $('#photoTip').textContent =
          'Foto siap. Tekan SIMPAN FOTO untuk mengunduh, atau FOTO ULANG untuk mencoba lagi.';
      } catch (err) {
        setPlaceholder(err.message);
        toast(err.message, true);
        P.frame = null;
        P.snapshotted = false;
        setButtons({ canSnap: true, canRetake: false, canSave: false });
      }
    };
    if (!useCountdown) {
      await take();
      return;
    }

    // Hitung mundur singkat agar kedua pemain sempat bersiap. Tidak ada
    // frame yang diambil selama hitungan; foto tetap menunggu tombol.
    let n = COUNTDOWN_FROM;
    countdown.textContent = String(n);
    countdown.classList.add('is-show');
    if (btn) btn.disabled = true;
    clearInterval(P.countdownTimer);
    P.countdownTimer = setInterval(async () => {
      n -= 1;
      if (n > 0) {
        countdown.textContent = String(n);
        return;
      }
      clearInterval(P.countdownTimer);
      await take();
    }, 1000);
  }

  function downloadPhoto() {
    if (!P.snapshotted) {
      toast('Ambil foto dulu sebelum menyimpan.', true);
      return;
    }
    try {
      const ts = new Date();
      const pad = (v) => String(v).padStart(2, '0');
      const stamp = `${ts.getFullYear()}${pad(ts.getMonth() + 1)}${pad(ts.getDate())}`
        + `-${pad(ts.getHours())}${pad(ts.getMinutes())}${pad(ts.getSeconds())}`;
      const mode = P.context.mode === 'battle' ? 'battle' : 'single';
      const name = `skomda-photo-${mode}-${stamp}.png`;

      const url = P.ctx.canvas.toDataURL('image/png');
      const a = document.createElement('a');
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      $('#photoTip').textContent = `Foto disimpan sebagai ${name}`;
      toast('Foto disimpan di perangkat ini.');
    } catch (err) {
      toast('Gagal menyimpan foto: ' + err.message, true);
    }
  }

  /**
   * Kirim foto ke galeri panitia (komputer ini, bukan internet).
   * Hanya berjalan bila pengunjung menekan tombolnya — tidak pernah otomatis.
   */
  async function sendToGaleri() {
    if (!P.snapshotted) {
      toast('Ambil foto dulu sebelum mengirim.', true);
      return;
    }
    if (P.sent) return;

    const btn = $('#btnSendPhoto');
    const labelAsli = btn ? btn.textContent : 'KIRIM KE GALERI PANITIA';
    if (btn) { btn.disabled = true; btn.textContent = 'MENGIRIM…'; }

    try {
      const blob = await new Promise((resolve) => P.ctx.canvas.toBlob(resolve, 'image/png'));
      if (!blob) throw new Error('Gagal menyiapkan berkas foto.');

      const h = (P.context && P.context.hasil) || {};
      const isBattle = P.context.mode === 'battle';
      const fd = new FormData();
      fd.append('file', blob, 'skomda-photo.png');
      fd.append('mode', isBattle ? 'battle' : 'single');
      if (h.sesi_id) fd.append('sesi_id', h.sesi_id);
      if (isBattle && h.pemain) {
        const p1 = h.pemain['1'] || h.pemain[1] || {};
        const p2 = h.pemain['2'] || h.pemain[2] || {};
        fd.append('pemain_1', p1.nama || 'Player 1');
        fd.append('pemain_2', p2.nama || 'Player 2');
        fd.append('skor_1', String(p1.skor ?? 0));
        fd.append('skor_2', String(p2.skor ?? 0));
        const menang = h.seri
          ? 'SERI'
          : ((h.pemenang === 1 ? p1.nama : p2.nama) || (h.pemenang === 1 ? 'Player 1' : 'Player 2'));
        fd.append('pemenang', menang);
      } else {
        fd.append('pemain_1', 'Single Player');
        fd.append('skor_1', String(h.skor ?? 0));
        fd.append('pemenang', h.predikat || 'SELESAI');
      }

      const res = await fetch(`${API}/api/galeri/foto`, { method: 'POST', body: fd });
      let data = null;
      try { data = await res.json(); } catch (_) {}
      if (!res.ok) {
        throw new Error((data && data.detail) || `Gagal mengirim (${res.status})`);
      }

      P.sent = true;
      if (btn) btn.textContent = 'TERKIRIM ✓';
      $('#photoTip').textContent =
        'Foto sudah masuk galeri panitia. Kamu tetap bisa menyimpannya sendiri.';
      toast('Foto terkirim ke galeri panitia.');
    } catch (err) {
      if (btn) btn.textContent = labelAsli;
      toast('Gagal mengirim foto: ' + err.message, true);
    } finally {
      if (btn) btn.disabled = P.sent || !P.snapshotted;
    }
  }

  async function retake() {
    P.frame = null;
    P.snapshotted = false;
    P.sent = false;
    setButtons({ canSnap: true, canRetake: false, canSave: false });
    setPlaceholder('Menyiapkan kamera…');
    $('#photoTip').textContent = 'Hadapkan wajah ke kamera, lalu tekan AMBIL FOTO.';
    renderEmpty();
    try {
      await api('/api/cv/start?mode=' + (P.context.mode === 'battle' ? 'battle' : 'single'),
        { method: 'POST' });
      setPlaceholder(null);
      // Tampilkan pratinjau langsung sebagai pengganti frame.
      startPreview();
    } catch (err) {
      setPlaceholder('Kamera tidak tersedia: ' + err.message);
    }
  }

  let previewTimer = null;
  function startPreview() {
    clearInterval(previewTimer);
    previewTimer = setInterval(async () => {
      if (P.snapshotted) return;
      try {
        const frame = await fetchFrame();
        // Pratinjau LIVE tanpa overlay: pengunjung melihat apa yang akan
        // tertangkap, overlay baru ditambahkan setelah tombol ditekan.
        P.ctx.drawImage(frame, 0, 0, W, H);
      } catch (_) { /* biarkan frame terakhir */ }
    }, 700);
  }

  function stopPreview() {
    clearInterval(previewTimer);
    previewTimer = null;
  }

  async function closePhoto() {
    stopPreview();
    clearInterval(P.countdownTimer);
    const countdown = $('#photoCountdown');
    if (countdown) countdown.classList.remove('is-show');
    P.frame = null;
    P.snapshotted = false;
    P.context = null;
    // Lepas kamera dengan benar setelah sesi foto.
    try {
      await fetch(`${API}/api/cv/stop`, { method: 'POST' });
    } catch (_) {}
    setButtons({ canSnap: true, canRetake: false, canSave: false });
    showScreen('landing');
  }

  /* ----------------------------------------------------------------- open */
  async function openPhoto(opts) {
    P.context = { mode: (opts && opts.mode) || 'single', hasil: (opts && opts.hasil) || null };
    P.frame = null;
    P.snapshotted = false;

    const canvas = $('#photoCanvas');
    if (canvas) {
      canvas.width = W;
      canvas.height = H;
      P.ctx = canvas.getContext('2d');
    }
    showScreen('photo');
    renderEmpty();
    setButtons({ canSnap: false, canRetake: false, canSave: false });
    setPlaceholder('Menyiapkan kamera…');
    $('#photoTip').textContent = 'Hadapkan wajah ke kamera, lalu tekan AMBIL FOTO.';

    await loadLogo();

    // Pastikan kamera aktif dengan mode yang benar (permainan sudah menutupnya).
    try {
      await api(
        '/api/cv/start?mode=' + (P.context.mode === 'battle' ? 'battle' : 'single'),
        { method: 'POST' },
      );
      setPlaceholder(null);
      startPreview();
    } catch (err) {
      setPlaceholder('Kamera tidak tersedia. ' + err.message);
      toast('Kamera tidak tersedia untuk sesi foto.', true);
    }
    setButtons({ canSnap: true, canRetake: false, canSave: false });
  }

  /* ----------------------------------------------------------------- init */
  function init() {
    const snap = $('#btnSnap');
    if (snap) snap.addEventListener('click', () => {
      stopPreview();
      doSnap(true);
    });

    const retakeBtn = $('#btnRetake');
    if (retakeBtn) retakeBtn.addEventListener('click', () => {
      stopPreview();
      retake();
    });

    const saveBtn = $('#btnSavePhoto');
    if (saveBtn) saveBtn.addEventListener('click', downloadPhoto);

    const sendBtn = $('#btnSendPhoto');
    if (sendBtn) sendBtn.addEventListener('click', sendToGaleri);

    const done = $('#btnDonePhoto');
    if (done) done.addEventListener('click', closePhoto);
  }

  window.skomdaOpenPhoto = openPhoto;
  window.skomdaClosePhoto = closePhoto;

  document.addEventListener('DOMContentLoaded', init);
})();
