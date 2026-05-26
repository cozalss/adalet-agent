# ADALET-AGENT

> Türkçe Hukuk için Çok Modlu, Çoklu-Ajan ve Doğrulamalı Yapay Zeka Vatandaş Asistanı

Çankaya Üniversitesi Yazılım Mühendisliği bitirme projesi. Tüketici, işçi, kiracı vatandaşa **uydurmadan**, **gerçek Yargıtay kararları ve mevzuatla doğrulanmış** Türkçe hukuk yardımı.

Tam vizyon ve mimari: [CLAUDE.md](CLAUDE.md)

---

## Quickstart (Windows, ~10 dk)

```powershell
# 1) Klonla
git clone https://github.com/cozalss/adalet-agent.git
cd adalet-agent

# 2) Bootstrap (Python+uv+Docker+modeller+test)
.\scripts\bootstrap.ps1

# 3) Backend başlat (MockLLM mode — dev default)
cd backend
uv run uvicorn main:app --reload

# 4) Tarayıcıda Swagger UI:
#    http://127.0.0.1:8000/docs
```

Hızlı atlatma:
- `bootstrap.ps1 -SkipModels` — 11 GB model indirimini atla (multimodal çalışmaz)
- `bootstrap.ps1 -SkipDocker` — Qdrant/Redis container'larını başlatma (manuel başlat)

---

## Ön gereksinimler

| Araç | Versiyon | Nereden |
|---|---|---|
| Python | 3.11+ | https://python.org |
| uv | 0.4+ | `pip install uv` (bootstrap otomatik) |
| Docker Desktop | 24+ | https://docker.com (Qdrant + Redis için) |
| Git | 2.40+ | https://git-scm.com |

Opsiyonel (gerçek LLM/multimodal için):
- **CUDA 12.4** + RTX 3060+ (Qwen 14B llama-server için)
- **Tesseract 5.4** — `winget install UB-Mannheim.TesseractOCR` (OCR için)

---

## Klasör yapısı

```
adalet-agent/
├── backend/              # FastAPI + LangGraph + RAG (Python 3.11)
│   ├── agents/           # 7 ajan (Triaj/Mevzuat/Emsal/Draft/Verify/Debate/Finalize)
│   ├── api/              # FastAPI route + auth + rate-limit
│   ├── core/             # Observability (Langfuse v4) + scheduler
│   ├── retrieval/        # BGE-M3 hybrid + RAPTOR + GraphRAG + reranker
│   ├── multimodal/       # OCR (Tesseract) + STT (faster-whisper) + TTS (Piper)
│   ├── predictive/       # ML tahmin modeli (Sprint-7/8 plan)
│   ├── eval/             # Ragas + freeze_baseline + domain_audit
│   ├── scripts/          # Seed + bootstrap + refresh cron
│   ├── tests/            # 378 test (373 base + 5 multimodal_integration)
│   └── models/           # GGUF/ONNX/tessdata (gitignore'da, 11 GB)
├── mobile/               # Flutter iOS + Android (yapım aşamasında)
├── docs/
│   ├── decisions/        # ADR-001..009
│   └── runbooks/         # Langfuse, LLM production, regulator gaps
├── data/                 # Eval benchmark + seed_state JSONL
├── docker-compose.yml    # Production stack (Qdrant + Redis + backend hardened)
├── docker-compose.dev.yml # Dev stack (Qdrant + Redis only)
└── scripts/
    └── bootstrap.ps1     # Sıfırdan kurulum (Windows)
```

---

## LLM mode'ları

`.env` içinde `LLM_MODE`:

| Mode | Ne | Ne zaman |
|---|---|---|
| `mock` | MockLLM, deterministik | **Dev default**, test, CI |
| `llamacpp_server` | HTTP llama-server (Qwen 14B-Q5) | Production, manuel başlat |
| `llamacpp` | In-proc Python (CUDA gerek) | Tek-process dev (yavaş) |

Gerçek LLM kurulumu: [docs/runbooks/llm-production-setup.md](docs/runbooks/llm-production-setup.md)

**Not:** `docker-compose.yml`'deki `caddy` ve `llama-server` servisleri şu an
placeholder (commented out). Production deploy için Sprint-9 W9.1-9.3 (Caddy
TLS + llama-server GPU passthrough) tamamlanmadı. Şu an gerçek LLM ayrı bir
süreç olarak host'ta çalışıyor; backend container `host.docker.internal:8080`'e
bağlanıyor.

---

## Test ve Lint

```powershell
cd backend
uv run pytest tests/ -m "not gpu and not llm_integration" --no-cov   # 373 base
uv run pytest tests/ -m multimodal_integration                       # 5 (Piper+Whisper+Tesseract)
uv run pytest --cov                                                  # full + coverage
uv run ruff check .                                                  # 0 hata bekleniyor
uv run mypy .                                                        # 158 source, 0 hata
```

Markerlar (pyproject.toml):
- `integration` — Qdrant/Redis/llama-server gerek
- `gpu` — CUDA gerek
- `llm_integration` — llama-server 8080 canlı
- `multimodal_integration` — Whisper+Piper+Tesseract model dosyaları
- `slow` — >10s

**Not:** mypy strict global açık ama legacy modüllerde (retrieval, multimodal,
api.*) per-module override ile yumuşatılmış — gradual adoption. Yeni modüller
(`agents.verifier_layers`, `verifier.rarr`, `agents.nodes.draft`) tam strict.
Test'ler ve script'ler için annotation zorunlu değil.

---

## Qdrant seed (gerçek retrieval için)

MockLLM mode'da boş Qdrant ile graph akışı test edilir, ama **gerçek cevap** için 62k chunk seed gerek:

```powershell
cd backend

# Mevzuat (62 kanun, ~12k chunk, ~5 dk)
uv run python -m scripts.seed_mevzuat

# Yargıtay + AYM kararları (~50k chunk, saatler sürer)
uv run python -m scripts.seed.pipeline --court yargitay --domain tuketici
# ... her domain için tekrarla

# Doğrulama
uv run python -m eval.domain_audit
```

---

## Yol haritası

12 ay (Eyl 2026 - Eyl 2027). Sprint detayları: [docs/decisions/](docs/decisions/) + [eval/runs/Sprint*_changes.md](backend/eval/runs/)

Şu an: **Sprint-6 bridge** — multimodal real (Piper+Whisper+Tesseract) +
Langfuse v4 observability ✅; predictive Sprint-7/8 plan ready ✅;
retrieval tuning + benchmark v3 + Caddy/llama-server compose henüz açık.

---

## Lisans

MIT — bkz. [LICENSE](LICENSE).

## Asla yapma

- Hukuki referans uydurma. Madde/karar şüpheliyse `[DOĞRULA: ...]` placeholder.
- Test verisinde gerçek TCKN/telefon/isim. Hep sahte (`Ayşe Yılmaz`, `0555-123-4567`).
- Production'da OpenAI/Anthropic API. Sadece lokal model.
- Hardcoded secret. `.env` kullan.
