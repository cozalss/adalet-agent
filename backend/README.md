# ADALET-AGENT Backend

> **Güncel durum (Mayıs 2026):** FastAPI + LangGraph üzerinde **doğrulamalı
> çoklu-ajan Türkçe Hukuk RAG**.
> **662 test** · ruff ✅ · mypy strict (215 dosya) ✅ · bandit ✅ · JWT+API-key auth.
>
> **Corpus:** 159k vektör (8 domain) · **Retrieval:** domain@1 %81.2, @5 %97.3, MRR 0.88
> (186-vaka benchmark, ölçüldü → [docs/theses/measured-results.md](../docs/theses/measured-results.md)).
>
> **Veri katmanı:** Qdrant (vektör) + PostgreSQL (feedback/api_key/audit, env-gated,
> Alembic) + Redis (session/rate-limit).

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

> **Sprint-5/6+ (güncel):** Corpus 62k→159k (HF Yargıtay 700k seed + Danıştay
> idari/vergi + GİB özelge); PostgreSQL ilişkisel katman (repository pattern +
> Alembic); retry artık re-retrieve eder; API/auth hardening (security headers,
> IDOR owner-binding, API key hash); domain-öncelikli tier-sort. 662 test.

## Modüller

```
backend/
├── main.py            FastAPI entry — lifespan (configure_logging+DB init+preload)
├── pyproject.toml     uv-managed deps + ruff/mypy strict + cov gate
├── Dockerfile         Multi-stage, non-root, healthcheck, read-only fs
├── agents/            LangGraph 12-node (triaj·mevzuat·emsal·draft·verify·debate·
│                      finalize + crag/self_rag/eligibility/tahmin/dilekçe) + state
├── retrieval/         BGE-M3 dense+sparse+ColBERT + HyDE + Multi-Query
│                      + RAPTOR (opt-in) + GraphRAG (opt-in) + tier-sort
├── verifier/          NLI + LettuceDetect + RARR
├── db/                PostgreSQL — engine + models + repositories (env-gated)
├── alembic/           DB migration (async, DATABASE_URL'den)
├── api/               Routes + middleware (auth/sanitize/PII/audit/security-headers)
│   ├── routes/        /ask, /ask/stream, /multimodal/*, /auth/*, /feedback, /dilekce
│   ├── middleware/    auth.py (JWT+API-key hash), sanitize.py, security_headers.py
│   ├── pii.py         PII mask layer (TCKN, phone, email, IBAN, plate)
│   ├── audit.py       Audit log stream (PII-free, hash fingerprint)
│   └── limiter.py     Per-principal rate limit (Redis backend)
├── core/              Logging redact + PII-mask + observability (Langfuse)
├── multimodal/        OCR + STT + TTS
├── predictive/        Tahmin modeli (BERT-TR — eğitim bekliyor)
├── eval/              eval_run, freeze_baseline, edge_cases, ragas_full, judge
│   └── runs/          Sprint changelogs + JSON outputs + manifest.json
├── scripts/           Seed (mevzuat/HF/Danıştay/GİB/UYAP) + build + backup + smoke
└── tests/             pytest — 662 test (api·agents·db·retrieval·verifier·multimodal)
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
# Tam suite (mock LLM)
uv run --extra dev pytest tests/ -q                  # 662 test
uv run --extra dev ruff check .                      # 0 hata
uv run --extra dev mypy .                            # 215 dosya, 0 hata
uv run --extra dev bandit -r . -c pyproject.toml -ll -ii   # güvenlik

# DB katmanı (aiosqlite, container'sız)
uv run --extra dev pytest tests/db/ -q

# Real-LLM integration (llama-server + Qdrant şart, skip otherwise)
uv run --extra dev pytest -m llm_integration -v
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
| POST | `/auth/invite/{code}` | public | Davet → JWT (gizlilik onayı) |
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
