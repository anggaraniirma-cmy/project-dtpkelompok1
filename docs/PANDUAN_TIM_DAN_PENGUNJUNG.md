# SKOMDA Gesture Quiz — Panduan Tim & Penjelasan untuk Pengunjung

> Dokumen ini dibuat untuk **dua pembaca sekaligus**:
> 1. **Anggota kelompok** yang perlu memahami cara kerja aplikasi dan bisa
>    menjawab pertanyaan juri/pengunjung.
> 2. **Pengunjung pameran** yang ingin tahu "ini sebenarnya cara kerjanya
>    bagaimana?" tanpa harus membaca kode.
>
> Dokumen teknis lengkap (untuk presentasi ke juri) ada di
> [`ARSITEKTUR_SKOMDA_GESTURE_QUIZ.md`](./ARSITEKTUR_SKOMDA_GESTURE_QUIZ.md).
> File ini sengaja memakai bahasa sehari-hari.

---

## 1. Satu kalimat: ini aplikasi apa?

**SKOMDA Gesture Quiz adalah kuis pilihan ganda yang dijawab dengan gerakan
tangan di depan kamera** — tanpa keyboard, tanpa menyentuh layar.

Pengunjung berdiri di depan webcam, membentuk jari (1, 2, 3, atau 4 jari),
menahannya sekitar satu detik, lalu jawaban terkunci dan skor bertambah.

Dibuat oleh siswa SMK Telkom Sidoarjo untuk pameran teknologi sekolah.

---

## 2. Penjelasan untuk pengunjung (versi 30 detik)

Kalau ada pengunjung bertanya *"ini pakai AI ya?"*, jawabannya kira-kira:

> "Kamera di depan Anda membaca **21 titik tangan** Anda — ujung jari,
> buku jari, pergelangan. Dari posisi titik-titik itu, komputer menghitung
> jari mana yang terangkat. Satu jari berarti jawaban A, dua jari B, tiga
> jari C, empat jari D. Kalau posisi jari Anda tahan sekitar satu detik,
> jawaban dianggap final.
>
> **Tidak ada foto atau video Anda yang dikirim ke internet.** Kamera hanya
> dibaca di komputer panitia di lokasi ini, dan hanya selama Anda bermain."

Kenapa desainnya begini:
- **Tanpa sentuhan** → layar tidak cepat kotor, antrean lebih cepat.
- **Tanpa instalasi** → pengunjung tidak perlu memasang aplikasi apa pun.
- **Menarik** → orang berhenti karena penasaran melihat tangan orang lain
  bergerak, jadi booth ramai.

### Panduan gerakan (yang ditampilkan di layar)

| Jawaban | Gerakan | Ibu jari |
|---|---|---|
| **A** | Telunjuk terangkat | dilipat |
| **B** | Telunjuk + tengah | dilipat |
| **C** | Telunjuk + tengah + manis | dilipat |
| **D** | Empat jari terbuka | dilipat |

Aturan penting yang sering ditanyakan:
- Harus **tangan kanan** (kamera menampilkan cermin, jadi terasa natural).
- **Ibu jari harus terlipat** — kalau terbuka, sistem menolak dengan pesan
  "Lipat ibu jari".
- Jari harus **berurutan dari telunjuk**. Telunjuk + manis (tanpa tengah)
  tidak dianggap jawaban.
- **Berdiri dekat kamera.** Tangan yang jauh di latar belakang sengaja
  diabaikan sistem.

---

## 3. Cara kerja aplikasi dalam 5 langkah (untuk tim)

Bayangkan ada tiga "petugas" di dalam satu laptop:

| Petugas | Nama teknis | Tugas |
|---|---|---|
| **Petugas kamera & penglihatan** | Python backend, port **8000** | membuka webcam, membaca tangan, mengenali gerakan, memutuskan jawaban |
| **Petugas layar pengunjung** | Visitor Panel, port **8080** | menampilkan pertanyaan, kamera, skor, hasil, sesi foto |
| **Petugas meja panitia** | Admin Panel, port **3000** | mengelola soal, pengaturan, melihat riwayat dan galeri foto |

Alurnya:

```
1. Pengunjung buka halaman (port 8080) → tekan MULAI BERMAIN
2. Backend menyalakan kamera dan mengambil soal dari database
3. Kamera → OpenCV (ambil gambar) → MediaPipe (temukan 21 titik tangan)
4. 21 titik itu diterjemahkan jadi A/B/C/D oleh aturan jari
5. Kalau gerakan bertahan ~1 detik → backend mengunci jawaban,
   menghitung poin, lalu layar menampilkan benar/salah
```

Yang **penting** untuk dijelaskan saat presentasi:

> **Browser tidak pernah mengirim gambar ke server, dan tidak pernah
> memutuskan jawaban.** Kamera dimiliki backend. Browser hanya menampilkan
> video (sebagai gambar) dan menerima hasil yang sudah dihitung server.
> Artinya pengunjung tidak bisa "curang" lewat Inspect Element.

---

## 4. Bagaimana komputer tahu itu jari A, B, C, atau D?

Ini bagian yang paling sering ditanya juri, jadi hafalkan intinya:

Bukan **menghitung jumlah jari**. Setiap jari diperiksa **satu per satu**
dengan dua ukuran:

1. **Panjang relatif** — jarak ujung jari ke pergelangan dibanding jarak
   buku jari ke pergelangan. Jari terlipat akan "menarik" ujungnya mendekat.
2. **Kelurusan** — kalau ruas jari lurus, nilainya mendekati 1; kalau
   tertekuk, nilainya turun tajam.

Kenapa tidak sekadar menghitung jumlah jari? Karena "dua jari terangkat"
bisa berarti telunjuk + tengah (benar = B), atau telunjuk + manis (bukan
jawaban apa pun). Menghitung jumlah saja akan salah.

Lalu kenapa tidak berubah saat tangan miring atau jauh? Karena semua ukuran
dibagi dengan **lebar telapak** tangan itu sendiri. Jadi tangan besar di
dekat kamera dan tangan kecil di jauh dihitung dengan skala yang sama.

**Hold 1 detik**: gerakan harus stabil. Ini mencegah jawaban tidak sengaja
terkirim karena tangan lewat sebentar. Setelah menjawab, pengunjung harus
melepas tangan dulu sebelum bisa menjawab soal berikutnya.

---

## 5. Kenapa tangan orang di belakang tidak ikut menjawab?

Ini pertanyaan yang sangat bagus kalau ditanya, karena jawabannya jujur:

Sistem melakukan **penyaringan berlapis**:
1. **Area permainan** — tangan yang muncul terlalu tinggi (di luar area main)
   diabaikan.
2. **Ukuran tangan** — tangan yang telapaknya terlalu kecil berarti orangnya
   jauh di belakang, jadi ditolak.
3. **Keyakinan model** — deteksi yang ragu-ragu tidak dipakai.
4. **Identitas antar frame** — sistem mengingat tangan siapa yang sedang
   bermain, sehingga orang lain tidak bisa "mengambil alih" posisi pemain.
5. **Zona kiri/kanan** — di mode 2 pemain, Player 1 harus di kiri dan
   Player 2 di kanan. Tangan di zona salah hanya diberi peringatan.

**Kejujuran yang harus disampaikan:** penyaringan ini **tidak 100% sempurna**.
Kalau MediaPipe tetap "melihat" banyak tangan di area yang sama, gangguan
masih mungkin terjadi. Solusi berikutnya adalah *person detection* (mendeteksi
posisi tubuh orang), yang **belum** dibuat di versi ini.

Kalau ditanya "akurasinya berapa persen?", jawaban jujur:
> "Kami belum mengukur angka akurasi formal dengan dataset. Yang sudah kami
> uji adalah 212 pengujian otomatis untuk logikanya, dan pengujian manual
> dengan tangan sungguhan di lokasi. Kami tidak mau menyebut angka yang
> belum kami ukur."

Jawaban seperti ini justru menaikkan kredibilitas di depan juri.

---

## 6. Dua mode permainan

**Single Player** — satu pengunjung, satu kamera, satu tangan. Menjawab
semua soal, lalu mendapat skor, akurasi, dan predikat.

**2 Player Battle** — dua pengunjung berdampingan. Pertanyaan sama, skor
terpisah. Layar kiri untuk Player 1, kanan untuk Player 2. Keduanya memakai
tangan kanan. Pemenang ditentukan dari skor; kalau sama, hasilnya **seri**.

**Jumlah soal bisa dipilih pengunjung: 5, 7, atau 10.** Pilihannya ada di
kartu mode masing-masing dan diingat di browser, jadi panitia tidak perlu
mengatur ulang tiap pengunjung. Kalau bank soal aktif masih sedikit (misalnya
baru 8 soal), tombol 10 tetap bisa ditekan tetapi layar akan memberi tahu
"Bank soal baru 8 soal aktif — permainan memakai 8 soal", jadi pengunjung
tidak bingung.

Soal tidak berganti sampai **kedua** pemain menjawab, atau waktu habis.

---

## 7. Skor dihitung bagaimana?

- Jawaban benar = **10 poin** + bonus kecepatan maksimal **5 poin**.
- Semakin cepat menjawab, bonusnya semakin besar (menurun linear terhadap
  sisa waktu).
- Jawaban salah atau waktu habis = **0 poin**.
- Rumus ini sama untuk Single Player dan Battle, supaya skor kedua mode
  bisa dibandingkan dengan adil.

---

## 8. Foto kenangan (Photo Moment)

Setelah selesai bermain, pengunjung bisa membuat foto kenangan:
- Foto disusun di browser dengan bingkai SKOMDA + skor.
- **SIMPAN FOTO** → file PNG masuk ke perangkat pengunjung. Tidak dikirim
  ke mana-mana.
- **KIRIM KE GALERI PANITIA** → hanya kalau pengunjung **menekan tombol itu
  sendiri**, foto dikirim ke komputer panitia di lokasi (bukan ke internet).

Foto yang dikirim **tidak otomatis tayang** di halaman depan. Panitia harus
menyetujuinya dulu (poin berikutnya). Ini supaya tidak ada foto pengunjung
yang dipajang tanpa izin.

---

## 9. Carousel foto di halaman depan

Halaman depan menampilkan **maksimal 5 foto** pengunjung sebelumnya, berganti
otomatis tiap ~4,5 detik, dengan tombol panah dan titik navigasi. Kalau kursor
diarahkan ke foto, slideshow berhenti supaya pengunjung bisa melihat dengan
tenang.

Untuk panitia — **cara menampilkan foto ke carousel**:
1. Buka Admin Panel (`localhost:3000`), login.
2. Masuk menu **Galeri Foto**.
3. Cari foto yang ingin ditampilkan, tekan **Tampilkan di hero**.
4. Foto itu akan diberi badge **PUBLIK**, dan muncul di carousel pengunjung
   (maksimal 5 foto terbaru).
5. Untuk menariknya lagi: tekan **Sembunyikan dari hero**.

Kalau belum ada foto yang disetujui, halaman depan menampilkan gambar
cadangan dengan tulisan "Belum ada foto yang dipublikasikan" — bukan kotak
kosong atau gambar rusak.

**Catatan penting untuk panitia:** sebelum memajang foto seseorang, pastikan
orang itu sudah setuju fotonya dipajang. Tombol ini ada di tangan panitia,
jadi persetujuan lisan saat pengunjung di booth adalah tanggung jawab kita.

---

## 10. Suara (sound effect)

Ada 12 efek suara lokal: permainan dimulai, pertanyaan muncul, gerakan
terdeteksi, jawaban terkunci, benar, salah, waktu hampir habis, ganti soal,
menang, seri, sesi foto dimulai, dan foto berhasil.

- Semua file suara ada di dalam aplikasi, **tidak butuh internet**.
- **Tidak berbunyi sendiri** sebelum pengunjung menekan MULAI.
- Ada tombol matikan suara (SFX ON/OFF) dan pengatur volume di bagian atas
  halaman.
- Suara tidak menumpuk walau event terjadi berulang cepat.

---

## 11. Keamanan & privasi — versi yang bisa dijelaskan ke pengunjung

Poin yang aman dan benar untuk disampaikan:

- **Video kamera tidak dikirim ke internet.** Tidak ada server luar, tidak
  ada layanan cloud.
- **Tidak ada data pribadi yang diminta** — tanpa nama, tanpa email, tanpa
  nomor telepon. Yang tersimpan hanya skor dan waktu permainan.
- **Foto hanya terkirim kalau pengunjung menekan tombol kirim.**
- **Panel panitia memakai password.** Password disimpan dalam bentuk
  terenkripsi (hash), bukan teks biasa.
- **Akses galeri foto butuh token panitia** — pengunjung tidak bisa melihat
  daftar foto orang lain.

Poin yang **tidak boleh** diklaim berlebihan:
- Jangan bilang "sistem bisa mengabaikan semua tangan orang lain". Belum.
- Jangan bilang "akurasi 99%". Belum diukur.
- Jangan bilang "foto tidak mungkin bocor". Foto tersimpan sebagai file biasa
  di komputer panitia; yang kita jamin adalah tidak dikirim ke internet dan
  tidak tayang tanpa persetujuan.

---

## 12. Kalau ada yang bertanya soal teknologi

| Pertanyaan | Jawaban singkat |
|---|---|
| Bahasa pemrogramannya? | Python untuk backend, HTML/CSS/JavaScript untuk tampilan |
| Library computer vision? | **OpenCV** (membaca kamera) + **MediaPipe** (mendeteksi 21 titik tangan) |
| Itu machine learning? | MediaPipe-nya ya (model siap pakai). Pengenalan A/B/C/D-nya **aturan geometri buatan kami sendiri**, bukan model terlatih |
| Database? | **SQLite**, satu file, tidak perlu server database |
| Kenapa tidak pakai AI generatif? | Karena tugasnya membaca posisi jari, bukan membuat teks/gambar. Model kecil dan aturan jelas lebih cepat dan bisa dijelaskan |
| Jalan di HP? | Tampilannya responsif, tetapi kamera dibaca oleh komputer panitia, jadi permainan berjalan di laptop/PC booth |
| Butuh internet? | **Tidak untuk inti permainan** — kamera, model, database, suara, dan foto semuanya lokal. Satu-satunya elemen online adalah **font tampilan (Google Fonts)**; bila internet mati, permainan tetap jalan penuh, hanya jenis hurufnya berganti ke font bawaan sistem |
| Berapa lama membuatnya? | (isi sesuai kenyataan kelompok) |

---

## 13. Pembagian peran yang bisa disebut saat presentasi

| Bagian | Isi | Berkas utama |
|---|---|---|
| Computer Vision | kamera, 21 titik tangan, aturan jari, stabilitas | `backend/app/cv/` |
| Game Engine | soal, timer, skor, pemenang, anti-jawaban-ganda | `backend/app/game/` |
| API & Database | endpoint, penyimpanan, autentikasi | `backend/app/routers/`, `database.py`, `security.py` |
| Frontend Pengunjung | landing, carousel, layar permainan, foto | `frontend/visitor/` |
| Frontend Panitia | dashboard, soal, galeri, pengaturan | `frontend/admin/` |
| Operasional | launcher, skrip, pengujian | `scripts/`, `tests/`, `start.bat` |

(Sesuaikan dengan pembagian tugas kelompok kalian masing-masing.)

---

## 14. Jawaban untuk 7 pertanyaan yang paling sering muncul

**"Kalau tangannya sakit / pakai perban bagaimana?"**
Gerakan mungkin tidak terbaca sempurna. Panitia bisa mengaktifkan mode jawab
manual (klik) sebagai cadangan, atau pengunjung bisa melewati soal.

**"Kalau kamera mati atau error?"**
Permainan tetap bisa jalan lewat tombol "Kamera bermasalah? Jawab dengan
klik". Kalau panitia ingin permainan **murni** gesture, jalur manual bisa
dimatikan.

**"Kenapa jawaban saya tidak masuk padahal sudah 2 jari?"**
Biasanya karena ibu jari terbuka, tangan terlalu jauh dari kamera, atau
gerakan belum ditahan cukup lama. Ada pesan di bawah kamera yang menjelaskan
alasannya.

**"Kenapa ada orang lain yang tangannya ikut terbaca?"**
Itu batasan yang kami akui. Sistem sudah menyaring berdasarkan area, ukuran,
dan identitas, tetapi belum sempurna. Solusi berikutnya adalah person
detection.

**"Fotonya saya minta ya."**
Silakan, panitia bisa mengunduh dari panel galeri. Foto juga bisa disimpan
sendiri lewat tombol SIMPAN FOTO di akhir permainan.

**"Kenapa jumlah soalnya beda dari yang saya pilih?"**
Kalau memilih 10 tetapi bank soal aktif baru 8, permainan memakai 8 soal dan
layar memberi tahu. Panitia bisa menambah soal lewat panel admin agar
pilihan 10 terpenuhi.

**"Ini bisa dipakai untuk ujian sekolah?"**
Bisa dikembangkan, tetapi versi ini dibuat untuk pameran: satu kamera, satu
sesi aktif, dan belum ada manajemen akun siswa.

---

## 15. Cara menjalankan (untuk anggota kelompok yang bertugas jaga booth)

1. Klik dua kali **`start.bat`**.
2. Tunggu sampai muncul tiga alamat:
   - Backend `http://localhost:8000`
   - Admin `http://localhost:3000`
   - Pengunjung `http://localhost:8080`
3. Buka `http://localhost:8080` di browser, biarkan fullscreen.
4. Login admin di `http://localhost:3000` dengan akun panitia.
5. **Sebelum pameran:** ganti password default, dan putuskan apakah jawaban
   manual diizinkan.
6. **Menghentikan:** `Ctrl+C` di jendela hitam, atau klik `stop.bat`.

Kalau kamera tidak terdeteksi: tutup aplikasi lain yang memakai kamera
(Zoom, Teams, Camera), lalu jalankan ulang.

---

## 16. Hal yang harus dihindari saat menjelaskan

- ❌ "Ini AI yang belajar sendiri." → ✅ "MediaPipe mendeteksi titik tangan;
  aturan pengenalan jawabannya kami susun sendiri."
- ❌ "Akurasinya 99%." → ✅ "Kami belum mengukur angka formal; yang ada 212
  pengujian otomatis dan uji manual."
- ❌ "Tidak mungkin salah deteksi." → ✅ "Ada penyaringan berlapis, tapi
  keramaian masih bisa mengganggu."
- ❌ "Fotonya aman 100%." → ✅ "Foto tidak dikirim ke internet dan tidak
  tayang tanpa persetujuan panitia."

Cara paling meyakinkan saat presentasi: **tunjukkan aplikasinya hidup**, lalu
sebutkan satu keterbatasan dengan jujur. Juri biasanya lebih percaya pada tim
yang tahu batas karyanya sendiri.
