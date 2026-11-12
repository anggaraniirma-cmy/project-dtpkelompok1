"""CRUD pertanyaan + statistik dashboard. Semua endpoint WAJIB token admin."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import database
from ..schemas import QuestionPayload
from ..security import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _fetch(conn, qid: int):
    row = conn.execute("SELECT * FROM pertanyaan WHERE id = ?", (qid,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pertanyaan tidak ditemukan")
    return row


@router.get("/stats")
def stats():
    with database.get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) n FROM pertanyaan").fetchone()["n"]
        aktif = conn.execute("SELECT COUNT(*) n FROM pertanyaan WHERE aktif=1").fetchone()["n"]
        kategori = conn.execute(
            "SELECT kategori, COUNT(*) n FROM pertanyaan GROUP BY kategori ORDER BY n DESC"
        ).fetchall()
        sesi = conn.execute(
            "SELECT COUNT(*) n, COALESCE(AVG(skor),0) s FROM sesi_permainan WHERE status='selesai'"
        ).fetchone()
        soal_terjawab = conn.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(benar),0) b FROM jawaban_permainan"
        ).fetchone()
        terbaru = conn.execute(
            "SELECT * FROM pertanyaan ORDER BY updated_at DESC, id DESC LIMIT 5"
        ).fetchall()

    n_jawab = soal_terjawab["n"] or 0
    akurasi = round(100 * soal_terjawab["b"] / n_jawab) if n_jawab else 0
    return {
        "total_pertanyaan": total,
        "pertanyaan_aktif": aktif,
        "total_kategori": len(kategori),
        "kategori": [{"nama": r["kategori"], "jumlah": r["n"]} for r in kategori],
        "total_sesi": sesi["n"],
        "rata_rata_skor": round(sesi["s"] or 0, 1),
        "total_jawaban": n_jawab,
        "akurasi": akurasi,
        "terbaru": [database.row_to_question(r) for r in terbaru],
    }


@router.get("/kategori")
def list_kategori():
    with database.get_conn() as conn:
        rows = conn.execute(
            "SELECT kategori FROM pertanyaan GROUP BY kategori ORDER BY kategori"
        ).fetchall()
    return [r["kategori"] for r in rows]


@router.get("/pertanyaan")
def list_pertanyaan(
    q: Optional[str] = Query(default=None, max_length=100),
    kategori: Optional[str] = Query(default=None, max_length=40),
    aktif: Optional[bool] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    where, params = [], []
    if q:
        where.append("(pertanyaan LIKE ? OR pilihan_a LIKE ? OR pilihan_b LIKE ?"
                     " OR pilihan_c LIKE ? OR pilihan_d LIKE ?)")
        like = f"%{q.strip()}%"
        params += [like] * 5
    if kategori:
        where.append("kategori = ?")
        params.append(kategori)
    if aktif is not None:
        where.append("aktif = ?")
        params.append(int(aktif))

    clause = f" WHERE {' AND '.join(where)}" if where else ""
    with database.get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) n FROM pertanyaan{clause}", params).fetchone()["n"]
        rows = conn.execute(
            f"SELECT * FROM pertanyaan{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
    return {
        "total": total,
        "items": [database.row_to_question(r) for r in rows],
    }


@router.get("/pertanyaan/{qid}")
def get_pertanyaan(qid: int):
    with database.get_conn() as conn:
        return database.row_to_question(_fetch(conn, qid))


@router.post("/pertanyaan", status_code=status.HTTP_201_CREATED)
def create_pertanyaan(payload: QuestionPayload):
    ts = database.now_iso()
    with database.get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO pertanyaan
               (pertanyaan, pilihan_a, pilihan_b, pilihan_c, pilihan_d,
                jawaban, kategori, durasi, aktif, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (payload.pertanyaan, payload.pilihan_a, payload.pilihan_b,
             payload.pilihan_c, payload.pilihan_d, payload.jawaban,
             payload.kategori, payload.durasi, int(payload.aktif), ts, ts),
        )
        row = _fetch(conn, cur.lastrowid)
    return database.row_to_question(row)


@router.put("/pertanyaan/{qid}")
def update_pertanyaan(qid: int, payload: QuestionPayload):
    with database.get_conn() as conn:
        _fetch(conn, qid)
        conn.execute(
            """UPDATE pertanyaan SET pertanyaan=?, pilihan_a=?, pilihan_b=?, pilihan_c=?,
               pilihan_d=?, jawaban=?, kategori=?, durasi=?, aktif=?, updated_at=?
               WHERE id=?""",
            (payload.pertanyaan, payload.pilihan_a, payload.pilihan_b,
             payload.pilihan_c, payload.pilihan_d, payload.jawaban,
             payload.kategori, payload.durasi, int(payload.aktif),
             database.now_iso(), qid),
        )
        row = _fetch(conn, qid)
    return database.row_to_question(row)


@router.delete("/pertanyaan/{qid}", status_code=status.HTTP_200_OK)
def delete_pertanyaan(qid: int):
    with database.get_conn() as conn:
        _fetch(conn, qid)
        # Riwayat jawaban menyimpan pertanyaan_id tanpa FK ketat, jadi aman dihapus.
        conn.execute("UPDATE jawaban_permainan SET pertanyaan_id=NULL WHERE pertanyaan_id=?", (qid,))
        conn.execute("DELETE FROM pertanyaan WHERE id=?", (qid,))
    return {"ok": True, "id": qid}


@router.get("/sesi")
def list_sesi(limit: int = Query(default=20, ge=1, le=100)):
    with database.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM sesi_permainan ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
