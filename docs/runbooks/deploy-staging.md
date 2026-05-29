# Hetzner Staging Deploy Runbook

> Sprint-4 W9 — staging.adalet.app deploy prosedürü. İlk kurulum + sonraki
> deploy'lar için.

## Mimari

```
        Internet (443/80)
              ↓
        ┌─────────┐
        │ Caddy 2 │  ← auto-TLS, HSTS, security headers
        └────┬────┘
             │ http://backend:8000
        ┌────▼────┐
        │ backend │  ← FastAPI + LangGraph (read-only fs, cap-drop ALL)
        └────┬────┘
             ├─ http://qdrant:6333   (API key auth, internal-only)
             ├─ redis://redis:6379   (requirepass, internal-only)
             └─ http://llama-server:8080  (GPU: RTX 4070, -ngl 20)
```

## Önkoşullar
- Hetzner CCX23 (4 vCPU, 16GB RAM) veya GPU-enabled instance (RTX A4000+)
- Ubuntu 24.04 LTS
- DNS A kaydı: `staging.adalet.app` → server IP (TTL 300)
- SSH root erişimi

## İlk Kurulum (One-Shot)

### 1. Server init
```bash
ssh root@<server-ip>
curl -fsSL https://raw.githubusercontent.com/<org>/adalet-agent/main/infra/deploy/hetzner-init.sh | bash
```

Bu script:
- Docker + Compose + NVIDIA Container Toolkit kurar
- UFW: yalnız 22/80/443 açar
- fail2ban + unattended-upgrades
- `adalet` user + `/opt/adalet-agent` clone
- `.env` template'i random secret'larla yaratır (chmod 600)

### 2. .env kontrol
```bash
sudo -iu adalet
cd /opt/adalet-agent
nano .env
# Özellikle kontrol et:
# - REDIS_PASSWORD, QDRANT_API_KEY, JWT_SECRET (init script doğru random verdi)
# - ALLOWED_ORIGINS frontend URL'leriyle eşleşiyor
# - LLM_MODE=llamacpp_server
# - LLM_SERVER_URL=http://llama-server:8080
# - LLAMA_MODEL_FILE=Qwen2.5-14B-Instruct-Q5_K_M.gguf
```

### 3. Model dosyaları
```bash
# llama-server için GGUF modeli
mkdir -p /opt/adalet-agent/backend/models
cd /opt/adalet-agent/backend/models
# compose default LLAMA_MODEL_FILE ile aynı isimde kaydet
wget -O Qwen2.5-14B-Instruct-Q5_K_M.gguf \
  https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-GGUF/resolve/main/qwen2.5-14b-instruct-q5_k_m.gguf

# BGE-M3 + reranker + NLI — backend ilk run'da indirir (HF cache volume'a)
```

### 4. Compose up
```bash
cd /opt/adalet-agent
docker compose --profile production --env-file .env up -d
docker compose ps  # tüm servisler healthy bekle (~3 dk)
```

### 5. ACME / TLS doğrulama
```bash
docker compose --profile production logs caddy | grep "certificate obtained"
# "successfully obtained certificate for staging.adalet.app"
curl -fsSL https://staging.adalet.app/health | jq .
# {"status":"ok", "components": {"qdrant":"ok", "redis":"ok", "llm":"ok"}}
```

### 6. Veri seed'i
```bash
# Qdrant collection'ları + chunks
docker compose --profile production exec backend uv run python -m scripts.seed_mevzuat
docker compose --profile production exec backend uv run python -m scripts.seed_emsal
# RAPTOR offline build (opsiyonel, ~30dk)
docker compose --profile production exec backend uv run python -m scripts.build_raptor --max-chunks 800
# GraphRAG build (LLM gerek yok, ~5dk)
docker compose --profile production exec backend uv run python -m scripts.build_graph
```

### 7. Smoke E2E
```bash
docker compose --profile production exec backend uv run python -m scripts.smoke_real_llm_mock_retrieval
# 3/3 pass bekle
```

## Yeni Deploy (Update)

```bash
sudo -iu adalet
cd /opt/adalet-agent
git pull --ff-only
docker compose --profile production --env-file .env build backend
docker compose --profile production --env-file .env up -d backend caddy llama-server
docker compose ps
# health check
curl -fsSL https://staging.adalet.app/health | jq .status
```

Zero-downtime için Caddy reverse-proxy backend health-check yapar; backend
restart sırasında 502 olabilir (~30s window). Production'da blue/green
gerekirse 2 backend replica + Caddy load-balance.

## Beta Kullanıcı Onboarding

### Davet kodu üret (admin host'tan)
```bash
docker compose --profile production exec backend python -c "
from api.middleware.auth import issue_token
print(issue_token('beta-user-001', role='beta'))
"
# Token'ı SOPS/email ile beta kullanıcıya gönder
```

Veya `/auth/invite/{code}` endpoint'i (W9.4'te eklenir) ile self-service.

## Monitoring

### Logs
```bash
docker compose --profile production logs -f backend caddy llama-server
# Audit log ayrı stream (Filebeat → S3 production'da)
docker compose --profile production exec backend tail -f /var/log/adalet/audit.log
```

### Grafana (gelecek)
- Metrics endpoint `/metrics` (W10'da Prometheus exporter)
- Langfuse trace dashboard https://cloud.langfuse.com

## Rollback

### Acil — son commit
```bash
cd /opt/adalet-agent
git reset --hard HEAD~1
docker compose --profile production --env-file .env build backend
docker compose --profile production --env-file .env up -d backend caddy llama-server
```

### Veri rollback (Qdrant snapshot restore)
```bash
# Son snapshot
ls /var/backups/adalet/qdrant/ | tail
# Restore
curl -X PUT -H "api-key: $QDRANT_API_KEY" \
  http://localhost:6333/collections/mevzuat/snapshots/recover \
  -H "Content-Type: application/json" \
  -d '{"location": "/var/backups/adalet/qdrant/mevzuat__<snapshot>"}'
```

## DDOS / Abuse

- UFW: yalnız 22/80/443 — diğer port'lar kapalı
- fail2ban: SSH brute-force koruma
- slowapi: per-principal rate limit (Redis backend)
- Cloudflare DNS önerilir (ücretsiz tier yeterli)

## Felaket Senaryoları

| Senaryo | Tespit | Aksiyon |
|---|---|---|
| Server down | `/health` 5xx, Cloudflare uptime | Hetzner panel'den yeniden başlat |
| Disk dolu | `df -h` >80% | Eski snapshot temizle (`backup_qdrant.py --retention 3`) |
| GPU OOM (llama-server) | `docker logs llama-server` | `-ngl` düşür (20→18), restart |
| Qdrant veri kaybı | health 503 + collection boş | Snapshot restore (yukarı) |
| Secret leak | audit log anomaly | `docs/runbooks/secret-rotation.md` uygula |

## Pre-Launch Checklist

```
[ ] .env tüm secret'lar set, 600 permission
[ ] DNS A kaydı çözünüyor
[ ] TLS sertifika obtained (Caddy log)
[ ] /health 200 + tüm components ok
[ ] Smoke E2E 3/3 pass
[ ] Qdrant collection'lar seed edildi
[ ] Cron job'lar (backup, cost) aktif
[ ] UFW yalnız 22/80/443
[ ] fail2ban running
[ ] Snapshot retention test edildi (cleanup_old)
[ ] Beta kullanıcılarına davet email'leri hazır
[ ] Frontend domain CORS allowed_origins'a eklendi
```
