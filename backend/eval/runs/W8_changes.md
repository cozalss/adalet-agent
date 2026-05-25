# Sprint-4 Hafta 8 — Observability + Health + Backup Changelog

Önceki: `eval/runs/W7_changes.md`

## Hedef
Langfuse trace; /health depth; Qdrant backup script; structured log redact;
cost tracker.

## Değişiklikler

### W8.1 — Langfuse LangGraph callback
- Yeni `core/observability.py`:
  - `get_langfuse_handler()` — LangChain CallbackHandler döner
  - ENV `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` yoksa None → no-op
  - `trace_name`, `user_id`, `session_id`, `metadata` parametreleri
- `api/routes/ask.py`:
  - `/ask` graph.ainvoke() çağrısında `config={"callbacks": [handler]}` ile trace
  - `user_id=principal.sub`, `session_id=conversation_id`
  - metadata: `domain`, `principal_kind`

### W8.2 — /health depth
- `main.py /health`:
  - Qdrant `/healthz` ping (2s timeout)
  - Redis ping via session_store.health() (InMemory/Redis backend)
  - LLM `/health` ping (sadece LLM_MODE=llamacpp_server)
  - Status logic:
    - dev mode (LLM_MODE=mock) → external down → "degraded", 200
    - prod mode + Qdrant down → "down", 503
    - LLM/Redis down → "degraded", 200

### W8.3 — Qdrant backup cronjob
- Yeni `scripts/backup_qdrant.py`:
  - `list_collections()` → snapshot per-collection
  - `create_snapshot()` + `download_snapshot()` (Qdrant REST API)
  - `cleanup_old()` retention policy (default 7 gün)
  - `--s3` flag ile boto3 ile S3 upload (Hetzner Object Storage uyumlu)
  - JSON report (`_report_<ts>.json`)
  - Cron örneği docstring'de

### W8.4 — Redis AOF (W7'de kapsandı)
- W7.1'de `docker-compose.yml` redis service zaten `--appendonly yes
  --appendfsync everysec` ile yapılandırıldı. W8'de ek değişiklik yok.

### W8.5 — Structured log formatter (redact + PII mask)
- Yeni `core/logging.py`:
  - `SENSITIVE_KEYS` allow-list (password, token, secret, jwt, cookie, ...)
  - `_redact_sensitive()` processor — case-insensitive + nested dict
  - `_mask_pii_in_strings()` processor — string değerlerde PII pattern
  - `configure_logging()` global entry — JSON (prod) / Console (dev)
- 6 yeni test (`tests/core/test_logging_redact.py`)

### W8.6 — Cost tracker
- Yeni `scripts/cost_report.py`:
  - Langfuse SDK fetch_traces / get_traces / list_traces (versiyon-tolerant)
  - Token aggregation (input/output/total)
  - Per-user top-10 breakdown
  - `PRICE_INPUT_PER_1K` / `_OUTPUT_` env ile cost estimate
    (default lokal Qwen → $0)
  - Output: `eval/runs/cost_YYYYMMDD.json`

## Test Sayısı
- W7 sonu: 319 passed + 6 skipped
- W8 sonu: **325 passed + 6 skipped** (+6 yeni)
  - tests/core/test_logging_redact.py: 6 test
- Regression: 0
  - test_health_returns_ok güncellendi (artık depth components içeriyor,
    dev mode'da ok/degraded toleranslı)
- Coverage: **82.53%** (gate ✓)
- mypy strict: 0 errors (65 source files; W7'de 62)
- ruff strict: 0 errors

## Çözülen Bug'lar
1. **HealthResponse.status Literal** — "unhealthy" enum'da yok, "down" kullan.
2. **`_redact_dict` mypy type-arg** — `out: dict[str, Any] = {}` explicit.
3. **`datetime.utcnow()` deprecated** — `datetime.now(UTC)` ile değiştirildi.

## Production Kullanım

### Langfuse trace (production'a entegrasyon)
```bash
LANGFUSE_PUBLIC_KEY=pk_lf_xxx
LANGFUSE_SECRET_KEY=sk_lf_xxx
LANGFUSE_HOST=https://cloud.langfuse.com  # veya self-hosted
```

### Qdrant backup cron (Hetzner staging)
```bash
# /etc/cron.d/adalet-backup
0 3 * * * root cd /opt/adalet-agent && docker compose exec backend uv run python -m scripts.backup_qdrant --s3
```

### Cost report (haftalık)
```bash
0 9 * * MON root cd /opt/adalet-agent && docker compose exec backend uv run python -m scripts.cost_report --days 7
```

### Logging
```bash
LOG_FORMAT=json  # production
LOG_FORMAT=console  # dev
LOG_LEVEL=INFO
```

## Sonraki
Hafta 9 — Staging Deploy + TLS + Beta Onboarding:
  - W9.1 Caddy reverse proxy + auto-TLS + security headers
  - W9.2 Hetzner deploy script + runbook
  - W9.3 llama-server compose entegrasyonu (GPU passthrough)
  - W9.4 Beta onboarding endpoint (/auth/invite/{code})
  - W9.5 Smoke E2E on staging URL
  - W9.6 Feedback endpoint
