"""Endpoints galeri foto dokumentasi.

Publik (tanpa login) hanya satu arah: pengunjung MENGIRIM foto yang sudah
mereka lihat dan setujui pada tombol "Kirim ke Galeri Panitia".

Semua pembacaan (daftar, pratinjau, unduh, hapus) ada di `/api/admin/galeri`
dan wajib token panitia — lihat routers/admin.py.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from .. import config, galeri

log = logging.getLogger("skomda.galeri")
router = APIRouter(prefix="/api/galeri", tags=["galeri"])

FOTO_UPLOAD_AKTIF = True   # dimatikan lewat env SKOMDA_ALLOW_FOTO_UPLOAD=0


def _aktif() -> bool:
    import os
    return os.getenv("SKOMDA_ALLOW_FOTO_UPLOAD", "1") == "1"


@router.post("/foto", status_code=status.HTTP_201_CREATED)
async def unggah_foto(
    file: UploadFile = File(...),
    mode: str = Form(default="single"),
    sesi_id: Optional[str] = Form(default=None),
    pemain_1: Optional[str] = Form(default=None),
    pemain_2: Optional[str] = Form(default=None),
    skor_1: Optional[int] = Form(default=None),
    skor_2: Optional[int] = Form(default=None),
    pemenang: Optional[str] = Form(default=None),
):
    """Simpan satu foto dokumentasi dari pengunjung.

    Foto hanya sampai ke sini bila pengunjung menekan tombol kirim secara sadar;
    backend tidak pernah mengambil foto sendiri.
    """
    if not _aktif():
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Pengiriman foto ke galeri dinonaktifkan panitia.",
        )

    # Baca dengan batas ukuran: jangan pernah memuat berkas raksasa ke memori.
    batas = config.FOTO_MAX_BYTES
    data = await file.read(batas + 1)
    if len(data) > batas:
        raise HTTPException(
            413,  # Content Too Large (nama konstanta berbeda antar versi Starlette)
            f"Ukuran foto melebihi batas {batas / (1024 * 1024):.0f} MB.",
        )

    try:
        hasil = galeri.simpan_foto(
            data,
            mode=mode,
            sesi_id=(sesi_id or None),
            pemain_1=(pemain_1 or None),
            pemain_2=(pemain_2 or None),
            skor_1=skor_1,
            skor_2=skor_2,
            pemenang=(pemenang or None),
        )
    except galeri.GaleriError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    except OSError as exc:
        log.exception("gagal menulis foto")
        raise HTTPException(
            status.HTTP_507_INSUFFICIENT_STORAGE,
            f"Penyimpanan foto gagal: {exc}",
        )

    log.info("foto galeri tersimpan: %s (%s)", hasil["nama_file"], hasil["mode"])
    return {"ok": True, **hasil}


# ------------------------------------------------------- promosi (publik) ---
# Endpoint baca publik HANYA untuk carousel hero. Batasannya:
#   * daftar maksimum 5 foto, hanya yang `publik = 1` (disetujui panitia);
#   * berkas disajikan satu per satu lewat nama yang divalidasi ketat;
#   * tidak ada token admin, tidak ada endpoint daftar-seluruh-galeri.
@router.get("/publik")
def daftar_publik():
    """Daftar maksimal 5 foto promosi yang sudah disetujui panitia."""
    return galeri.daftar_publik()


@router.get("/publik/{nama_file}")
def berkas_publik(nama_file: str, thumb: bool = False):
    """Sajikan satu berkas foto promosi.

    Foto hanya keluar bila statusnya `publik = 1`; nama file tetap diperiksa
    regex + resolusi path di `galeri.ambil_file` (anti path traversal).
    """
    with galeri.database.get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM galeri_foto WHERE nama_file = ? AND publik = 1",
            (nama_file,),
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Foto tidak tersedia")

    path = galeri.ambil_file(nama_file, thumb=thumb)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Foto tidak tersedia")

    media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(
        path,
        media_type=media,
        headers={"Cache-Control": "public, max-age=300"},
    )
