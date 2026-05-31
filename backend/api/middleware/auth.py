"""JWT + API key authentication — Sprint-4 W6.1/W6.2.

İki kanal:
  1. Authorization: Bearer <JWT>           → kullanıcı (beta tester) flow
  2. X-API-Key: <key>                      → B2B servisler için shadow flow

Default: AUTH_ENABLED=0 → her istek `Principal(anonymous=True)`. Production'da
ENV=1 zorunlu; geliştirici PUBLIC_PATHS env'i ile bazı path'leri açık tutar
(örn. /health, /docs).

Tasarım kararları:
- JWT için PyJWT (lightweight, no crypto-suite dep).
- Secret rotation: `JWT_SECRET` env değişikliği yeniden başlatma gerektirir.
- Token TTL'i default 24h; refresh token akışı şu an yok (beta için yeterli).
- API key sabit liste (`API_KEYS_FILE=path` JSON: {"key_or_sha256": "label"}).
  Stored key SHA-256 hex ise hash modu (önerilen — dosya sızsa ham key açığa
  çıkmaz); plaintext de desteklenir (geriye uyum, deprecation uyarısı). Hash
  üret: `auth.hash_api_key("<ham-key>")`.
- Rate-limit per-key entegrasyon W6.2'de api/limiter.py'ye ekleniyor.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt
import structlog
from fastapi import Header, HTTPException, Request, status

log = structlog.get_logger()


# --- ENV config ------------------------------------------------------------

AUTH_ENABLED = os.getenv("AUTH_ENABLED", "0").lower() in {"1", "true", "yes"}
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
# alg-confusion koruması: yalnız simetrik HMAC algoritmaları kabul (asla "none"
# veya asimetrik). Geçersiz konfig → güvenli default'a düş + hata logla (fail-closed).
_ALLOWED_JWT_ALGS = {"HS256", "HS384", "HS512"}
if JWT_ALGORITHM not in _ALLOWED_JWT_ALGS:
    log.error("jwt_algorithm_invalid", configured=JWT_ALGORITHM, fallback="HS256")
    JWT_ALGORITHM = "HS256"
JWT_TTL_SECONDS = int(os.getenv("JWT_TTL_SECONDS", "86400"))  # 24h
JWT_ISSUER = os.getenv("JWT_ISSUER", "adalet-agent")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "adalet-agent-api")

# Public path prefix'leri — auth required değil
_DEFAULT_PUBLIC = "/health,/docs,/openapi.json,/redoc"
PUBLIC_PATH_PREFIXES = tuple(
    p.strip() for p in os.getenv("PUBLIC_PATHS", _DEFAULT_PUBLIC).split(",") if p.strip()
)

API_KEYS_FILE = os.getenv("API_KEYS_FILE", "")


@dataclass(frozen=True)
class Principal:
    """Kimliği temsil eder. `anonymous` flag'i auth-disabled durumda True."""
    sub: str
    kind: str  # "user" | "api_key" | "anonymous"
    anonymous: bool = False
    role: str = "beta"
    claims: dict[str, Any] | None = None


def hash_api_key(raw_key: str) -> str:
    """Ham API key → SHA-256 hex. API_KEYS_FILE'a bu hash yazılır (güvenli mod)."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _load_api_keys() -> dict[str, str]:
    """API_KEYS_FILE → {key: label} dict. Yoksa boş."""
    if not API_KEYS_FILE:
        return {}
    p = Path(API_KEYS_FILE)
    if not p.exists():
        log.warning("api_keys_file_missing", path=API_KEYS_FILE)
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError("API_KEYS_FILE must contain a JSON object")
        return {str(k): str(v) for k, v in data.items()}
    except (json.JSONDecodeError, OSError, TypeError) as exc:
        log.error("api_keys_file_invalid", error=str(exc))
        return {}


_API_KEY_CACHE: dict[str, str] | None = None


def get_api_keys() -> dict[str, str]:
    """Aktif API key haritası (sync, cache'li) — auth hot-path.

    Cache boşsa SENKRON dosyadan yükler (dev/test fallback). DB modunda cache
    boot'ta `refresh_api_key_cache()` ile DB'den doldurulur (hot-path'te async
    sorgu YOK).
    """
    global _API_KEY_CACHE
    if _API_KEY_CACHE is None:
        _API_KEY_CACHE = _load_api_keys()
    return _API_KEY_CACHE


async def refresh_api_key_cache() -> None:
    """Cache'i repo'dan (DB veya dosya) yeniden yükle — boot'ta + revoke sonrası.

    DATABASE_URL set ise ApiKey tablosundan aktif key'ler; değilse JSON dosya.
    Lifespan startup'ta çağrılır; cache authoritative olur.
    """
    global _API_KEY_CACHE
    from db.repositories.api_key import get_api_key_repo
    repo = get_api_key_repo(API_KEYS_FILE)
    _API_KEY_CACHE = await repo.list_active()
    log.info("api_key_cache_refreshed", backend=repo.name, n_keys=len(_API_KEY_CACHE))


def reset_api_key_cache() -> None:
    """Test yardımcısı — cache invalidate."""
    global _API_KEY_CACHE
    _API_KEY_CACHE = None


# SHA-256 hex = 64 karakterlik [0-9a-f]. Stored key bu formatta ise hash kabul
# edilir (güvenli mod); değilse plaintext (geriye uyum + deprecation uyarısı).
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_plaintext_key_warned = False


def _match_api_key(provided: str, keys: dict[str, str]) -> str | None:
    """Sabit-zaman API key eşleştirme — timing attack + at-rest sızıntı koruması.

    Stored key SHA-256 hex ise sağlanan key hash'lenip karşılaştırılır → dosya
    sızsa bile ham key açığa çıkmaz (C2). Plaintext stored key geriye uyum için
    desteklenir ama bir kez deprecation uyarısı verilir — production'da hash önerilir.

    Her iki yolda da `hmac.compare_digest` ile sabit-zaman; erken return YOK
    (eşleşme pozisyonunu sızdırmamak için tüm kayıtlar gezilir).
    """
    global _plaintext_key_warned
    provided_b = provided.encode("utf-8")
    provided_hash = hashlib.sha256(provided_b).hexdigest().encode("utf-8")
    matched: str | None = None
    for key, label in keys.items():
        if _SHA256_HEX_RE.match(key):
            # Güvenli mod: stored=hash, provided'ı hash'le karşılaştır
            if hmac.compare_digest(key.encode("utf-8"), provided_hash):
                matched = label
        else:
            # Geriye uyum: plaintext stored key (deprecation)
            if not _plaintext_key_warned:
                _plaintext_key_warned = True
                log.warning(
                    "api_key_plaintext_deprecated",
                    hint="API_KEYS_FILE plaintext key içeriyor; SHA-256 hash kullan "
                         "(hashlib.sha256(key).hexdigest()). Dosya sızarsa ham key açığa çıkar.",
                )
            if hmac.compare_digest(key.encode("utf-8"), provided_b):
                matched = label
    return matched


# --- JWT helpers -----------------------------------------------------------

def issue_token(sub: str, role: str = "beta", **extra_claims: Any) -> str:
    """Sub + role + extra claims içeren JWT üret."""
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET ENV ayarlanmadı")
    import time
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "sub": sub,
        "role": role,
        "iat": now,
        "exp": now + JWT_TTL_SECONDS,
        **extra_claims,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """JWT decode + verify; geçersizse HTTPException 401."""
    if not JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET ayarlanmadı (server config hatası)",
        )
    try:
        return jwt.decode(
            token, JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
            issuer=JWT_ISSUER,
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token süresi doldu",
        ) from exc
    except jwt.InvalidTokenError as exc:
        # İç JWT hata detayını (imza/audience/issuer) istemciye SIZDIRMA — token
        # forgery'ye oracle olur. Spesifik sebebi yalnız sunucu log'una yaz.
        log.warning("jwt_invalid", reason=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="geçersiz veya süresi dolmuş token",
        ) from exc


# --- FastAPI dependency ----------------------------------------------------

def _is_public(path: str) -> bool:
    if not PUBLIC_PATH_PREFIXES:
        return False
    return path in PUBLIC_PATH_PREFIXES or path.startswith(PUBLIC_PATH_PREFIXES)


async def authenticate(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> Principal:
    """Bearer JWT veya X-API-Key header'larından Principal üretir.

    Davranış:
      - AUTH_ENABLED=0 → her zaman anonymous=True (CI/test/local-dev).
      - PUBLIC path → anonymous=True (auth skip).
      - JWT geçerli → kind=user, sub=token.sub
      - API key match → kind=api_key, sub=label
      - Hiçbiri yok/yanlış → 401 (production'da).
    """
    if not AUTH_ENABLED:
        return Principal(sub="dev", kind="anonymous", anonymous=True)

    if _is_public(request.url.path):
        return Principal(sub="public", kind="anonymous", anonymous=True)

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        claims = decode_token(token)
        request.state.principal_kind = "user"
        request.state.principal_sub = claims.get("sub", "?")
        return Principal(
            sub=str(claims.get("sub", "?")),
            kind="user",
            role=str(claims.get("role", "beta")),
            claims=claims,
        )

    if x_api_key:
        keys = get_api_keys()
        label = _match_api_key(x_api_key, keys)
        if not label:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="geçersiz API key",
            )
        request.state.principal_kind = "api_key"
        request.state.principal_sub = label
        return Principal(sub=label, kind="api_key", role="service")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authorization (Bearer) veya X-API-Key zorunlu",
        headers={"WWW-Authenticate": "Bearer"},
    )


__all__ = (
    "AUTH_ENABLED",
    "Principal",
    "authenticate",
    "decode_token",
    "get_api_keys",
    "hash_api_key",
    "issue_token",
    "refresh_api_key_cache",
    "reset_api_key_cache",
)
