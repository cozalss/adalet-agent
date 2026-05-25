# Sprint-4 Hafta 6 — Production Security Part 1 Changelog

Önceki: `eval/runs/W5_changes.md`

## Hedef
JWT + API key auth middleware; runtime prompt-injection filter; PII mask;
audit log; rate-limit per-principal.

## Değişiklikler

### W6.1 — JWT auth middleware
- Yeni `api/middleware/auth.py`:
  - `Principal` (sub/kind/role/anonymous/claims)
  - `issue_token()` / `decode_token()` (PyJWT HS256)
  - `authenticate()` FastAPI dependency
  - `AUTH_ENABLED` env (default 0 → her istek `anonymous=True`)
  - `PUBLIC_PATHS` env (default `/health,/docs,/openapi.json,/redoc`)
  - `JWT_SECRET`, `JWT_TTL_SECONDS=86400`, `JWT_ISSUER`, `JWT_AUDIENCE`
- Bağımlılık: `pyjwt>=2.13` eklendi
- `api/routes/ask.py`:
  - `/ask`, `/ask/stream`, `/ask/session/{id}` üçü de `Depends(authenticate)`

### W6.2 — API key shadow flow + per-principal rate limit
- `api/middleware/auth.py`:
  - `X-API-Key` header desteği
  - `API_KEYS_FILE` JSON `{key: label}` dosyası
  - `get_api_keys()` lazy cache, `reset_api_key_cache()` test yardımcısı
- `api/limiter.py`:
  - `_principal_key()` — request.state.principal_sub varsa onu key olarak kullan,
    yoksa IP (X-Forwarded-For aware)
  - `RATE_LIMIT_ASK_API_KEY` (default 60/min) — B2B servis daha yüksek limit
  - Auth middleware request.state'e `principal_sub` ve `principal_kind` koyuyor

### W6.3 — Runtime prompt-inj filter
- Yeni `api/middleware/sanitize.py`:
  - `SanitizeResult` (blocked / reason / cleaned_text / matched_hard / matched_soft)
  - Hard patterns (jailbreak/system-leak): 9 regex (TR + EN)
  - Soft patterns (system-role etiketleri): `[SYSTEM]`, `[INST]`, `<|im_start|>`,
    `### SYSTEM`, `assistant:` — temizlenir, blok değil
  - `SANITIZE_ENABLED` (default 1), `SANITIZE_HARD_BLOCK` (default 1)
- `/ask` ve `/ask/stream`: sanitize sonucu blocked → 400 + audit
  log. Cleaned text agent'a iletilir.

### W6.4 — PII mask layer
- Yeni `api/pii.py`:
  - `mask_pii(text)` → 5 PII tipi:
    - TCKN (11 hane, ilk ≠ 0, lookaround)
    - Telefon (TR +90/0xxx, format-tolerant)
    - Email, IBAN, plaka
  - `MaskResult.counts` ve `.has_pii`
  - `hash_question(text)` SHA-256 first 16 hex — audit fingerprint
- `/ask`: kullanıcı sorusu PII-mask edilerek session/audit'e yazılır;
  LLM'e gönderilen metin orijinal (cevap için kullanıcının bilgisi gerekli olabilir).

### W6.5 — Audit log
- Yeni `api/audit.py`:
  - `AuditEvent` (event/principal/question_hash/domain/verdict/conv_id/...)
  - Ayrı `adalet.audit` logger, JSON stream stdout
  - Production: Filebeat / Vector ile object storage'a (S3) gönderim
  - `AUDIT_LOG_DISABLED` env
- Field rename: structlog reserved `event` kelimesi → `audit_event`

## Test Sayısı
- W5 sonu: 279 passed + 6 skipped (285 toplam)
- W6 sonu: **308 passed + 6 skipped** (+29 yeni)
  - tests/api/test_auth_middleware.py: 9 test
  - tests/api/test_sanitize_pii_audit.py: 20 test (sanitize 7 + pii 9 + audit 2 + extras)
- Regression: 0
- Coverage: **82.54%** (W5'te 80.98%; W6 yeni dosyalar mostly covered)
- mypy strict: 0 hata (62 source files; W5'te 57)
- ruff strict: 0 hata

## Çözülen Bug'lar
1. **structlog `event` kelimesi clash** — `AuditEvent.event` field'i payload'a
   `event=` olarak gönderiliyordu, structlog'un message kwargs ile çatışıyordu.
   `audit_event` olarak rename edildi.
2. **Soft sanitize `[SYSTEM]` greedy match** — `[^\[]*` regex'i bir sonraki `[`
   görene kadar tüm metni yutuyordu. `[^\n\[\.]{0,120}` ile sınırlandı.
3. **ruff PIE810** — `startswith` iki ayrı çağrı yerine tuple ile birleşik.

## Production Kullanım

### Environment variables (production)
```bash
AUTH_ENABLED=1
JWT_SECRET=<32+ byte random hex>
JWT_TTL_SECONDS=86400
JWT_ISSUER=adalet-agent
JWT_AUDIENCE=adalet-agent-api
PUBLIC_PATHS=/health,/docs,/openapi.json

# B2B API keys (production: secrets manager mount)
API_KEYS_FILE=/run/secrets/api_keys.json
# JSON format: {"<random-key>": "alpha-corp", "<random-key2>": "beta-ltd"}

# Rate limit per-key default 60/min — B2B paid tier için arttır
RATE_LIMIT_ASK=10/minute
RATE_LIMIT_ASK_API_KEY=60/minute

# Sanitize (PI filter)
SANITIZE_ENABLED=1
SANITIZE_HARD_BLOCK=1

# PII mask
PII_ENABLED=1

# Audit log (production'da JSON akışı stdout → filebeat → S3)
AUDIT_LOG_DISABLED=0
```

### Beta token issue (manual)
```python
from api.middleware.auth import issue_token
token = issue_token("beta-user-001", role="beta", email="user@example.com")
print(token)
```

### API key generate (cryptographically random)
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
# Bu key'i API_KEYS_FILE JSON'ına {"<key>": "label"} olarak ekle
```

## Sonraki
Hafta 7 — Production Security Part 2 (Infrastructure):
  - W7.1 Redis auth zorunlu + expose:6379 kaldır
  - W7.2 Qdrant API key + TLS
  - W7.3 Container hardening (security_opt, cap_drop, read-only fs)
  - W7.4 CI/CD GitHub Actions workflow
  - W7.5 Multimodal upload hardening
  - W7.6 Rate limiter Redis backend
  - W7.7 Secret rotation runbook
