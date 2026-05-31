"""Auth onboarding — Sprint-4 W9.4.

POST /auth/invite/{code} — geçerli davet kodu ile JWT token döner.
GET  /auth/me            — current principal info (token verify smoke)

Davet kodu yönetimi:
  INVITE_CODES_FILE=path JSON: {"<code>": {"email": "...", "name": "...", "used": false}}

Gizlilik: davet kodu kullanılırken kullanıcı veri işleme bilgilendirmesini onaylar;
bu metadata audit log'a yazılır.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi import Path as PathParam  # pathlib.Path ile çakışmasın
from pydantic import AliasChoices, BaseModel, Field

from api.audit import AuditEvent
from api.audit import emit as emit_audit
from api.limiter import INVITE_RATE, limiter
from api.middleware.auth import Principal, authenticate, issue_token
from api.passwords import hash_password, verify_password
from api.pii import fingerprint
from db.repositories.users import get_user_repo, normalize_email

log = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["auth"])

INVITE_CODES_FILE = os.getenv("INVITE_CODES_FILE", "")
USERS_STORE_FILE = Path(os.getenv("USERS_STORE_FILE", "data/users.json"))

_EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
# E-posta/şifre auth rate limit (IP başına brute-force koruması).
_AUTH_RATE = "10/minute"


class InviteAcceptRequest(BaseModel):
    """Davet kabul + gizlilik onayı.

    Backward compatibility: eski istemciler `kvkk_consent` gönderebilir; yeni
    API sözleşmesinde alan adı `privacy_consent`.
    """
    privacy_consent: bool = Field(
        ...,
        validation_alias=AliasChoices("privacy_consent", "kvkk_consent"),
        description="Gizlilik ve veri işleme bilgilendirmesini okudum ve onaylıyorum",
    )
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
    name: str = ""
    email: str = ""


class RegisterRequest(BaseModel):
    email: str = Field(..., pattern=_EMAIL_RE, max_length=120)
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(default="", max_length=80)
    privacy_consent: bool = Field(
        ..., description="Gizlilik ve veri işleme bilgilendirmesini onaylıyorum"
    )


class LoginRequest(BaseModel):
    email: str = Field(..., max_length=120)
    password: str = Field(..., max_length=128)


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


# Davet dosyası load→check→mark→save dizisi atomik olmalı: iki eşzamanlı istek
# aynı kodu kullanmasın (TOCTOU). threading.Lock — to_thread worker'ları arası
# serialize eder, asyncio.Lock'un test-başına-loop cross-loop sorunu olmadan.
_invite_file_lock = threading.Lock()


def _consume_invite(
    code: str, req_email: str | None,
) -> tuple[str, dict[str, object] | None]:
    """Atomik tek-kullanım davet tüketimi (threading.Lock altında).

    Döner: ("ok", invite) | ("not_found", None) | ("used", None) | ("no_email", None).
    Blocking dosya I/O burada (asyncio.to_thread ile çağrılır → event loop bloke olmaz).
    """
    with _invite_file_lock:
        invites = _load_invites()
        invite = invites.get(code)
        if not invite:
            return ("not_found", None)
        if invite.get("used"):
            return ("used", None)
        email = invite.get("email") or req_email
        if not email:
            return ("no_email", None)
        now = datetime.now(UTC).isoformat()
        invite["used"] = True
        invite["used_at"] = now
        invite["consent_given_at"] = now
        invites[code] = invite
        _save_invites(invites)
        return ("ok", invite)


@router.post("/invite/{code}", response_model=TokenResponse)
@limiter.limit(INVITE_RATE)
async def accept_invite(
    request: Request,
    req: InviteAcceptRequest,
    code: str = PathParam(..., min_length=6, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
) -> TokenResponse:
    """Davet kodu ile JWT alır. Kod tek kullanımlık (race-safe).

    Rate-limit (INVITE_RATE, IP başına): kod brute-force/enumerasyonunu sınırlar.
    """
    _ = request  # slowapi key_func request.state/IP'den okur — yan etki için tutulur
    if not req.privacy_consent:
        raise HTTPException(400, "Gizlilik onayı şart")

    # Atomik tüketim + blocking dosya I/O thread pool'da (event loop bloke olmaz).
    result, invite = await asyncio.to_thread(_consume_invite, code, req.email)
    if result == "not_found":
        raise HTTPException(404, "Geçersiz davet kodu")
    if result == "used":
        raise HTTPException(409, "Davet kodu daha önce kullanıldı")
    if result == "no_email":
        raise HTTPException(400, "email zorunlu (invite veya request body)")
    if invite is None:  # mypy narrowing + defensive (result=="ok" → invite var)
        raise HTTPException(500, "davet işlenemedi")

    email = invite.get("email") or req.email
    sub = f"beta:{email}"
    token = issue_token(
        sub, role="beta",
        email=str(email), name=req.name or invite.get("name") or "",
    )

    emit_audit(AuditEvent(
        event="invite_accepted",
        principal=Principal(sub=sub, kind="user", role="beta"),
        domain="auth",
    ))
    # Gizlilik: sub = "beta:email@..." — ham email log'a yazma; fingerprint yeterli.
    log.info("invite_accepted", sub_hash=fingerprint(sub))

    from api.middleware.auth import JWT_TTL_SECONDS
    return TokenResponse(
        access_token=token, expires_in=JWT_TTL_SECONDS,
        sub=sub, role="beta",
    )


def _user_token(email: str, name: str) -> TokenResponse:
    """Kayıtlı kullanıcı için JWT + TokenResponse üret (register/login ortak)."""
    from api.middleware.auth import JWT_TTL_SECONDS
    sub = f"user:{email}"
    token = issue_token(sub, role="user", email=email, name=name or "")
    emit_audit(AuditEvent(
        event="user_authenticated",
        principal=Principal(sub=sub, kind="user", role="user"), domain="auth",
    ))
    # Gizlilik: ham email log'a yazma; fingerprint yeterli.
    log.info("user_authenticated", sub_hash=fingerprint(sub))
    return TokenResponse(
        access_token=token, expires_in=JWT_TTL_SECONDS, sub=sub, role="user",
    )


@router.post("/register", response_model=TokenResponse)
@limiter.limit(_AUTH_RATE)
async def register(request: Request, req: RegisterRequest) -> TokenResponse:
    """E-posta/şifre ile yeni hesap → JWT. Şifre pbkdf2 ile hash'lenir."""
    _ = request  # slowapi key_func IP'den okur
    if not req.privacy_consent:
        raise HTTPException(400, "Gizlilik onayı şart")
    email = normalize_email(req.email)
    repo = get_user_repo(USERS_STORE_FILE)
    created = await repo.create(email, hash_password(req.password), req.name.strip())
    if not created:
        raise HTTPException(409, "Bu e-posta zaten kayıtlı")
    return _user_token(email, req.name.strip())


_DUMMY_HASH: str | None = None


def _dummy_hash() -> str:
    """Zamanlama eşitleyici — kullanıcı yokken de bir pbkdf2 çalıştır (enumeration).

    İlk kullanımda hesaplanır (import maliyeti yok); aynı iterasyon → eşit gecikme.
    """
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("__timing_equalizer__")
    return _DUMMY_HASH


@router.post("/login", response_model=TokenResponse)
@limiter.limit(_AUTH_RATE)
async def login(request: Request, req: LoginRequest) -> TokenResponse:
    """E-posta/şifre doğrulama → JWT. Generic hata + sabit-zaman (enumeration koruması)."""
    _ = request
    email = normalize_email(req.email)
    repo = get_user_repo(USERS_STORE_FILE)
    user = await repo.get(email)
    # Kullanıcı yoksa da pbkdf2 çalıştır → yanıt süresi eşitlenir (timing side-channel).
    stored = str(user.get("password_hash", "")) if user else _dummy_hash()
    ok = verify_password(req.password, stored)
    if user is None or not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="E-posta veya şifre hatalı",
        )
    return _user_token(email, str(user.get("name", "")))


@router.get("/me", response_model=PrincipalInfo)
async def me(p: Principal = Depends(authenticate)) -> PrincipalInfo:
    """Token verify + principal echo (isim/email claim'leriyle)."""
    if p.anonymous:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="anonymous — Bearer token gerekli",
        )
    claims = p.claims or {}
    return PrincipalInfo(
        sub=p.sub, kind=p.kind, role=p.role, anonymous=p.anonymous,
        name=str(claims.get("name", "")), email=str(claims.get("email", "")),
    )
