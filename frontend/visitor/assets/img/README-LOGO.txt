SLOT LOGO RESMI SMK TELKOM SIDOARJO
===================================

Folder ini sengaja dikosongkan. Selama file logo belum ada, kedua panel
menampilkan monogram "SMK" berlatar merah Telkom sebagai penanda tempat
(bukan logo karangan).

CARA MEMASANG LOGO ASLI
-----------------------
1. Simpan file logo resmi sebagai:

     frontend/visitor/assets/img/logo-sekolah.png
     frontend/admin/assets/img/logo-sekolah.png

   (dua salinan file yang sama, karena admin dan visitor adalah frontend
   terpisah dan tidak boleh saling bergantung)

2. Muat ulang halaman. Tidak ada kode yang perlu diubah — HTML sudah
   menunjuk ke nama file tersebut.

SPESIFIKASI YANG DISARANKAN
---------------------------
- Format   : PNG dengan latar transparan (atau putih bersih)
- Ukuran   : 512 x 512 piksel (ditampilkan 38-44 px, jadi harus tajam)
- Rasio    : 1:1 (kotak). Logo non-kotak tetap aman karena CSS memakai
             object-fit: contain, tetapi akan ada ruang kosong di sisi.
- Berat    : di bawah 200 KB

BILA LOGO BERUBAH NAMA
----------------------
Cari atribut src="assets/img/logo-sekolah.png" di:
  - frontend/visitor/index.html  (header + footer)
  - frontend/admin/index.html    (layar login + sidebar)
lalu sesuaikan namanya. Atribut onerror akan otomatis jatuh ke monogram
"SMK" bila file hilang, sehingga tampilan tidak pernah rusak.
