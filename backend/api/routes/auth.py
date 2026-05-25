"""Auth onboarding — Sprint-4 W9.4.

POST /auth/invite/{code} — geçerli davet kodu ile JWT token döner.
GET  /auth/me            — current principal info (token verify smoke)

Davet kodu yönetimi:
  INVITE_CODES_FILE=path JSON: {"<code>": {"email": "...", "name": "...", "used": false}}

KVKK: davet kodu kullanılırken kullanıcı consent verir; bu metadata audit log'a yazılır.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.audit import AuditEvent
from api.audit import emit as emit_audit
from api.middleware.auth import Principal, authenticate, issue_token

log = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["auth"])

INVITE_CODES_FILE = os.getenv("INVITE_CODES_FILE", "")


class InviteAcceptRequest(BaseModel):
    """Davet kabul + KVKK consent."""
    kvkk_consent: bool = Field(..., description="KVKK aydınlatma metnini okudum ve onaylıyorum")
    email: str | None = Field(default=None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str | None = Field(default=None, max_length=80)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    sub: str
    role: str


class PrincipalInfo(BaseModel):
    sub: str
    kind: str
    role: str
    anonymous: bool


def _load_invites() -> dict[str, dict[str, object]]:
    if not INVITE_CODES_FILE:
        return {}
    p = Path(INVITE_CODES_FILE)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        log.error("invite_codes_invalid", error=str(exc))
        return {}


def _save_invites(data: dict[str, dict[str, object]]) -> None:
    if not INVITE_CODES_FILE:
        return
    p = Path(INVITE_CODES_FILE)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


@router.post("/invite/{code}", response_model=TokenResponse)
async def accept_invite(code: str, req: InviteAcceptRequest) -> TokenResponse:
    """Davet kodu ile JWT alır. Kod tek kullanımlık."""
    if not req.kvkk_consent:
        raise HTTPException(400, "KVKK onayı şart")

    invites = _load_invites()
    invite = invites.get(code)
    if not invite:
        raise HTTPException(404, "Geçersiz davet kodu")
    if invite.get("used"):
        raise HTTPException(409, "Davet kodu daha önce kullanıldı")

    # Subject oluştur — invite'taki email yoksa request'tekini kullan
    email = invite.get("email") or req.email
    if not email:
        raise HTTPException(400, "email zorunlu (invite veya request body)")

    sub = f"beta:{email}"
    token = issue_token(
        sub, role="beta",
        email=str(email), name=req.name or invite.get("name") or "",
    )

    # Davet'i tek-kullanım olarak işaretle
    invite["used"] = True
    invite["used_at"] = datetime.now(UTC).isoformat()
    invite["consent_given_at"] = datetime.now(UTC).isoformat()
    invites[code] = invite
    _save_invites(invites)

    emit_audit(AuditEvent(
        event="invite_accepted",
        principal=Principal(sub=sub, kind="user", role="beta"),
        domain="auth",
    ))
    log.info("invite_accepted", sub=sub)

    from api.middleware.auth import JWT_TTL_SECONDS
    return TokenResponse(
        access_token=token, expires_in=JWT_TTL_SECONDS,
        sub=sub, role="beta",
    )


@router.get("/me", response_model=PrincipalInfo)
async def me(p: Principal = Depends(authenticate)) -> PrincipalInfo:
    """Token verify + principal echo."""
    if p.anonymous:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="anonymous — Bearer token gerekli",
        )
    return PrincipalInfo(
        sub=p.sub, kind=p.kind, role=p.role, anonymous=p.anonymous,
    )
