"""Güvenlik başlıkları middleware — production hardening.

Uygulama katmanında güvenlik response header'ları ekler. Reverse proxy
(nginx/Caddy) production'da bunları ekleyebilir; ama doğrudan erişimde veya
proxy-bypass'ta uygulama katmanı son savunma hattıdır.

Başlıklar (web/security.md ECC kuralıyla uyumlu):
  - Strict-Transport-Security  (HSTS — sadece HTTPS'te anlamlı, env ile kapatılabilir)
  - X-Content-Type-Options: nosniff
  - X-Frame-Options: DENY
  - Referrer-Policy: strict-origin-when-cross-origin
  - Permissions-Policy: kamera/mikrofon/konum kapalı
  - X-XSS-Protection: 0  (modern tarayıcılarda CSP tercih; legacy XSS auditor kapalı)
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# HSTS yalnız HTTPS arkasında anlamlı; local HTTP dev'de tarayıcı uyarısı
# yaratmasın diye env ile kontrol (production'da "1").
_HSTS_ENABLED = os.getenv("SECURITY_HSTS_ENABLED", "0").lower() in {"1", "true", "yes"}
_HSTS_VALUE = "max-age=31536000; includeSubDomains"

_STATIC_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "X-XSS-Protection": "0",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Her response'a güvenlik başlıklarını ekler."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        for key, value in _STATIC_HEADERS.items():
            response.headers.setdefault(key, value)
        if _HSTS_ENABLED:
            response.headers.setdefault("Strict-Transport-Security", _HSTS_VALUE)
        return response
