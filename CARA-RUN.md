# Cara Menjalankan — SKOMDA Gesture Quiz

Kuis gerakan tangan untuk pameran SMK Telkom Sidoarjo.
Backend Python (FastAPI + OpenCV + MediaPipe), dua frontend statis (admin & pengunjung).

Panduan ini hanya soal menjalankan. Penjelasan arsitektur, algoritma gesture, dan
daftar variabel environment ada di `README.md`.

---

## 1. Prasyarat

| Kebutuhan | Keterangan |
|---|---|
| Python **3.11** | Wajib. MediaPipe yang dipakai di sini belum mendukung 3.12/3.13. Cek: `python --version` |
| Webcam | Kamera dimiliki **backend**, bukan browser. Satu kamera cukup. |
| Browser modern | Chrome / Edge terbaru untuk kedua panel. |
| Port bebas | 8000 (API), 3000 (admin), 8080 (pengunjung). |

Sistem operasi: Windows 11 (paling teruji), Linux/macOS jalan dengan perintah
yang sama (ganti path `.venv\Scripts\` menjadi `.venv/bin/`).

---

## 2. Cara tercepat (Windows)

Klik dua kali **`start.bat`**. Skrip itu otomatis:

1. memeriksa `.venv` dan model MediaPipe (mengunduh model bila hilang),
2. mengetes kamera dan memberi tahu bila tidak terdeteksi,
3. menjalankan backend + admin + pengunjung sekaligus dan mencetak URL-nya.

Jendela CMD harus dibiarkan terbuka selama pameran.

Menghentikan: **Ctrl+C** di jendela itu (kamera ikut dilepas), atau klik dua kali
**`stop.bat`** kalau jendela sudah tertutup tapi port masih dipakai.

---

## 3. Cara manual (semua OS)

Dari folder proyek (`kelompok1dtp`).

### 3.1 Buat virtualenv dan pasang dependency

```bash
python -m venv .venv

# Windows
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt

# Linux / macOS
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

Kalau hanya butuh memastikan environment sudah benar:

```bash
.venv\Scripts\python.exe -m pip check
```

### 3.2 Siapkan model MediaPipe

Model `hand_landmarker.task` (± 7,5 MB) **ikut di dalam repo**, jadi biasanya
langkah ini dilewati. Jalankan hanya bila file itu hilang:

```bash
.venv\Scripts\python.exe scripts\download_model.py
```

Hasilnya: `backend/models/hand_landmarker.task`.

### 3.3 Jalankan ketiga service sekaligus

```bash
.venv\Scripts\python.exe scripts\run_all.py
```

Output yang benar kira-kira:

```
  [1/3] Backend siap di http://localhost:8000
  [2/3] Menjalankan admin panel…
  [3/3] Menjalankan panel pengunjung…
  API      : http://localhost:8000  (http://localhost:8000/docs)
  Admin    : http://localhost:3000   (admin / skomda2026)
  Visitor  : http://localhost:8080
```

### 3.4 Buka panel

| Panel | URL | Login |
|---|---|---|
| Admin / panitia | http://localhost:3000 | `admin` / `skomda2026` |
| Pengunjung / permainan | http://localhost:8080 | tidak perlu login |
| Dokumentasi API | http://localhost:8000/docs | — |
| Health check | http://localhost:8000/api/health | — |

Database SQLite dibuat otomatis di `backend/data/quiz.db` saat pertama dijalankan.

---

## 4. Menjalankan service satu per satu (untuk development)

Tiga terminal terpisah, semuanya dari folder proyek:

```bash
# 1) Backend + computer vision (port 8000, tambah --reload untuk auto-restart)
cd backend
..\.venv\Scripts\python.exe -m app --port 8000 --reload

# 2) Admin panel (port 3000)
.venv\Scripts\python.exe scripts\serve_frontend.py admin --port 3000 --api http://localhost:8000

# 3) Visitor panel (port 8080)
.venv\Scripts\python.exe scripts\serve_frontend.py visitor --port 8080 --api http://localhost:8000
```

`serve_frontend.py` menyajikan `/config.js` berisi `window.SKOMDA_API`, jadi alamat
backend tidak di-hardcode di HTML.

Kalau port 3000/8080 sedang dipakai, server statis otomatis pindah ke port
berikutnya dan mencetak URL yang benar-benar dipakai — perhatikan outputnya.

---

## 5. Menghentikan

- `run_all.py` / `start.bat` aktif: **Ctrl+C** di jendelanya.
- Jendela sudah tertutup tapi port masih dipakai: jalankan **`stop.bat`**,
  atau manual:

```bash
netstat -ano | findstr ":8000 :3000 :8080"
taskkill /PID <PID> /F
```

---

## 6. Cek cepat sebelum pameran

```bash
# unit + integration test (tanpa kamera) — harus 95 passed
.venv\Scripts\python.exe -m pytest -q

# uji kamera nyata (tanpa jendela)
.venv\Scripts\python.exe tests\manual_camera_check.py

# uji kamera dengan jendela preview
.venv\Scripts\python.exe tests\manual_camera_check.py --gui
```

Bersihkan sesi lama yang menggantung (mis. setelah listrik mati saat pameran):

```bash
.venv\Scripts\python.exe scripts\bersihkan_sesi.py           # lihat saja
.venv\Scripts\python.exe scripts\bersihkan_sesi.py --apply   # tutup sesinya
```

---

## 7. Troubleshooting

| Gejala | Penyebab & solusi |
|---|---|
| `ModuleNotFoundError: fastapi` | Virtualenv belum dipakai. Panggil Python lewat path `.venv\Scripts\python.exe`, jangan `python` global. |
| `pip install` gagal di mediapipe | Python bukan 3.11. Pasang 3.11 lalu buat ulang venv. |
| `[X] Folder .venv tidak ditemukan` dari start.bat | Belum pernah install. Ikuti langkah 3.1. |
| Backend hidup tapi kamera hitam | Kamera dipakai aplikasi lain (Zoom/Teams/OBS). Tutup dulu. Coba `SKOMDA_CAM_INDEX=1`. |
| Kamera tidak terdeteksi | Permainan tetap jalan; tombol "Kamera bermasalah? Jawab dengan klik" tersedia selama `SKOMDA_ALLOW_MANUAL_ANSWER=1`. |
| Panel menampilkan "tidak bisa menghubungi server" | Backend belum siap atau beda port. Buka http://localhost:8000/api/health lebih dulu. |
| `Address already in use` di port 8000 | Jalankan `stop.bat`, atau set `SKOMDA_PORT=8001` (lalu `run_all.py` ikut menyesuaikan). |
| Login admin ditolak | Password mungkin sudah diganti lewat menu Pengaturan. Reset: hapus `backend/data/quiz.db` (data soal & sesi ikut hilang) lalu jalankan ulang. |
| Model hilang setelah clone | `python scripts\download_model.py`, atau salin `backend/models/hand_landmarker.task` dari flashdisk. |
| Sesi pengunjung menggantung "berjalan" | `python scripts\bersihkan_sesi.py --apply`. |

---

## 8. Environment variable yang sering dipakai saat pameran

| Variabel | Default | Fungsi |
|---|---|---|
| `SKOMDA_PORT` | `8000` | Port backend (frontend ikut menyesuaikan) |
| `SKOMDA_CAM_INDEX` | `0` | Index webcam (0 = kamera utama) |
| `SKOMDA_ALLOW_MANUAL_ANSWER` | `1` | `0` = jawaban murni gesture, tombol klik dimatikan |
| `SKOMDA_ADMIN_USER` / `SKOMDA_ADMIN_PASS` | `admin` / `skomda2026` | Akun awal saat database masih kosong |
| `SKOMDA_ABANDON_AFTER` | `120` | Detik sebelum sesi telantar ditutup `dibatalkan` |
| `SKOMDA_DB` | `backend/data/quiz.db` | Lokasi file SQLite |

Contoh (Windows CMD):

```bat
set SKOMDA_CAM_INDEX=1
set SKOMDA_ALLOW_MANUAL_ANSWER=0
start.bat
```

> Sebelum pameran: ganti password default lewat menu **Pengaturan** di panel admin.

---

## 9. Isi repo sekilas

```
backend/app/       FastAPI, database SQLite, security JWT, cv/ (kamera→gesture), game/engine
backend/models/    hand_landmarker.task (model MediaPipe)
backend/data/      quiz.db dibuat otomatis (tidak di-commit)
frontend/admin/    panel panitia  (:3000)
frontend/visitor/  panel pengunjung (:8080)
scripts/           run_all.py · serve_frontend.py · download_model.py · bersihkan_sesi.py
tests/             95 test otomatis + skrip cek kamera
requirements.txt   daftar library Python (versi dipin & sudah diuji)
start.bat          jalankan semua (Windows)
stop.bat           hentikan semua bila jendela terlanjur tertutup
```
