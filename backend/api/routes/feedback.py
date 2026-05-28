"""Feedback endpoint — Sprint-4 W9.6.

POST /feedback — kullanıcı verdiği cevap için thumbs up/down + free text.
Audit log'a + opsiyonel Langfuse score'a yazılır.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.audit import AuditEvent
from api.audit import emit as emit_audit
from api.middleware.auth import Principal, authenticate
from api.middleware.sanitize import sanitize_question
from api.pii import fingerprint, mask_pii
from db.repositories.feedback import get_feedback_repo

log = structlog.get_logger()
router = APIRouter(prefix="/feedback", tags=["feedback"])

# Production read-only container'da `data/feedback` yazılamaz — FEEDBACK_LOG_DIR
# env ile named volume mount edilen writable path verilir (örn. `/var/lib/adalet/feedback`).
# Dev'de default `data/feedback` (repo-relative).
FEEDBACK_LOG_PATH = Path(os.getenv("FEEDBACK_LOG_DIR", "data/feedback"))


class FeedbackRequest(BaseModel):
    conversation_id: str = Field(..., min_length=1, max_length=64)
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=1000)
    # Eğer multi-turn ise hangi turn için
    turn_index: int | None = Field(default=None, ge=0)


class FeedbackResponse(BaseModel):
    ok: bool = True
    feedback_id: str


# Backend seçimi repository factory'de: DATABASE_URL varsa Postgres, yoksa JSONL.
# _append_jsonl artık db/repositories/feedback.py'de (FilesystemFeedbackRepo).


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(
    req: FeedbackRequest,
    principal: Principal = Depends(authenticate),
) -> FeedbackResponse:
    """Feedback persist + audit. Comment PII-mask edilir, sanitize edilir.

    IDOR (soft): conversation owner kayıtlıysa ve çağıran sahip değilse 403.
    Owner süresi dolmuşsa (session TTL) doğrulanamaz → geç feedback'i kırmamak
    için izin verilir. Anonim modda no-op.
    """
    if not principal.anonymous:
        from api.session_store import get_store
        try:
            owner = await get_store().get_owner(req.conversation_id)
        except Exception:
            owner = None
        if owner is not None and owner != fingerprint(principal.sub):
            emit_audit(AuditEvent(
                event="feedback_idor_blocked", principal=principal,
                conversation_id=req.conversation_id,
            ))
            raise HTTPException(403, "Bu oturuma feedback verme yetkiniz yok.")

    safe_comment = ""
    if req.comment:
        s = sanitize_question(req.comment)
        if s.blocked:
            raise HTTPException(400, f"yorum içeriği reddedildi: {s.reason}")
        safe_comment = mask_pii(s.cleaned_text).masked_text

    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    # Gizlilik: principal.sub = "beta:email@..." → ham email feedback_id'ye, JSONL'e
    # ve log'a sızmasın. Deterministik fingerprint (gruplanabilir, kimliksiz).
    sub_fp = fingerprint(principal.sub, 12)
    feedback_id = f"fb_{ts}_{sub_fp}"

    # Persist — repository factory backend seçer: DATABASE_URL varsa Postgres
    # (kalıcı + sorgulanabilir), yoksa JSONL dosya (dev/test/CI fallback).
    record = {
        "feedback_id": feedback_id,
        "ts": datetime.now(UTC).isoformat(),
        "principal_kind": principal.kind,
        "principal_sub_hash": sub_fp,
        "conversation_id": req.conversation_id,
        "turn_index": req.turn_index,
        "rating": req.rating,
        "comment_masked": safe_comment,
    }
    repo = get_feedback_repo(FEEDBACK_LOG_PATH)
    await repo.save(record)

    emit_audit(AuditEvent(
        event=f"feedback_{req.rating}",
        principal=principal,
        conversation_id=req.conversation_id,
    ))
    log.info("feedback_received", **record)
    return FeedbackResponse(feedback_id=feedback_id)
