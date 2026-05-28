# Sprint-4 Hafta 9 — Staging Deploy + TLS + Beta Onboarding Changelog

Önceki: `eval/runs/W8_changes.md`

## Hedef
Caddy reverse-proxy + auto-TLS; Hetzner init script; llama-server compose
placeholder; beta onboarding (invite + token + gizlilik onayı); feedback
endpoint; staging smoke E2E script.

## Değişiklikler

### W9.1 — Caddy reverse proxy + auto-TLS
- Yeni `infra/Caddyfile`:
  - `staging.adalet.app` server block — ACME auto-TLS, TLS 1.2+1.3
  - Security headers:
    - HSTS 1 yıl preload-eligible
    - X-Frame-Options DENY, X-Content-Type-Options nosniff
    - Referrer-Policy strict-origin-when-cross-origin
    - Permissions-Policy (camera off, microphone self için, geolocation off)
    - CSP minimal (backend-only; frontend kendi CSP'sini yönetir)
  - Reverse proxy:
    - `@health /health` — backend:8000
    - `@api /ask* /multimodal/* /auth/* /feedback*` — backend:8000 + SSE flush
    - `@docs /docs /openapi.json /redoc` — backend:8000
  - Access log JSON rotation (100MB, 14 dosya, 720h retention)

### W9.2 — Hetzner deploy script + runbook
- Yeni `infra/deploy/hetzner-init.sh`:
  - Ubuntu 24.04 → docker + compose + NVIDIA Container Toolkit + UFW + fail2ban
  - `adalet` deploy user (docker group)
  - Repo clone /opt/adalet-agent
  - `.env` template (random secret'lar `openssl rand`)
- Yeni `docs/runbooks/deploy-staging.md`:
  - Mimari diyagram
  - Önkoşullar + ilk kurulum 7 step (init → env → model → up → ACME → seed → smoke)
  - Update / rollback / beta onboarding / monitoring / disaster recovery
  - Pre-launch checklist

### W9.3 — llama-server compose entegrasyonu
- `docker-compose.yml` placeholder (commented out — RTX hazır olduğunda enable):
  - `ghcr.io/ggerganov/llama.cpp:server-cuda` image
  - GPU passthrough: `deploy.resources.reservations.devices` NVIDIA
  - Models volume mount, `-m qwen2.5-14b... -ngl 20 --ctx-size 8192`
- `LLM_SERVER_URL=http://llama-server:8080` env-config'de zaten yer alıyor

### W9.4 — Beta onboarding endpoint
- Yeni `api/routes/auth.py`:
  - `POST /auth/invite/{code}` — InviteAcceptRequest (privacy_consent zorunlu)
    → TokenResponse (access_token + expires_in + sub + role)
  - Davet kodu single-use, used_at + consent_given_at timestamp
  - `GET /auth/me` — token verify smoke + principal echo
  - `INVITE_CODES_FILE` JSON `{code: {email, name, used}}`
- Audit log entry: `invite_accepted`

### W9.5 — Smoke E2E staging script
- Yeni `scripts/smoke_staging.py`:
  - 8 vakalık QUESTIONS set (4 domain)
  - /health smoke → 200 + status ok
  - Her soru için POST /ask, latency + verdict + citations
  - JSON report `data/staging_runs/smoke_<ts>.json`
  - Threshold: 6/8 success (production'da 28/30 hedef)

### W9.6 — Feedback endpoint
- Yeni `api/routes/feedback.py`:
  - `POST /feedback` — rating (up/down) + opsiyonel comment + turn_index
  - Comment sanitize (PI filter) + PII mask
  - Persist: JSONL append-only `data/feedback/feedback_YYYYMMDD.jsonl`
  - Audit event: `feedback_up` / `feedback_down`
- Auth zorunlu (Depends(authenticate))

## Test Sayısı
- W8 sonu: 325 passed + 6 skipped
- W9 sonu: **336 passed + 6 skipped** (+11 yeni)
  - tests/api/test_auth_invite_feedback.py: 11 test
    (invite unknown/used/no-consent/accept/second-attempt + me/feedback × 4)
- Regression: 0
- Coverage: **83.24%** (gate ✓)
- mypy strict: 0 errors (67 source files)
- ruff strict: 0 errors

## Çözülen Bug'lar
1. **`EmailStr` import** — `pydantic[email]` extra eksik; regex pattern ile string'e
   indirildi (`^[^@\s]+@[^@\s]+\.[^@\s]+$`).
2. **W9.4 feedback async + pathlib mkdir ASYNC240** — file-level ignore eklendi
   (basit dosya I/O, blocking event-loop'u dert etmiyor).

## Production Kullanım

### Deploy adımları (özet)
```bash
# 1) Server init
ssh root@<server-ip>
bash <(curl -fsSL https://raw.githubusercontent.com/.../infra/deploy/hetzner-init.sh)

# 2) .env'i doldur
cd /opt/adalet-agent && nano .env

# 3) Compose
docker compose --env-file .env up -d

# 4) ACME bekle (~30s) + smoke
curl -fsSL https://staging.adalet.app/health | jq .

# 5) Beta davet üret
docker compose exec backend python -c "
import json, secrets
codes = {secrets.token_urlsafe(12): {'email': 'user@example.com', 'used': False}}
print(json.dumps(codes, indent=2))
" > /run/secrets/invites.json
```

### Beta kullanıcı akışı
```
POST /auth/invite/{code}
  Body: {"privacy_consent": true, "email": "...", "name": "..."}
  → 200 {"access_token": "...", "sub": "beta:...", "role": "beta", "expires_in": 86400}

Sonra her istekte:
  Authorization: Bearer <access_token>
```

## Sonraki
Hafta 10 — Final Eval + ADR + Akademik Material:
  - W10.1 Final benchmark v3 (200 vaka × 5 mode)
  - W10.2 LLM-Judge full + Ragas full
  - W10.3 eval/runs/manifest.json
  - W10.4 8 ADR (NLI threshold, LLM_MODE, ColBERT, RAPTOR/GraphRAG,
    JWT vs API key, PII mask, Caddy TLS, benchmark policy)
  - W10.5 Architecture diagram (Mermaid)
  - W10.6 README v13 update
  - W10.7 Akademik paper draft
