# Sprint-4 Hafta 7 — Production Security Part 2 (Infrastructure) Changelog

Önceki: `eval/runs/W6_changes.md`

## Hedef
Redis/Qdrant auth zorunlu; container hardening; CI/CD workflow; multimodal
upload sanitize; rate-limiter Redis backend; secret rotation runbook.

## Değişiklikler

### W7.1 — Redis password zorunlu + expose:6379 kaldır
- `docker-compose.yml` redis:
  - `--requirepass ${REDIS_PASSWORD:?...}` (zorunlu env)
  - `--appendfsync everysec` (W8 yedek)
  - `--maxmemory 512mb`, `--maxmemory-policy allkeys-lru`
  - Host'a expose YOK — `adalet-net` internal-only
- Backend bağlanma: `REDIS_URL=redis://:password@redis:6379/0`
- Test code zaten `redis_url` üzerinden auth destekliyor (session_store.py).

### W7.2 — Qdrant API key + internal-only
- `docker-compose.yml` qdrant:
  - `QDRANT__SERVICE__API_KEY=${QDRANT_API_KEY:?...}`
  - `QDRANT__SERVICE__ENABLE_CORS=false`
  - Host'a expose YOK
- Backend bağlanma: `QDRANT_URL=http://qdrant:6333`, `QDRANT_API_KEY=...`
- `retrieval/vector_store.py:33` zaten `QDRANT_API_KEY` env'ini okuyor.

### W7.3 — Container hardening (backend service)
- `read_only: true` — root fs salt okunur
- `security_opt: [no-new-privileges:true]`
- `cap_drop: [ALL]` — tüm Linux capabilities düşürüldü
- `tmpfs`: `/tmp` (512m) + `/home/app/.cache` (128m) — writable
- `deploy.resources.limits.memory: 8G` — model'ler için
- `depends_on: {qdrant, redis: condition: service_healthy}` — healthcheck wait

### W7.4 — CI/CD GitHub Actions workflow
- `.github/workflows/backend-ci.yml` rewrite (4 job):
  1. **lint-and-types**: ruff + mypy strict
  2. **test-and-coverage**: pytest + `--cov-fail-under=80` gate, mock LLM env
  3. **security-scan**: pip-audit (deps) + bandit (source)
  4. **docker-build**: Buildx + GHA cache (no push)
- Tetikleyici: `main`, `develop`, `sprint-*` branch + PR

### W7.5 — Multimodal upload hardening
- `api/routes/multimodal.py`:
  - `_sanitize_filename()` — path traversal, null byte, control char temizliği
  - `_ALLOWED_AUDIO_EXTS` whitelist — extension allowlist (mime check'in üstüne)
  - Tüm `/multimodal/ocr|stt|tts` endpoint'lerine `Depends(authenticate)` eklendi
- `tests/api/test_multimodal_security.py`:
  - 11 test (path traversal, null byte, Unicode strip, length cap, edge cases)

### W7.6 — Rate limiter Redis backend
- `docker-compose.yml backend`:
  - `RATE_LIMIT_STORAGE_URI=redis://:${REDIS_PASSWORD}@redis:6379/1`
  - DB 1 ayrılmış (DB 0 session_store için)
- Multi-worker uvicorn deploy'unda her replica aynı limit kovasını paylaşır.
- W6.2 `_principal_key()` per-principal limit ile çalışıyor.

### W7.7 — Secret rotation runbook
- `docs/runbooks/secret-rotation.md`:
  - Etkilenen secret tablosu (JWT, Redis, Qdrant, B2B keys, Langfuse, TLS)
  - 90 günlük periyodik + tetikleyici listesi (CVE, ekip ayrılma vb.)
  - Step-by-step: JWT / Redis / Qdrant / B2B key / TLS
  - 48h overlap window kuralı
  - Rollback prosedürü
  - Checklist template

## Test Sayısı
- W6 sonu: 308 passed + 6 skipped
- W7 sonu: **319 passed + 6 skipped** (+11 yeni)
  - tests/api/test_multimodal_security.py: 11 (filename sanitize)
- Regression: 0
- Coverage: **82.50%** (gate ✓)
- mypy strict: 0 errors (62 source files)
- ruff strict: 0 errors

## Çözülen Bug'lar
1. **`_ALLOWED_EXTS` function-local CONST naming (N806)** — module level çıkarıldı.

## Production Kullanım

### .env örneği
```bash
# Required
REDIS_PASSWORD=<openssl rand -base64 48>
QDRANT_API_KEY=<openssl rand -base64 64>
JWT_SECRET=<openssl rand -hex 32>
AUTH_ENABLED=1

# Optional
API_KEYS_FILE=/run/secrets/api_keys.json
JWT_ISSUER=adalet-agent
JWT_AUDIENCE=adalet-agent-api
LLM_MODE=llamacpp_server
LLM_SERVER_URL=http://llama-server:8080  # W9'da compose'a eklenir
```

### Deploy (Hetzner staging)
```bash
cd /opt/adalet-agent
# Secrets manager / sops ile .env decrypt
docker compose --env-file .env up -d
# Smoke
curl -fsS https://staging.adalet.app/health
```

### Local dev (auth OFF default)
```bash
# Sadece minimum env, AUTH_ENABLED=0 → anonymous
docker compose up qdrant redis  # backend host'tan çalışıyorsa
```

## Sonraki
Hafta 8 — Observability + Health + Backup:
  - W8.1 Langfuse LangGraph callback (per-agent trace + trace_id response)
  - W8.2 /health depth (Qdrant get_collection, Redis ping, LLM /v1/models)
  - W8.3 Qdrant backup cronjob (S3/Hetzner Object Storage)
  - W8.4 Redis AOF + persistence policy
  - W8.5 Structured log formatter (sensitive key redact)
  - W8.6 Cost tracker (Langfuse trace → token usage)
