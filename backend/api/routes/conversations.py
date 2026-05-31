"""Sohbet geçmişi + dosya endpoint'leri — /me/conversations, /me/files.

Kayıtlı kullanıcının sohbet geçmişi cihazlar-arası senkronlanır. Tarayıcı
localStorage birincil kaynaktır; bu uçlar oturum açan kullanıcıya kalıcılık
sağlar (anonim → 401, geçmiş tarayıcıda kalır).

KVKK (gevşetildi, temel hijyen korunur): saklama anahtarı = owner_sub_hash
(fingerprint(sub)); ham email saklanmaz. Mesaj içeriği backend'in PII-mask'ladığı
haldedir. Her uç owner-scoped (IDOR'a kapalı). DELETE = silme hakkı.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from api.dependencies import require_user
from api.limiter import limiter
from db.repositories.conversations import get_conversation_repo

log = structlog.get_logger()
router = APIRouter(prefix="/me", tags=["me"])

CONV_STORE_PATH = Path(os.getenv("CONV_STORE_FILE", "data/conversations.json"))

# Kötüye-kullanım/DoS sınırları (saklama boyutu).
_MAX_CONTENT = 24000   # mesaj başına karakter
_MAX_MESSAGES = 200    # sohbet başına mesaj
_MAX_TITLE = 200
_MAX_CITATIONS = 30    # mesaj başına atıf


class MessageIn(BaseModel):
    turn_index: int = Field(default=0, ge=0)
    role: Literal["user", "assistant"] = "user"
    content: str = Field(default="", max_length=_MAX_CONTENT)
    domain: str = Field(default="", max_length=40)
    citations: list[dict] = Field(default_factory=list, max_length=_MAX_CITATIONS)
    confidence: float = Field(default=0.0, ge=0.0, le=100.0)


class ConversationIn(BaseModel):
    title: str = Field(default="", max_length=_MAX_TITLE)
    domain: str = Field(default="", max_length=40)
    messages: list[MessageIn] = Field(default_factory=list, max_length=_MAX_MESSAGES)


class ConversationSummary(BaseModel):
    id: str
    title: str = ""
    domain: str = ""
    message_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class FileIn(BaseModel):
    conversation_id: str = Field(default="", max_length=64)
    filename: str = Field(default="", max_length=255)
    ocr_engine: str = Field(default="", max_length=40)
    n_chars: int = Field(default=0, ge=0)
    pii_flag: bool = False

    @field_validator("filename")
    @classmethod
    def _safe_filename(cls, v: str) -> str:
        # Path bileşenlerini at (traversal önlemi) + yalnız görünür ad.
        base = v.replace("\\", "/").split("/")[-1]
        return "".join(ch for ch in base if ch.isprintable()).strip()


_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _check_id(conv_id: str) -> None:
    if not _ID_RE.match(conv_id):
        raise HTTPException(422, "geçersiz sohbet kimliği")


@router.get("/conversations", response_model=list[ConversationSummary])
@limiter.limit("60/minute")
async def list_conversations(
    request: Request,
    q: str | None = None,
    sub_hash: str = Depends(require_user),
) -> list[ConversationSummary]:
    """Kullanıcının sohbet geçmişi (en yeni önce). q ile başlık/metin araması."""
    repo = get_conversation_repo(CONV_STORE_PATH)
    rows = await repo.list_for_owner(sub_hash, q.strip() if q else None)
    return [ConversationSummary(**r) for r in rows]


@router.get("/conversations/{conv_id}")
@limiter.limit("120/minute")
async def get_conversation(
    request: Request,
    conv_id: str,
    sub_hash: str = Depends(require_user),
) -> dict:
    """Tek sohbetin tüm mesajları (geçmişe tıkla → yükle)."""
    _check_id(conv_id)
    repo = get_conversation_repo(CONV_STORE_PATH)
    conv = await repo.get(sub_hash, conv_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sohbet bulunamadı")
    return conv


@router.put("/conversations/{conv_id}", response_model=ConversationSummary)
@limiter.limit("120/minute")
async def upsert_conversation(
    request: Request,
    conv_id: str,
    body: ConversationIn,
    sub_hash: str = Depends(require_user),
) -> ConversationSummary:
    """Sohbeti kaydet/güncelle (her turdan sonra frontend tüm sohbeti gönderir)."""
    _check_id(conv_id)
    repo = get_conversation_repo(CONV_STORE_PATH)
    conv = {
        "id": conv_id,
        "title": body.title,
        "domain": body.domain,
        "messages": [m.model_dump() for m in body.messages],
    }
    ok = await repo.upsert(sub_hash, conv)
    if not ok:
        # Bu conv_id başka bir kullanıcıya ait → sessiz başarı yerine açık 403.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "bu sohbet size ait değil")
    log.info("conversation_saved", sub_hash=sub_hash[:12], n=len(body.messages))
    rows = await repo.list_for_owner(sub_hash)
    match = next((r for r in rows if r["id"] == conv_id), None)
    return ConversationSummary(**(match or {"id": conv_id, "message_count": len(body.messages)}))


@router.delete("/conversations", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def delete_all_conversations(
    request: Request,
    sub_hash: str = Depends(require_user),
) -> None:
    """Tüm sohbet geçmişini sil (KVKK "tüm verilerimi sil" — tek istek, atomik)."""
    repo = get_conversation_repo(CONV_STORE_PATH)
    n = await repo.delete_all(sub_hash)
    log.info("conversations_cleared", sub_hash=sub_hash[:12], n=n)


@router.delete("/conversations/{conv_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("60/minute")
async def delete_conversation(
    request: Request,
    conv_id: str,
    sub_hash: str = Depends(require_user),
) -> None:
    """Sohbeti sil (silme hakkı)."""
    _check_id(conv_id)
    repo = get_conversation_repo(CONV_STORE_PATH)
    await repo.delete(sub_hash, conv_id)
    log.info("conversation_deleted", sub_hash=sub_hash[:12], conv=conv_id[:12])


@router.get("/files")
@limiter.limit("60/minute")
async def list_files(
    request: Request,
    sub_hash: str = Depends(require_user),
) -> list[dict]:
    """"Dosyalarım" — kullanıcının yüklediği belge metadata'sı (metin saklanmaz)."""
    repo = get_conversation_repo(CONV_STORE_PATH)
    return await repo.list_files(sub_hash)


@router.post("/files", status_code=status.HTTP_201_CREATED)
@limiter.limit("60/minute")
async def add_file(
    request: Request,
    body: FileIn,
    sub_hash: str = Depends(require_user),
) -> dict:
    """OCR yükleme metadata kaydı (Dosyalarım panelini besler)."""
    repo = get_conversation_repo(CONV_STORE_PATH)
    await repo.add_file(sub_hash, body.model_dump())
    return {"ok": True}
