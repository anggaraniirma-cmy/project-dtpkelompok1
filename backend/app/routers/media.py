"""Endpoint media publik terbatas untuk halaman pengunjung.

Hanya SATU berkas yang boleh dibaca di sini: foto dokumentasi pameran
(`fotocontoh.png`) yang dipakai sebagai visual hero di landing page.

Alasannya:
  * berkas aslinya tinggal di `backend/data/foto/` yang di-.gitignore karena
    berisi foto pengunjung — jadi tidak boleh disalin ke folder frontend;
  * foto-foto galeri pengunjung TIDAK boleh terbaca publik, karena itu route
    ini tidak menerima nama berkas dari klien sama sekali (nama dipatok),
    sehingga tidak bisa dipakai untuk menebak nama foto galeri.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from .. import config

router = APIRouter(prefix="/api/media", tags=["media"])

# Nama yang diizinkan, dipetakan ke berkas nyata. Route tidak pernah menerima
# nama dari klien -> tidak ada permukaan untuk membaca foto galeri.
_MEDIA = {
    "fotocontoh.png": "fotocontoh.png",
}


@router.get("/{nama}")
def media(nama: str):
    """Sajikan satu berkas media publik (read-only)."""
    berkas_nama = _MEDIA.get(nama)
    if berkas_nama is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media tidak tersedia")

    folder = config.FOTO_DIR.resolve()
    path = (folder / berkas_nama).resolve()
    try:
        path.relative_to(folder)          # pertahanan berlapis
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media tidak tersedia")
    if not path.is_file():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Berkas foto belum tersedia di backend/data/foto/",
        )

    tipe = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return Response(
        content=path.read_bytes(),
        media_type=tipe,
        headers={"Cache-Control": "public, max-age=300"},
    )
