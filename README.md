# SKOMDA Gesture Quiz

Kuis interaktif berbasis Computer Vision untuk pameran **SMK Telkom Sidoarjo**.
Pengunjung menjawab pertanyaan dengan **gerakan jari** (A/B/C/D) yang dibaca
langsung dari webcam — tanpa keyboard, tanpa sentuhan.

Deteksi tangan memakai **MediaPipe Hand Landmarker (21 titik)** dan klasifikasi
rule-based per jari, dijalankan di **Python + OpenCV** dan disalurkan ke browser
melalui **FastAPI**.

> Cara menjalankan langkah demi langkah (install, model, URL, troubleshooting):
> lihat **`CARA-RUN.md`**. Daftar library ada di `requirements.txt`.

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
      landmarks.py       MediaPipe HandLandmarker (21 landmark, 1-2 tangan)
      gesture.py         klasifikasi A/B/C/D per jari
      players.py         pemisahan Player 1/2 berdasarkan zona kamera
      stabilizer.py      temporal smoothing, hold 1s, cooldown, re-arm
      overlay.py         gambar landmark + HUD single & battle (OpenCV)
      pipeline.py        kamera → deteksi → klasifikasi → stabilisasi → JPEG
    game/
      engine.py          sesi single player, timer, skor, anti jawaban ganda
      battle.py          sesi 2 pemain: skor & jawaban terpisah per pemain
    routers/             auth.py · admin.py · game.py · battle.py · cv.py
  data/quiz.db           database (dibuat otomatis)
  models/*.task          model MediaPipe
frontend/
  admin/                 panel panitia  (:3000)
  visitor/               panel pengunjung (:8080)
scripts/
  run_all.py             jalankan ketiga service
  serve_frontend.py      static server untuk kedua frontend
  download_model.py      unduh model MediaPipe bila belum ada
tests/                    berisi test otomatis + skrip cek kamera
```

---

## Menjalankan

Butuh **Python 3.11** dan webcam.

### Cara tercepat (Windows)

Klik dua kali **`start.bat`** di folder proyek. Skrip itu akan:

1. memeriksa `.venv` dan model MediaPipe (mengunduh model bila hilang),
2. mengetes kamera dan memberi tahu bila tidak terdeteksi,
3. menjalankan ketiga service sekaligus dan mencetak URL-nya.

Biarkan jendelanya terbuka selama pameran. Untuk menghentikan semuanya
(kamera ikut dilepas): **Ctrl+C** di jendela itu, atau klik dua kali **`stop.bat`**
berguna bila jendela sudah terlanjur tertutup tapi port masih dipakai.

### Cara manual (semua OS)

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

Halaman awal menampilkan **dua kartu mode**. Pilih salah satu:

### Single Player — `MULAI`

1. Berdiri di depan kamera, gunakan **tangan kanan**, **ibu jari terlipat**.
2. Bentuk gerakan sesuai jawaban:

   | Gesture | Jari terangkat |
   |---|---|
   | **A** | telunjuk |
   | **B** | telunjuk + tengah |
   | **C** | telunjuk + tengah + manis |
   | **D** | telunjuk + tengah + manis + kelingking |

3. Tahan ±1 detik sampai bilah progres penuh → jawaban terkunci.
4. Lepas tangan sebelum menjawab soal berikutnya (mencegah jawaban ganda).

### 2 Player Battle — `MULAI BATTLE`

1. Dua pengunjung berdiri **berdampingan**: Player 1 di **zona kiri** kamera,
   Player 2 di **zona kanan**. Keduanya memakai **tangan kanan**.
2. Keduanya mendapat **pertanyaan yang sama** dan menjawab dengan gesture A/B/C/D.
3. Setiap pemain punya stabilizer, progress tahan, cooldown, dan skor sendiri.
   Jawaban yang sudah terkunci tidak bisa berubah dan tidak dihitung dua kali.
4. Soal berganti setelah **keduanya** menjawab (atau waktu habis). Pemain yang
   sudah menjawab tetap memegang statusnya sambil menunggu.
5. Di akhir, skor dibandingkan: pemenang ditentukan dari skor; skor sama = **SERI**.

Cara sistem menentukan pemain: **posisi tangan pada frame**, bukan urutan deteksi.
MediaPipe bisa mengembalikan tangan dalam urutan apa pun; backend mengurutkan
berdasarkan posisi horizontal telapak, lalu menetapkan yang paling kiri ke
Player 1 dan yang paling kanan ke Player 2. Tangan kiri ditolak. Bila kedua
tangan berada di zona yang salah (pengunjung berdempetan), permainan tetap
jalan tetapi overlay dan panel menampilkan peringatan **"di luar zona"**.

### Photo Moment

Setelah permainan selesai (kedua mode), tombol **AMBIL FOTO?** membuka sesi foto:

| Tombol | Fungsi |
|---|---|
| **AMBIL FOTO** | hitung mundur 3 detik, lalu mengambil satu frame |
| **FOTO ULANG** | membuang hasil dan kembali ke pratinjau |
| **SIMPAN FOTO** | mengunduh PNG ke perangkat pengunjung |
| **SELESAI** | melepas kamera dan kembali ke beranda |

Foto tidak pernah diambil otomatis, tidak disimpan sebelum tombol **SIMPAN FOTO**,
dan tidak dikirim ke layanan mana pun — overlay digambar di `<canvas>` browser
lalu diunduh sebagai `skomda-photo-<mode>-<timestamp>.png`. Nama file memakai
timestamp sehingga tidak pernah menimpa foto sebelumnya.

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

Catatan handedness: frame dicerminkan (mode cermin) sebelum inferensi, sedangkan
MediaPipe melabeli `Right`/`Left` berdasarkan gambar apa adanya. Karena itu label
dibalik di `landmarks.real_handedness()` supaya "tangan kanan" di UI = tangan
kanan pengunjung yang sebenarnya.

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

## Pengujian

```bash
.venv\Scripts\python.exe -m pytest -q            # harus 144 passed
.venv\Scripts\python.exe tests\manual_camera_check.py
.venv\Scripts\python.exe tests\manual_camera_check.py --gui

# mode 2 pemain (butuh dua orang di depan kamera)
.venv\Scripts\python.exe tests\manual_battle_check.py
.venv\Scripts\python.exe tests\manual_battle_check.py --seconds 60

# uji integrasi terhadap backend yang sedang berjalan
.venv\Scripts\python.exe tests\live_check_battle.py http://127.0.0.1:8000
```

`manual_battle_check.py` melaporkan **persentase frame** di mana dua tangan
terdeteksi bersamaan dan berapa kali tiap pemain terbaca di luar zonanya. Bila
angkanya 0%, skrip menuliskan itu dan menyebutkan penyebab yang perlu diperiksa
(pencahayaan, posisi berdiri, kamera dipakai aplikasi lain) — bukan mengklaim
berhasil.

Uji otomatis berjalan **tanpa kamera**; pipeline battle diuji dengan kamera dan
detektor palsu sehingga pemisahan pemain, stabilizer independen, dan antrean
kunci per pemain benar-benar dieksekusi.

---

## Mode 2 Player Battle — catatan teknis

| Bagian | Berkas | Perilaku |
|---|---|---|
| Deteksi dua tangan | `cv/landmarks.py` (`detect_many`) | `num_hands=2` hanya saat mode battle |
| Pemisahan pemain | `cv/players.py` | urut posisi horizontal; kiri = P1, kanan = P2 |
| Stabilizer per pemain | `cv/pipeline.py` (`stabilizers`) | dua instance independen, latch & cooldown sendiri |
| Antrean kunci | `cv/pipeline.py` (`pop_locks`) | `{1: "A", 2: "D"}`, diambil sekali |
| Mesin permainan | `game/battle.py` | skor/jawaban/riwayat per pemain, anti duplikat per pemain |
| API | `routers/battle.py` | `/api/battle/{start,state,answer,next,timeout,result,reset}` |
| WebSocket | `routers/cv.py` (`/ws/battle`) | status kamera dua pemain + jawaban terkunci |
| Skema DB | `database.py` (`_migrasi_kolom`) | kolom `mode`, `pemain_1/2`, `skor_1/2`, `benar_1/2`, `pemain` |

Rumus poin dipakai bersama kedua mode (`game/engine.py: hitung_poin`), jadi skor
single player dan battle selalu sebanding: **10 poin + bonus kecepatan maks 5**.

Migrasi database berjalan otomatis dan idempoten saat startup — database lama
tetap utuh, tidak perlu menghapus `quiz.db`.

---

## Logo sekolah

Letakkan file logo resmi sebagai `assets/img/logo-sekolah.png` di
`frontend/visitor/` dan `frontend/admin/`. Selama belum ada, tampil monogram
"SMK" berlatar merah Telkom. Lihat `assets/img/README-LOGO.txt` untuk spesifikasi.
