"""Hashing password + JWT + dependency otorisasi admin.

Catatan penting: passlib 1.7.4 tidak kompatibel dengan bcrypt >= 4.1
(membaca bcrypt.__about__ yang sudah dihapus), jadi modul bcrypt dipakai
langsung. bcrypt membatasi input 72 byte -> password di-prehash sha256.
"""
from __future__ import annotations

import base64
import hashlib
import threading
import time
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config

_bearer = HTTPBearer(auto_error=False)


def _prehash(password: str) -> bytes:
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_token(username: str) -> tuple[str, int]:
    now = int(time.time())
    payload = {
        "sub": username,
        "role": "admin",
        "iat": now,
        "exp": now + config.JWT_TTL_SECONDS,
    }
    token = jwt.encode(payload, config.get_secret_key(), algorithm=config.JWT_ALGORITHM)
    return token, config.JWT_TTL_SECONDS


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, config.get_secret_key(), algorithms=[config.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesi login berakhir, silakan login ulang")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token tidak valid")


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    """Dependency untuk semua endpoint admin. Visitor tidak punya token -> 401."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Autentikasi diperlukan",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials)
    if payload.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Akses ditolak")
    return payload


def require_admin_media(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    """Seperti `require_admin`, tetapi juga menerima `?token=` untuk <img>.

    Tag <img> di browser tidak bisa mengirim header Authorization. Endpoint
    berkas galeri karena itu menerima token lewat query string. Token tetap
    diverifikasi dengan aturan yang sama (HS256, role=admin, belum kedaluwarsa).
    """
    token = credentials.credentials if credentials and credentials.credentials else None
    if not token:
        token = request.query_params.get("token")
    if not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Autentikasi diperlukan",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(token)
    if payload.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Akses ditolak")
    return payload


class LoginThrottle:
    """Pembatas percobaan login sederhana (anti brute force, in-memory)."""

    def __init__(self, max_attempts: int = 5, window: int = 300):
        self.max_attempts = max_attempts
        self.window = window
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str) -> list[float]:
        cutoff = time.time() - self.window
        hits = [t for t in self._hits.get(key, []) if t > cutoff]
        self._hits[key] = hits
        return hits

    def check(self, key: str) -> None:
        with self._lock:
            hits = self._prune(key)
            if len(hits) >= self.max_attempts:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "Terlalu banyak percobaan login. Coba lagi beberapa menit lagi.",
                )

    def fail(self, key: str) -> None:
        with self._lock:
            self._prune(key).append(time.time())

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


login_throttle = LoginThrottle()


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"
