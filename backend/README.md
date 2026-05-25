# ADALET-AGENT Backend

> **Sürüm:** v13 (Sprint-4 sonu — Mayıs 2026)
> FastAPI + LangGraph üzerinde **doğrulamalı çoklu-ajan Türkçe Hukuk RAG**.
> 336 test green, 83% coverage, mypy --strict, ruff strict, JWT auth, TLS hazır.

## Sprint-4 Özet (10 hafta, 25h/hafta)

| Hafta | Konu | Δ Test | Δ Coverage |
|---|---|---|---|
| W1 | Retrieval quick wins (ColBERT, HyDE 15s, Multi-Query JSON, BM25 stemmer) | +8 | — |
| W2 | Benchmark expansion 50→186 vaka, p95 latency, edge_cases v2, Ragas fix | +12 | — |
| W3 | RAPTOR persistence + GraphRAG traversal | +11 | — |
| W4 | Verifier split + RARR-lite + adversarial debate | +8 | — |
| W5 | mypy --strict + ruff strict + real-LLM suite + Yargıtay regression | +35 | 80.98% |
| W6 | JWT + API-key auth + PI filter + PII mask + audit log | +29 | 82.54% |
| W7 | Redis/Qdrant auth + container hardening + CI workflow + secret runbook | +11 | 82.50% |
| W8 | Langfuse + /health depth + Qdrant backup + log redact + cost tracker | +6 | 82.53% |
| W9 | Caddy auto-TLS + Hetzner init + beta onboarding + feedback | +11 | 83.24% |
| W10 | Final eval + 8 ADR + architecture diagram + paper draft | — | 83.24% |
| **Toplam** | | **+131** | **83.24%** |

Detay: [`eval/runs/W{1..10}_changes.md`](eval/runs/).

## Modüller

```
backend/
├── main.py            FastAPI entry — lifespan preload + /health depth
├── pyproject.toml     uv-managed deps + ruff/mypy strict + cov gate
├── Dockerfile         Multi-stage, non-root, healthcheck, read-only fs
├── agents/            LangGraph 7-ajan + verifier_layers
├── retrieval/         BGE-M3 dense+sparse+ColBERT + HyDE + Multi-Query
│                      + RAPTOR (opt-in) + GraphRAG (opt-in)
├── verifier/          NLI + LettuceDetect + RARR-lite (W4)
├── api/               Routes + middleware (auth/sanitize/PII/audit)
│   ├── routes/        /ask, /ask/stream, /multimodal/*, /auth/*, /feedback
│   ├── middleware/    auth.py (JWT+API-key), sanitize.py (PI filter)
│   ├── pii.py         PII mask layer (TCKN, phone, email, IBAN, plate)
│   ├── audit.py       Audit log stream (PII-free, hash fingerprint)
│   └── limiter.py     Per-principal rate limit (Redis backend)
├── core/              Logging redact + observability (Langfuse)
├── multimodal/        OCR + STT + TTS
├── eval/              freeze_baseline, edge_cases, ragas_full, judge
│   └── runs/          Sprint changelogs + JSON outputs + manifest.json
├── scripts/           Seed, build, backup, smoke, manifest
└── tests/             pytest — 336 test (mock LLM), llm_integration mark
```

## Quickstart

### Yerel geliştirme (mock LLM, hızlı)
```bash
uv sync
uv run uvicorn main:app --reload --port 8000
# http://localhost:8000/docs Swagger UI
```

### Production smoke (real Qwen + mock retrieval)
```bash
# 1) llama-server (RTX 4070, ~30s yükleme)
./llama-server -m models/qwen2.5-14b-q4_k_m.gguf -ngl 20 --ctx-size 8192 --port 8080

# 2) Smoke (Qdrant gerek yok)
LLM_MODE=llamacpp_server PYTHONUTF8=1 \
  uv run python -m scripts.smoke_real_llm_mock_retrieval
# Beklenen: 3/3 pass, avg ~32s/soru
```

### Full production (docker compose)
```bash
# .env hazırla (secret rotation runbook'a bak)
cp ../.env.example ../.env
nano ../.env  # REDIS_PASSWORD, QDRANT_API_KEY, JWT_SECRET doldur

# Compose
docker compose --env-file ../.env up -d
curl https://staging.adalet.app/health  # Caddy ACME alındıktan sonra
```

Detaylı deploy: [`docs/runbooks/deploy-staging.md`](../docs/runbooks/deploy-staging.md).

## Test

```bash
# Tam suite (mock LLM, ~15s)
uv run pytest tests/ --ignore=tests/multimodal --ignore=tests/training \
  --cov --cov-report=term --cov-fail-under=80
# 336 passed, 6 skipped, 83.24% cov

# mypy strict + ruff strict
uv run mypy . --exclude '\.venv' --exclude tests --exclude scripts
uv run ruff check .

# Real-LLM integration (llama-server + Qdrant şart, skip otherwise)
uv run pytest -m llm_integration -v
```

## Eval

```bash
# 4-mode retrieval karşılaştırma (W2 v2 benchmark)
uv run python -m eval.freeze_baseline --benchmark v2 \
  --modes hybrid,rerank,hyde,multi_query
# Çıktı: eval/runs/v2_w2_<sha>.json

# Edge cases (24 vaka — PI, jailbreak, scope, PII, OWASP LLM Top-10)
uv run python -m eval.edge_cases  # eval/runs/edge_cases_<ts>.json

# Manifest build
uv run python -m scripts.build_eval_manifest
# Çıktı: eval/runs/manifest.json

# Cost report (haftalık, Langfuse trace'lerden)
uv run python -m scripts.cost_report --days 7

# Qdrant backup (cron)
uv run python -m scripts.backup_qdrant --s3
```

## Endpoint'ler

| Method | Path | Auth | Açıklama |
|---|---|---|---|
| GET | `/health` | public | Depth: qdrant + redis + llm ping |
| POST | `/ask` | required | 7-ajan zinciri (JSON) |
| POST | `/ask/stream` | required | SSE per-node event |
| DELETE | `/ask/session/{conv_id}` | required | History temizle |
| POST | `/multimodal/ocr` | required | Belge → metin |
| POST | `/multimodal/stt` | required | Ses → metin |
| POST | `/multimodal/tts` | required | Metin → WAV |
| POST | `/auth/invite/{code}` | public | Davet → JWT (KVKK consent) |
| GET | `/auth/me` | required | Principal echo |
| POST | `/feedback` | required | Thumbs up/down + comment |

## Güvenlik (Sprint-4 W6+W7)

- **JWT** (HS256, 24h TTL) — kullanıcı flow
- **X-API-Key** — B2B partner; rate limit 60/min (vs 10/min user)
- **Prompt-injection filter** — 9 hard regex (TR+EN) + soft `[SYSTEM]` strip
- **PII mask** — TCKN, phone, email, IBAN, plate; persist/audit'e PII'siz
- **Audit log** — hash(question), domain, verdict; PII-free JSON stream
- **Rate limit** — slowapi + Redis backend, per-principal (NAT-aware)
- **Container hardening** — read-only fs, cap-drop ALL, no-new-privileges, tmpfs
- **TLS** — Caddy 2 auto-TLS, HSTS 1y preload, X-Frame DENY, CSP minimal
- **Audit/log redaction** — `core/logging.py` SENSITIVE_KEYS allow-list

## CI / Test Coverage

`.github/workflows/backend-ci.yml`:
1. lint-and-types (ruff + mypy strict)
2. test-and-coverage (pytest --cov-fail-under=80)
3. security-scan (pip-audit + bandit)
4. docker-build smoke

## Önemli Dosyalar

- [`docs/architecture.md`](../docs/architecture.md) — Mermaid diagrams + module map
- [`docs/decisions/`](../docs/decisions/) — 8 ADR (W4-W9 kararları)
- [`docs/runbooks/deploy-staging.md`](../docs/runbooks/deploy-staging.md) — Hetzner deploy
- [`docs/runbooks/secret-rotation.md`](../docs/runbooks/secret-rotation.md) — 90-gün rotation
- [`docs/theses/paper-draft.md`](../docs/theses/paper-draft.md) — Akademik makale taslağı
- [`eval/runs/manifest.json`](eval/runs/manifest.json) — tüm eval run'larının index'i

## Lisans

MIT — bkz. [LICENSE](../LICENSE).
