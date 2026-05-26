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
from api.pii import mask_pii

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


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(
    req: FeedbackRequest,
    principal: Principal = Depends(authenticate),
) -> FeedbackResponse:
    """Feedback persist + audit. Comment PII-mask edilir, sanitize edilir."""
    safe_comment = ""
    if req.comment:
        s = sanitize_question(req.comment)
        if s.blocked:
            raise HTTPException(400, f"yorum içeriği reddedildi: {s.reason}")
        safe_comment = mask_pii(s.cleaned_text).masked_text

    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    feedback_id = f"fb_{ts}_{principal.sub[:12]}"

    # Persist — production'da SQLite veya append-only log
    FEEDBACK_LOG_PATH.mkdir(parents=True, exist_ok=True)
    record = {
        "feedback_id": feedback_id,
        "ts": datetime.now(UTC).isoformat(),
        "principal_kind": principal.kind,
        "principal_sub": principal.sub,
        "conversation_id": req.conversation_id,
        "turn_index": req.turn_index,
        "rating": req.rating,
        "comment_masked": safe_comment,
    }
    import json
    log_path = FEEDBACK_LOG_PATH / f"feedback_{datetime.now(UTC).strftime('%Y%m%d')}.jsonl"
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    emit_audit(AuditEvent(
        event=f"feedback_{req.rating}",
        principal=principal,
        conversation_id=req.conversation_id,
    ))
    log.info("feedback_received", **record)
    return FeedbackResponse(feedback_id=feedback_id)
