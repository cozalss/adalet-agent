"""slowapi rate-limiter singleton.

Production hatırlatması: tek-process default in-memory backend; multi-worker
deploy'larda Redis backend gerekli (`storage_uri="redis://..."`). Şu an
1 uvicorn worker → in-memory yeterli.

Env değişkenleri:
  RATE_LIMIT_ASK            = "10/minute" — kullanıcı/IP default
  RATE_LIMIT_ASK_API_KEY    = "60/minute" — B2B API key (daha yüksek)
  RATE_LIMIT_STORAGE_URI    = "memory://" (default) veya "redis://localhost:6379"
"""

from __future__ import annotations

import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

ASK_RATE = os.getenv("RATE_LIMIT_ASK", "10/minute")
ASK_RATE_API_KEY = os.getenv("RATE_LIMIT_ASK_API_KEY", "60/minute")
# Davet kodu kabul — brute-force / kod-enumerasyon koruması. IP başına sıkı:
# meşru kullanıcı bir kez kabul eder; saldırgan kod denemesini sınırla.
INVITE_RATE = os.getenv("RATE_LIMIT_INVITE", "5/hour")
STORAGE_URI = os.getenv("RATE_LIMIT_STORAGE_URI", "memory://")


def _principal_key(request: Request) -> str:
    """Sprint-4 W6.2: principal-aware rate limit key.

    Sıralama:
      1. JWT/API-key bağlanmışsa principal_sub (auth middleware request.state'e koyar)
      2. Yoksa client IP (X-Forwarded-For aware)

    Bu sayede beta kullanıcılar IP NAT arkasında bile ayrı limit kovasına girer;
    B2B API key'leri kendi (genelde daha yüksek) limit'leriyle birlikte gelir.
    """
    sub = getattr(request.state, "principal_sub", None)
    kind = getattr(request.state, "principal_kind", None)
    if sub and kind in {"user", "api_key"}:
        return f"{kind}:{sub}"
    return get_remote_address(request)


def ask_rate_for(key: str) -> str:
    """Sprint-6 fix: principal_kind'a göre dinamik limit string'i.

    slowapi `LimitGroup.__iter__` callable limit_value'yi key_func sonucuyla
    çağırır (signature'da `key` param'ı varsa). `_principal_key` zaten
    "api_key:..." / "user:..." / IP prefix'i üretiyor — burada prefix'e bakıp
    bucket'ı seçiyoruz.

    API key → `ASK_RATE_API_KEY` (default 60/min)
    User/IP → `ASK_RATE` (default 10/min)

    Kullanım: `@limiter.limit(ask_rate_for)` decorator.
    """
    if key.startswith("api_key:"):
        return ASK_RATE_API_KEY
    return ASK_RATE


limiter = Limiter(key_func=_principal_key, storage_uri=STORAGE_URI)


__all__ = ("ASK_RATE", "ASK_RATE_API_KEY", "INVITE_RATE", "ask_rate_for", "limiter")
