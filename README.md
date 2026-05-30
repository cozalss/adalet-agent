# ADALET-AGENT

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-agent%20orchestration-1C3C3C)](https://langchain-ai.github.io/langgraph/)
[![Qdrant](https://img.shields.io/badge/Qdrant-vector%20search-DC244C?logo=qdrant&logoColor=white)](https://qdrant.tech)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

ADALET-AGENT, Türkçe hukuk sorularını kaynaklı ve doğrulamalı cevaplamak için
geliştirilen lokal çalışabilir bir yapay zeka asistanıdır. Sistem; mevzuat,
Yargıtay, Danıştay, Anayasa Mahkemesi ve düzenleyici kurum verilerini hibrit
retrieval ile getirir, cevabı çoklu ajan akışında üretir ve hukuki iddiaları
doğrulama katmanlarından geçirir.

Amaç basit: genel amaçlı LLM'lerin hukukta yaptığı madde, karar ve kaynak
uydurma riskini azaltmak; doğrulanamayan iddiaları üretmek yerine reddetmek.

> Hukuki tavsiye değildir. Sistem bilgilendirme amaçlıdır; somut uyuşmazlıkta
> avukata danışılmalıdır.

## Durum

| Alan | Durum |
|---|---|
| Backend | FastAPI + LangGraph tabanlı çekirdek sistem hazır |
| Retrieval | Qdrant üzerinde 159k hukuk vektörü ile ölçülmüş RAG |
| Doğrulama | Fuzzy match, LettuceDetect, NLI veto ve debate katmanları |
| Auth/Güvenlik | JWT, API key, PII maskeleme, audit, rate limit, security headers |
| Production infra | Docker Compose, Caddy TLS, PostgreSQL, Redis, Qdrant, llama-server profili |
| Frontend | `frontend/` placeholder, UI henüz uygulanmadı |
| Mobile | `mobile/` Flutter başlangıç alanı, aktif ürün yüzeyi değil |

Son yerel kalite koşumu: `699 passed, 6 skipped`; `ruff`, `mypy`, `bandit` ve
`pip-audit` policy gate geçti. Gerçek GPU/model ile production container smoke
ayrıca koşulmalıdır.

## İçindekiler

- [Öne Çıkanlar](#öne-çıkanlar)
- [Ölçülmüş Sonuçlar](#ölçülmüş-sonuçlar)
- [Mimari](#mimari)
- [Hızlı Başlangıç](#hızlı-başlangıç)
- [Production Deploy](#production-deploy)
- [API](#api)
- [LLM Modları](#llm-modları)
- [Test ve Kalite](#test-ve-kalite)
- [Klasör Yapısı](#klasör-yapısı)
- [Dokümantasyon](#dokümantasyon)

## Öne Çıkanlar

- Çoklu ajan akışı: triaj, mevzuat, emsal, draft, verify, debate, finalize,
  tahmin ve dilekçe düğümleri.
- Hibrit retrieval: BM25, BGE-M3 dense/sparse/ColBERT, RRF füzyon, opsiyonel
  rerank, RAPTOR ve GraphRAG.
- Kaynaklı cevap üretimi: cevap iddiaları citation ile bağlanır.
- Fail-closed doğrulama: production'da doğrulayıcı çökerse cevap reddedilir.
- Lokal LLM: production profili Qwen tabanlı `llama-server` kullanır; bulut LLM
  varsayılanı yoktur.
- KVKK odaklı güvenlik: PII maskeleme, audit log redaction, prompt-injection
  filtresi ve container hardening.
- Multimodal backend: OCR, STT ve TTS endpointleri.
- Tahmin modülü: BERT-TR tabanlı dava sonucu tahmini için eğitim, kalibrasyon ve
  inference pipeline'ı.

Kapsamlanan ana hukuk alanları: tüketici, iş hukuku, kira, icra, trafik, vergi,
tapu ve idari hukuk. Ceza ve aile hukuku kapsam dışıdır.

## Ölçülmüş Sonuçlar

Ölçüm detayları ve metodoloji:
[docs/theses/measured-results.md](docs/theses/measured-results.md)

| Metrik | Değer | Not |
|---|---:|---|
| Corpus | 159.362 vektör | 8 domain, mevzuat ve yargı kararları |
| Domain Accuracy @1 | %81.2 | 186 vaka benchmark |
| Domain Accuracy @5 | %97.3 | doğru domain top-5 içinde |
| MRR | 0.879 | mean reciprocal rank |
| Keyword recall | %78.2 | ground-truth keyword top-5 |
| Tahmin modeli | f1_macro 0.825 | BERT-TR, 3 sınıf |
| Kalibrasyon | ECE 0.0109 | temperature scaling sonrası |

Önemli bulgu: cross-encoder rerank bu corpus ve vatandaş dili sorgularında
domain@1 değerini iyileştirmedi, buna karşılık latency maliyetini belirgin
artırdı. Bu yüzden domain öncelikli tier-sort ve hibrit arama üretim yolu için
daha iyi maliyet/fayda dengesi veriyor.

## Mimari

```text
Client
  |
  v
Caddy TLS
  |
  v
FastAPI
  |
  +-- Auth, sanitize, PII mask, rate limit, audit
  |
  v
LangGraph agent pipeline
  |
  +-- Triaj
  +-- Mevzuat retrieval
  +-- Emsal retrieval
  +-- Draft
  +-- Verify
  +-- Debate
  +-- Tahmin / Dilekçe
  +-- Finalize
  |
  +-- Qdrant: hukuk vektörleri
  +-- PostgreSQL: feedback, api key, audit, eval kayıtları
  +-- Redis: session, rate limit, cache
  +-- llama-server: lokal Qwen LLM
```

Ayrıntılı mimari:
[docs/architecture.md](docs/architecture.md)

## Hızlı Başlangıç

Gereksinimler:

- Python 3.11
- uv
- Docker Desktop veya Docker Engine

### 1. Dev servislerini başlat

Dev compose yalnızca Qdrant ve Redis'i ayağa kaldırır; backend lokal çalışır.

```powershell
git clone https://github.com/cozalss/adalet-agent.git
cd adalet-agent

docker compose -f docker-compose.dev.yml up -d
```

### 2. Backend'i mock LLM ile çalıştır

```powershell
cd backend
uv sync --extra dev

$env:LLM_MODE = "mock"
$env:QDRANT_URL = "http://127.0.0.1:6333"
$env:REDIS_URL = "redis://127.0.0.1:6379/0"

uv run uvicorn main:app --reload --port 8000
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

### 3. Temel testleri çalıştır

```powershell
cd backend
uv run --extra dev pytest tests/ -q
uv run --extra dev ruff check .
uv run --extra dev mypy .
```

## Production Deploy

Production profili şunları başlatır:

- Qdrant
- Redis
- PostgreSQL
- Backend
- Caddy
- llama-server

Ön koşullar:

- NVIDIA GPU ve `nvidia-container-toolkit`
- `backend/models/<LLAMA_MODEL_FILE>` altında GGUF model dosyası
- `.env` içinde zorunlu secret değerleri
- Caddy TLS için doğru DNS kaydı

```bash
cp .env.example .env
# .env içindeki QDRANT_API_KEY, JWT_SECRET, REDIS_PASSWORD ve
# POSTGRES_PASSWORD değerlerini doldur.

docker compose --profile production --env-file .env up -d
docker compose --profile production ps
curl -fsSL https://staging.adalet.app/health
```

Staging adımları:
[docs/runbooks/deploy-staging.md](docs/runbooks/deploy-staging.md)

LLM kurulumu:
[docs/runbooks/llm-production-setup.md](docs/runbooks/llm-production-setup.md)

## API

| Method | Path | Auth | Açıklama |
|---|---|:---:|---|
| `GET` | `/health` | public | Derin sağlık kontrolü |
| `POST` | `/ask` | gerekli | Ana hukuk asistanı cevabı |
| `POST` | `/ask/stream` | gerekli | SSE ile aşamalı cevap |
| `DELETE` | `/ask/session/{id}` | gerekli | Konuşma geçmişini temizler |
| `POST` | `/multimodal/ocr` | gerekli | Belge görselinden metin çıkarır |
| `POST` | `/multimodal/stt` | gerekli | Sesi metne çevirir |
| `POST` | `/multimodal/tts` | gerekli | Metni sese çevirir |
| `POST` | `/auth/invite/{code}` | public | Davet kodundan JWT üretir |
| `GET` | `/auth/me` | gerekli | Kimlik bilgisini döndürür |
| `POST` | `/feedback` | gerekli | Kullanıcı geri bildirimi alır |

Örnek:

```http
POST /ask
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "question": "5 yıldır çalıştığım işten çıkarıldım, kıdem tazminatı alabilir miyim?"
}
```

## LLM Modları

| Mod | Kullanım |
|---|---|
| `mock` | Lokal geliştirme ve CI |
| `llamacpp_server` | Production önerisi, HTTP üzerinden `llama-server` |
| `llamacpp` | In-process llama.cpp, CUDA kurulumu gerektirir |

Production varsayılanı `llamacpp_server` olacak şekilde compose içinde
tanımlıdır. Dev/test için `.env` veya shell üzerinden `LLM_MODE=mock` verilebilir.

## Test ve Kalite

```powershell
cd backend

uv run --extra dev pytest tests/ -q
uv run --extra dev ruff check .
uv run --extra dev mypy .
uv run --extra dev bandit -r . -c pyproject.toml -ll -ii
uvx pip-audit --ignore-vuln CVE-2025-69872
```

CI iş akışı:
[.github/workflows/backend-ci.yml](.github/workflows/backend-ci.yml)

CI kapıları:

- lint ve type check
- pytest + coverage gate
- pip-audit + bandit
- Docker build smoke

## Veri ve Eval

Seed ve değerlendirme komutları backend dizininden çalışır:

```powershell
cd backend

uv run python -m scripts.seed_mevzuat
uv run python -m scripts.seed_hf_yargitay --shards 0,1,2 --cap-per-domain 2000
uv run python -m scripts.seed_danistay_hf --cap-per-domain 2000
uv run python -m scripts.eval_run --version v2 --rerank
```

Tahmin modeli pipeline'ı:

```powershell
cd backend

uv run python -m scripts.predictive.auto_label --cap-per-class 6000
uv run python -m predictive.train --data data/predictive/labeled_v2.jsonl
uv run python -m scripts.predictive.calibrate_model --data data/predictive/labeled_v2.jsonl
```

## Klasör Yapısı

```text
adalet-agent/
├── backend/
│   ├── agents/          LangGraph düğümleri ve ajan akışı
│   ├── api/             FastAPI routes, auth, PII, audit, limiter
│   ├── db/              PostgreSQL engine, modeller ve repository katmanı
│   ├── retrieval/       Qdrant, hybrid search, rerank, RAPTOR, GraphRAG
│   ├── verifier/        NLI, LettuceDetect, RARR
│   ├── multimodal/      OCR, STT, TTS
│   ├── predictive/      BERT-TR tahmin modeli
│   ├── eval/            benchmark ve ablation koşumları
│   ├── scripts/         seed, backup, smoke ve operasyon scriptleri
│   └── tests/           pytest suite
├── frontend/            placeholder, UI henüz yok
├── mobile/              Flutter çalışma alanı
├── docs/                mimari, ADR, runbook ve tez dokümanları
├── infra/               Caddy ve deploy altyapısı
├── docker-compose.yml   production stack ve production profili
├── docker-compose.dev.yml
└── scripts/bootstrap.ps1
```

## Güvenlik İlkeleri

- Hukuki kaynak uydurma yoktur; doğrulanamayan iddia reddedilir.
- Production'da `VERIFY_STRICT=1` ile fail-closed davranış hedeflenir.
- Production'da bulut LLM varsayılanı yoktur.
- Secret değerleri hardcode edilmez; `.env` ve secret guard kullanılır.
- PII maskeleme TCKN, telefon, e-posta, IBAN ve plaka gibi alanları kapsar.
- Container tarafında read-only filesystem, cap-drop ve no-new-privileges kullanılır.

## Dokümantasyon

- Mimari: [docs/architecture.md](docs/architecture.md)
- Ölçülmüş sonuçlar: [docs/theses/measured-results.md](docs/theses/measured-results.md)
- Staging deploy: [docs/runbooks/deploy-staging.md](docs/runbooks/deploy-staging.md)
- LLM production kurulumu: [docs/runbooks/llm-production-setup.md](docs/runbooks/llm-production-setup.md)
- Secret rotation: [docs/runbooks/secret-rotation.md](docs/runbooks/secret-rotation.md)
- ADR kayıtları: [docs/decisions/](docs/decisions/)

## Lisans

MIT. Ayrıntı için [LICENSE](LICENSE).

## Akademik Not

Bu proje Çankaya Üniversitesi Yazılım Mühendisliği bitirme projesi kapsamında
geliştirilmektedir. Hukuki doğruluk, kaynak gösterimi, ölçülebilir retrieval
kalitesi ve lokal veri işleme ana tasarım hedefleridir.
