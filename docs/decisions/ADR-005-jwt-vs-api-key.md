# ADR-005 — Auth: iki kanal (JWT + X-API-Key)

**Durum:** Accepted
**Tarih:** 2026-05-23
**Sprint:** 4 / W6.1-6.2

## Bağlam
Production'a beta açmadan önce auth gerekli. İki farklı use case:

1. **Beta kullanıcı** (insan) — mobil/web app üzerinden /ask çağırır
2. **B2B partner** (otomasyon) — yargi-mcp gibi servisleri entegre edilen
   müşteri sunucusu

Sektörel pratik:
- OAuth 2.0 full flow → overkill, 1-kişilik backend ekibi
- API key only → kullanıcı identity yok (audit, rate-limit için sub gerek)
- JWT only → B2B partner için sürekli renewal acılı

## Karar
İki kanal **aynı middleware** içinde:

```python
async def authenticate(request, authorization=Header(...), x_api_key=Header(...)) -> Principal:
    if AUTH_ENABLED is False: return Principal(anonymous=True)
    if request.path in PUBLIC_PATHS: return anonymous
    if authorization starts with "Bearer ": JWT decode → Principal(kind="user")
    if x_api_key: lookup API_KEYS_FILE → Principal(kind="api_key")
    raise 401
```

**JWT** (kullanıcı):
- HS256, 24h TTL (refresh akışı yok — beta için yeterli)
- Davet kodu ile issue (`POST /auth/invite/{code}`)
- Gizlilik onayı zorunlu

**X-API-Key** (B2B):
- 32-byte random urlsafe
- `API_KEYS_FILE` JSON, plain (hash değil — geliştirici dosya yetkisi ile koru)
- Rate limit `RATE_LIMIT_ASK_API_KEY=60/min` (kullanıcı limit 10/min)

`api/limiter.py` `_principal_key()` ile **per-principal rate limit** — IP başına
değil, principal başına (NAT arkasında kullanıcılar ayrı kovaya düşer).

## Sonuç
- W6 sonu 29 test green (auth + sanitize + pii + audit)
- Production deploy hazır (W9 invite endpoint + gizlilik onayı)
- B2B partner onboarding: API key + label JSON entry
- Audit log her iki kanal için tutarlı (principal_kind ayrımı)

## Alternatifler
- **Auth0 / Clerk** — vendor lock-in, data residency gereksinimleri ve beta için fazla
- **mTLS** — B2B partner ile sertifika takası operasyonel yük
- **OAuth 2.0 + PKCE** — mobil app için fazla, beta için lüks

## İlgili
- [api/middleware/auth.py](../../adalet-agent/backend/api/middleware/auth.py)
- [api/limiter.py](../../adalet-agent/backend/api/limiter.py)
- [api/routes/auth.py](../../adalet-agent/backend/api/routes/auth.py)
- docs/runbooks/secret-rotation.md
