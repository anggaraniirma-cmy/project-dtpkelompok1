# SKOMDA Gesture Quiz

Kuis interaktif berbasis Computer Vision untuk pameran **SMK Telkom Sidoarjo**.
Pengunjung menjawab pertanyaan dengan **gerakan jari** (A/B/C/D) yang dibaca
langsung dari webcam — tanpa keyboard, tanpa sentuhan.

Deteksi tangan memakai **MediaPipe Hand Landmarker (21 titik)** dan klasifikasi
rule-based per jari, dijalankan di **Python + OpenCV** dan disalurkan ke browser
melalui **FastAPI**.

---

## Arsitektur

```
                        ┌─────────────────────────────┐
   Admin  :3000 ───────▶│  FastAPI  :8000             │
                        │  ├─ /api/auth   (JWT)       │
   Visitor :8080 ──────▶│  ├─ /api/admin  (CRUD soal) │──▶ SQLite quiz.db
                        │  ├─ /api/game   (sesi)      │
                        │  └─ /api/cv     (MJPEG+WS)  │──▶ Webcam + MediaPipe
                        └─────────────────────────────┘
```

Satu backend, satu database, dua frontend terpisah. Kamera **dimiliki backend**,
bukan browser: browser hanya menerima stream MJPEG dan status lewat WebSocket.
Karena itu jawaban tidak bisa dipalsukan dari DevTools.

### Struktur folder

```
backend/
  app/
    config.py            konfigurasi (env) & path
    database.py          skema SQLite, seed, pengaturan permainan
    security.py          bcrypt + JWT + dependency require_admin
    schemas.py           validasi Pydantic
    main.py              FastAPI, CORS, lifespan
    cv/
      camera.py          thread capture webcam
      landmarks.py       MediaPipe HandLandmarker (21 landmark)
      gesture.py         klasifikasi A/B/C/D per jari
      stabilizer.py      temporal smoothing, hold 1s, cooldown, re-arm
      overlay.py         gambar landmark + HUD (OpenCV)
      pipeline.py        kamera → deteksi → klasifikasi → stabilisasi → JPEG
    game/engine.py       state sesi, timer, skor, anti jawaban ganda
    routers/             auth.py · admin.py · game.py · cv.py
  data/quiz.db           database (dibuat otomatis)
  models/*.task          model MediaPipe
frontend/
  admin/                 panel panitia  (:3000)
  visitor/               panel pengunjung (:8080)
scripts/
  run_all.py             jalankan ketiga service
  serve_frontend.py      static server untuk kedua frontend
  download_model.py      unduh model MediaPipe bila belum ada
tests/                   87 test otomatis
```

---

## Menjalankan

Butuh **Python 3.11** dan webcam.

```bash
# 1. virtualenv
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt     # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # Linux/macOS

# 2. model MediaPipe (hanya bila backend/models/*.task belum ada)
.venv/Scripts/python.exe scripts/download_model.py

# 3. jalankan semuanya
.venv/Scripts/python.exe scripts/run_all.py
```

| Service | URL | Keterangan |
|---|---|---|
| Admin Panel | http://localhost:3000 | login `admin` / `skomda2026` |
| Visitor / Game | http://localhost:8080 | tanpa login |
| Backend API | http://localhost:8000 | dokumentasi di `/docs` |

Jalankan terpisah bila perlu:

```bash
cd backend && ../.venv/Scripts/python.exe -m app --port 8000
.venv/Scripts/python.exe scripts/serve_frontend.py admin   --port 3000 --api http://localhost:8000
.venv/Scripts/python.exe scripts/serve_frontend.py visitor --port 8080 --api http://localhost:8000
```

`serve_frontend.py` menyajikan `/config.js` berisi `window.SKOMDA_API`, sehingga
kedua frontend tidak menyimpan alamat backend secara hardcode.

---

## Cara bermain

1. Buka http://localhost:8080, tekan **MULAI BERMAIN**.
2. Berdiri di depan kamera, gunakan **tangan kanan**, **ibu jari terlipat**.
3. Bentuk gerakan sesuai jawaban:

   | Gesture | Jari terangkat |
   |---|---|
   | **A** | telunjuk |
   | **B** | telunjuk + tengah |
   | **C** | telunjuk + tengah + manis |
   | **D** | telunjuk + tengah + manis + kelingking |

4. Tahan ±1 detik sampai bilah progres penuh → jawaban terkunci.
5. Lepas tangan sebelum menjawab soal berikutnya (mencegah jawaban ganda).

Tombol **"Kamera bermasalah? Jawab dengan klik"** adalah jalur cadangan darurat.
Matikan dengan `SKOMDA_ALLOW_MANUAL_ANSWER=0` bila ingin jawaban murni gesture.

---

## Gesture recognition

Bukan menghitung jumlah jari. Setiap jari dinilai terpisah dengan dua ukuran
geometri yang invarian terhadap jarak & rotasi:

- **Rasio panjang** `|tip − wrist| / |pip − wrist|` — jari terlipat melipat ke
  telapak sehingga ujungnya mendekat ke pergelangan.
- **Kelurusan** kosinus sudut di sendi PIP — jari lurus ≈ 1.0, tertekuk turun.

Ibu jari punya aturan sendiri (abduksi terhadap pusat telapak). Semua ambang
dinormalisasi oleh lebar telapak `|mcp telunjuk − mcp kelingking|`.

Stabilisasi: sampel 0,6 detik + mayoritas ≥60%, harus bertahan 1 detik penuh,
lalu cooldown 1,5 detik dan latch sampai tangan dilepas. Gesture di luar aturan
(campuran tidak berurutan, ibu jari terbuka, tangan kiri) diabaikan.

Angka-angka ini bisa diubah panitia di **Pengaturan** tanpa menyentuh kode.

### Kalibrasi ambang dengan tangan nyata

Ambang bawaan diturunkan dari geometri tangan, bukan dari data lapangan. Untuk
menyetelnya ke tangan dan kamera pameran yang sebenarnya:

```bash
# 1. rekam sampel (jendela kamera muncul; tekan A/B/C/D beberapa kali)
.venv/Scripts/python.exe tests/record_gesture_samples.py

# 2. analisis sebaran → usulan ambang + laporan celah antar kelas
.venv/Scripts/python.exe scripts/analyze_calibration.py samples-20260101-1200.jsonl
```

Skrip analisis melaporkan persentil rasio & kelurusan per jari untuk kelas
"terangkat" vs "terlipat", akurasi ambang yang sedang dipakai pada data Anda,
dan memberi tahu bila kelasnya **tidak** terpisah bersih (mis. label tertukar
atau sudut kamera kurang tepat) — bukan memaksakan ambang yang terlihat bagus.

---

## Waktu & sesi (server-side)

Semua keputusan waktu diambil dari jam server (`time.monotonic`), bukan timer
JavaScript:

- Jawaban yang datang setelah durasi soal habis **ditolak** dan dicatat timeout.
- Worker di `lifespan` berdetak tiap detik: mencatat timeout, memajukan soal,
  dan menyelesaikan permainan tanpa perlu browser.
- `/next` diabaikan bila soal aktif belum dijawab, sehingga klik ganda tidak
  melompati soal.
- Sesi yang ditinggal lebih dari `SKOMDA_ABANDON_AFTER` detik (default 120)
  ditutup sebagai `dibatalkan`, tidak menggantung selamanya.

Bila ada sesi lama yang terlanjur menggantung:

```bash
.venv/Scripts/python.exe scripts/bersihkan_sesi.py           # lihat
.venv/Scripts/python.exe scripts/bersihkan_sesi.py --apply   # tutup
```

---

## Pengaturan panitia (panel admin)

- **Jumlah soal per sesi** (1–20)
- **Durasi bawaan soal** (5–180 detik)
- **Lama menahan gesture** (0,6–3,0 detik)
- **Jeda antar jawaban** (0,5–5,0 detik)
- **Ganti password** admin (wajib password lama, min. 8 karakter, huruf + angka)

Nilai disimpan di tabel `pengaturan` (SQLite) sehingga permanen. Hold & cooldown
dibaca ulang saat kamera dinyalakan, jadi perubahan berlaku pada sesi berikutnya.

---

## Pengujian

```bash
.venv/Scripts/python.exe -m pytest -q            # 95 test, tanpa kamera
.venv/Scripts/python.exe tests/manual_camera_check.py         # kamera nyata
.venv/Scripts/python.exe tests/manual_camera_check.py --gui   # dengan jendela
```

Cakupan otomatis: klasifikasi A–D (termasuk skala 0,7–1,5× dan rotasi ±25°),
penolakan gesture tak valid, stabilisasi/cooldown/jitter, autentikasi & otorisasi
admin, CRUD soal, validasi input, alur permainan penuh, jawaban ganda, timeout,
batas waktu server-side & pembatalan sesi telantar, pengaturan, ganti password.

`manual_camera_check.py` melaporkan apa adanya: bila tidak ada tangan di depan
kamera, statusnya "TIDAK ADA TANGAN TERDETEKSI" — bukan klaim berhasil.

---

## Konfigurasi (environment)

| Variabel | Default | Keterangan |
|---|---|---|
| `SKOMDA_PORT` | `8000` | port backend |
| `SKOMDA_DB` | `backend/data/quiz.db` | path SQLite |
| `SKOMDA_SECRET` | file `.jwt_secret` | secret JWT |
| `SKOMDA_ADMIN_USER` / `_PASS` | `admin` / `skomda2026` | akun awal (seed saja) |
| `SKOMDA_CAM_INDEX` | `0` | index webcam |
| `SKOMDA_ALLOW_MANUAL_ANSWER` | `1` | `0` = jawaban murni gesture |
| `SKOMDA_ALLOW_FEED` | `0` | `1` = endpoint injeksi gesture untuk demo |
| `SKOMDA_ADVANCE_GRACE` | `2.0` | jeda feedback sebelum soal berikutnya (detik) |
| `SKOMDA_ABANDON_AFTER` | `120` | sesi ditutup bila ditinggal selama ini (detik) |

> **Sebelum pameran:** ganti password default lewat menu Pengaturan.

---

## Logo sekolah

Letakkan file logo resmi sebagai `assets/img/logo-sekolah.png` di
`frontend/visitor/` dan `frontend/admin/`. Selama belum ada, tampil monogram
"SMK" berlatar merah Telkom. Lihat `assets/img/README-LOGO.txt` untuk spesifikasi.
