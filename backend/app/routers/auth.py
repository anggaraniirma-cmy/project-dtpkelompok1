"""Endpoint login admin (JWT) + info sesi."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from .. import database
from ..schemas import LoginRequest
from ..security import (
    client_key, create_token, login_throttle, require_admin, verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(payload: LoginRequest, request: Request):
    key = client_key(request)
    login_throttle.check(key)

    with database.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM admin WHERE username = ?", (payload.username.strip(),)
        ).fetchone()

    # Bandingkan tetap lewat verify_password walau user tidak ada? Tidak perlu:
    # pesan error disamakan agar username tidak bisa ditebak.
    if row is None or not verify_password(payload.password, row["password_hash"]):
        login_throttle.fail(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Username atau password salah")

    login_throttle.reset(key)
    token, ttl = create_token(row["username"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": ttl,
        "admin": {"username": row["username"], "nama": row["nama"]},
    }


@router.get("/me")
def me(payload: dict = Depends(require_admin)):
    with database.get_conn() as conn:
        row = conn.execute(
            "SELECT username, nama FROM admin WHERE username = ?", (payload["sub"],)
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Akun tidak ditemukan")
    return {"username": row["username"], "nama": row["nama"]}
