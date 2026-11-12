"""Model validasi request/response (Pydantic v2)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Letter = Literal["A", "B", "C", "D"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class QuestionPayload(BaseModel):
    pertanyaan: str = Field(min_length=5, max_length=500)
    pilihan_a: str = Field(min_length=1, max_length=200)
    pilihan_b: str = Field(min_length=1, max_length=200)
    pilihan_c: str = Field(min_length=1, max_length=200)
    pilihan_d: str = Field(min_length=1, max_length=200)
    jawaban: Letter
    kategori: str = Field(default="Umum", min_length=1, max_length=40)
    durasi: int = Field(default=30, ge=5, le=180)
    aktif: bool = True

    @field_validator("pertanyaan", "pilihan_a", "pilihan_b", "pilihan_c", "pilihan_d", "kategori")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Tidak boleh kosong")
        return v

    @field_validator("kategori")
    @classmethod
    def _kategori_title(cls, v: str) -> str:
        return " ".join(v.split())[:40]


class AnswerPayload(BaseModel):
    pilihan: Letter


class StartPayload(BaseModel):
    jumlah_soal: int | None = Field(default=None, ge=1, le=20)
