"""Galeri dokumentasi foto hasil Photo Moment.

Dua sisi:

  * PENGUNJUNG (`routers/galeri.py`, publik) — boleh MENGIRIM satu foto yang
    sudah mereka lihat & setujui. Tidak bisa membaca, mendaftar, atau menghapus
    foto siapa pun.
  * PANITIA (`routers/admin.py`, wajib token) — bisa melihat daftar, mengunduh
    file, dan menghapus.

Penyimpanan: file PNG di `config.FOTO_DIR`, metadata di tabel `galeri_foto`.
Nama file dibuat server-side dari timestamp + token acak, sehingga nama kiriman
pengunjung tidak pernah dipakai langsung (mencegah path traversal & tabrakan).

Batasan yang ditegakkan di sini:
  * hanya PNG/JPEG (diperiksa dari magic bytes, BUKAN dari nama file);
  * ukuran maksimum `config.FOTO_MAX_BYTES`;
  * dimensi maksimum 4000x4000 (menolak berkas raksasa);
  * jumlah simpanan dibatasi `MAKS_FOTO` dengan pembersihan terlama.
"""
from __future__ import annotations

import re
import secrets
import time
from pathlib import Path
from typing import Optional

from . import config, database

MAKS_FOTO = 500          # jumlah foto yang disimpan; terlama dibuang otomatis
MAKS_DIMENSI = 4000      # piksel sisi terpanjang
_NAMA_SAH = re.compile(r"^[0-9a-zA-Z_-]{6,80}\.(png|jpg)$")


class GaleriError(ValueError):
    """Kesalahan yang aman ditampilkan ke pengguna."""


def foto_dir() -> Path:
    d = config.FOTO_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def thumb_dir() -> Path:
    d = config.FOTO_DIR / "thumb"
    d.mkdir(parents=True, exist_ok=True)
    return d


THUMB_LEBAR = 520


def buat_thumb(path: Path) -> Optional[Path]:
    """Buat (sekali) versi kecil untuk grid galeri.

    Foto asli 1200x900 bisa 800 KB; grid dengan 60 foto akan memuat puluhan
    megabyte. Thumbnail ~520px JPEG membuat galeri terbuka cepat. Hasil
    disimpan berdampingan agar tidak dihitung ulang tiap permintaan.

    Bila Pillow tidak tersedia, kembalikan None dan pemanggil memakai file asli
    (degradasi yang aman, bukan error).
    """
    tujuan = thumb_dir() / (path.stem + ".jpg")
    if tujuan.is_file() and tujuan.stat().st_mtime >= path.stat().st_mtime:
        return tujuan
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((THUMB_LEBAR, THUMB_LEBAR))
            im.save(tujuan, "JPEG", quality=80, optimize=True)
        return tujuan
    except Exception:
        return None


def _deteksi_format(data: bytes) -> Optional[str]:
    """Tentukan format dari magic bytes. Nama file TIDAK dipercaya."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    return None


def _ukuran_gambar(data: bytes) -> Optional[tuple[int, int]]:
    """Baca lebar x tinggi tanpa Pillow (cukup untuk PNG & JPEG)."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            w = int.from_bytes(data[16:20], "big")
            h = int.from_bytes(data[20:24], "big")
            return w, h
        if data[:3] == b"\xff\xd8\xff":
            i = 2
            n = len(data)
            while i < n - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                seg_len = int.from_bytes(data[i + 2:i + 4], "big")
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                              0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h = int.from_bytes(data[i + 5:i + 7], "big")
                    w = int.from_bytes(data[i + 7:i + 9], "big")
                    return w, h
                i += 2 + max(seg_len, 2)
    except (IndexError, ValueError):
        return None
    return None


def simpan_foto(
    data: bytes,
    *,
    mode: str = "single",
    sesi_id: Optional[str] = None,
    pemain_1: Optional[str] = None,
    pemain_2: Optional[str] = None,
    skor_1: Optional[int] = None,
    skor_2: Optional[int] = None,
    pemenang: Optional[str] = None,
) -> dict:
    """Validasi lalu simpan satu foto. Melempar GaleriError bila tidak sah."""
    if not data:
        raise GaleriError("Berkas foto kosong.")
    if len(data) > config.FOTO_MAX_BYTES:
        mb = config.FOTO_MAX_BYTES / (1024 * 1024)
        raise GaleriError(f"Ukuran foto melebihi batas {mb:.0f} MB.")

    fmt = _deteksi_format(data)
    if fmt is None:
        raise GaleriError("Berkas bukan PNG atau JPEG yang sah.")

    dim = _ukuran_gambar(data)
    if dim is not None and max(dim) > MAKS_DIMENSI:
        raise GaleriError(
            f"Dimensi foto terlalu besar ({dim[0]}x{dim[1]}), maksimum {MAKS_DIMENSI}px."
        )

    mode = (mode or "single").lower()
    if mode not in ("single", "battle"):
        mode = "single"

    # Nama file: timestamp + token acak, TIDAK memakai nama kiriman klien.
    nama = f"{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(4)}.{fmt}"
    if not _NAMA_SAH.match(nama):
        raise GaleriError("Nama berkas tidak valid.")

    folder = foto_dir()
    path = folder / nama
    # Tulis ke file sementara lalu rename: foto setengah jadi tidak pernah
    # muncul di galeri walaupun proses terhenti.
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)

    ts = database.now_iso()
    with database.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO galeri_foto (nama_file, sesi_id, mode, pemain_1, pemain_2,"
            " skor_1, skor_2, pemenang, ukuran, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (nama, sesi_id, mode, pemain_1, pemain_2, skor_1, skor_2,
             pemenang, len(data), ts),
        )
        foto_id = cur.lastrowid
        total = conn.execute("SELECT COUNT(*) n FROM galeri_foto").fetchone()["n"]

    _pangkas(folder)

    return {
        "id": foto_id,
        "nama_file": nama,
        "mode": mode,
        "ukuran": len(data),
        "created_at": ts,
        "total": total,
    }


def _pangkas(folder: Path) -> None:
    """Buang foto terlama bila melebihi MAKS_FOTO (file + baris database)."""
    with database.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, nama_file FROM galeri_foto ORDER BY created_at DESC, id DESC"
        ).fetchall()
        berlebih = rows[MAKS_FOTO:]
        for row in berlebih:
            conn.execute("DELETE FROM galeri_foto WHERE id=?", (row["id"],))
    for row in berlebih:
        try:
            (folder / row["nama_file"]).unlink(missing_ok=True)
        except OSError:
            pass


def daftar(limit: int = 60, offset: int = 0, mode: Optional[str] = None) -> dict:
    where, params = [], []
    if mode in ("single", "battle"):
        where.append("mode = ?")
        params.append(mode)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    with database.get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) n FROM galeri_foto{clause}", params
        ).fetchone()["n"]
        rows = conn.execute(
            f"SELECT * FROM galeri_foto{clause} ORDER BY created_at DESC, id DESC"
            " LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
    return {"total": total, "items": [dict(r) for r in rows]}


def ambil_file(nama_file: str, thumb: bool = False) -> Optional[Path]:
    """Path file foto (atau thumbnail-nya), None bila tidak ada / nama tidak sah."""
    if not _NAMA_SAH.match(nama_file or ""):
        return None
    path = foto_dir() / nama_file
    if not path.is_file():
        return None
    # Pastikan hasil resolve tetap di dalam folder foto (anti symlink escape).
    try:
        path.resolve().relative_to(foto_dir().resolve())
    except ValueError:
        return None
    if thumb:
        kecil = buat_thumb(path)
        if kecil is not None:
            return kecil
    return path


def hapus(foto_id: int) -> bool:
    with database.get_conn() as conn:
        row = conn.execute(
            "SELECT nama_file FROM galeri_foto WHERE id=?", (foto_id,)
        ).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM galeri_foto WHERE id=?", (foto_id,))
    try:
        (foto_dir() / row["nama_file"]).unlink(missing_ok=True)
    except OSError:
        pass
    return True
