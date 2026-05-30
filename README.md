# ADALET-AGENT

[![CI](https://github.com/cozalss/adalet-agent/actions/workflows/backend-ci.yml/badge.svg)](https://github.com/cozalss/adalet-agent/actions/workflows/backend-ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-agent%20orchestration-1C3C3C)](https://langchain-ai.github.io/langgraph/)
[![Qdrant](https://img.shields.io/badge/Qdrant-vector%20search-DC244C?logo=qdrant&logoColor=white)](https://qdrant.tech)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

**Türkçe hukuk için kaynaklı, doğrulamalı ve lokal çalışan çoklu-ajan yapay zeka asistanı.**

ADALET-AGENT; mevzuat, Yargıtay, Danıştay ve Anayasa Mahkemesi verilerini hibrit
retrieval ile getirir, cevabı bir çoklu-ajan akışında üretir ve **her hukuki
iddiayı doğrulama katmanlarından geçirir**. Tasarım hedefi tek cümleyle: genel
amaçlı LLM'lerin hukukta yaptığı **madde/karar/kaynak uydurma** riskini ortadan
kaldırmak — doğrulanamayan iddiayı üretmek yerine reddetmek.

> ⚠️ Hukuki tavsiye değildir. Sistem bilgilendirme amaçlıdır; somut uyuşmazlıkta
> avukata danışılmalıdır.

---

## Neden farklı?

| | Genel amaçlı LLM | ADALET-AGENT |
|---|---|---|
| Kaynak | Hafızadan, doğrulanmaz | Her iddia gerçek mevzuat/karara `[src: …]` ile bağlanır |
| Uydurma maddesi | Mümkün | Doğrulama katmanı yakalar → düşürür veya reddeder |
| Eksik bilgi | Tahmin eder | **Clarifier** durup takip sorusu sorar |
| Kapsam dışı (ceza/aile) | Riskli cevap üretir | Nazikçe reddeder + yönlendirir |
| Veri | Buluta gider | **Tamamen lokal** (Qwen + Whisper + Piper) |
| Şeffaflık | Kara kutu | Güven skoru + kaynak listesi + açık kaynak |

---

## İçindekiler

- [Öne Çıkanlar](#öne-çıkanlar)
- [Ölçülmüş Sonuçlar](#ölçülmüş-sonuçlar)
- [Mimari](#mimari)
- [Karar Katmanı (Policy · Clarifier · Composer)](#karar-katmanı)
- [Doğrulama Katmanları](#doğrulama-katmanları)
- [Hızlı Başlangıç](#hızlı-başlangıç)
- [Production Deploy](#production-deploy)
- [API](#api)
- [LLM Modları](#llm-modları)
- [Test ve Kalite](#test-ve-kalite)
- [Veri ve Eval](#veri-ve-eval)
- [Klasör Yapısı](#klasör-yapısı)
- [Güvenlik İlkeleri](#güvenlik-i̇lkeleri)
- [Dokümantasyon](#dokümantasyon)

## Öne Çıkanlar

- **Çoklu-ajan akışı (LangGraph):** triaj → policy → {clarifier | retrieval} →
  draft → verify → debate → compose → finalize. Opsiyonel düğümler: CRAG,
  Self-RAG, tahmin, dilekçe, eligibility (hepsi ENV ile aç/kapa).
- **Deterministik karar katmanı:** üretimden önce "cevapla / netleştir /
  yönlendir / reddet" kararı tek bir saf fonksiyonda (`policy.py`, LLM yok).
- **Hibrit retrieval:** BM25 + BGE-M3 (dense/sparse/ColBERT) + RRF füzyon, domain
  öncelikli tier-sort; opsiyonel rerank, HyDE, multi-query, RAPTOR, GraphRAG.
- **4 katmanlı doğrulama + debate:** Rules → Fuzzy → LettuceDetect → NLI veto,
  ardından Constitutional self-critique. `VERIFY_STRICT=1` ile fail-closed.
- **Lokal LLM:** production profili Qwen 2.5 14B tabanlı `llama-server` kullanır;
  bulut LLM varsayılanı **yoktur**.
- **KVKK odaklı güvenlik:** PII maskeleme (TCKN/telefon/e-posta/IBAN/plaka),
  audit redaction, prompt-injection filtresi, container hardening.
- **Multimodal:** OCR (Tesseract), STT (Whisper), TTS (Piper) endpoint'leri.
- **Tahmin modülü:** BERT-TR tabanlı dava sonucu tahmini (eğitim + kalibrasyon +
  inference pipeline'ı).

**Kapsanan 8 sivil hukuk alanı:** tüketici · iş hukuku · kira · icra · trafik ·
vergi · tapu · idari. **Ceza ve aile hukuku kapsam dışıdır** (etik/risk kararı —
triaj bunları reddedip yönlendirir).

## Ölçülmüş Sonuçlar

Tüm sayılar gerçek ölçümdür; metodoloji:
[docs/theses/measured-results.md](docs/theses/measured-results.md)

| Metrik | Değer | Not |
|---|---:|---|
| Corpus | 159.362 vektör | 8 domain (Yargıtay, Anayasa, Danıştay, mevzuat) |
| Domain Accuracy @1 | %81.2 | 186 vaka benchmark |
| Domain Accuracy @5 | %97.3 | doğru domain top-5 içinde |
| MRR | 0.879 | mean reciprocal rank |
| Keyword recall | %78.2 | ground-truth keyword ∈ top-5 |
| Verify ayırt etme gücü | **+58.1 puan** | claim-support ON %41.9 vs OFF %100 (gerçek Qwen 14B) |
| Tahmin modeli | f1_macro 0.825 | BERT-TR, 3 sınıf (acc %82.6) |
| Kalibrasyon | ECE 0.0825 → **0.0109** | temperature scaling (T=1.56) |
| Retrieval gecikme | ~260 ms ort. | hybrid-only (rerank kapalı) |

> **Mühendislik bulgusu:** Cross-encoder rerank, bu corpus ve vatandaş dili
> sorgularında domain@1'i iyileştirmiyor (%81.7 → %81.2) ama ~10× gecikme
> getiriyor. Bu yüzden üretim yolu **domain öncelikli tier-sort + hibrit arama**
> kullanır — rerank yalnız opsiyonel. Ayrıca corpus'taki dev chunk'lar nedeniyle
> reranker `max_length=512` ile sınırlanmıştır (uçtan-uca gecikme ~5× düştü).

## Mimari

```text
Client (Web / Mobile / B2B)
   │
   ▼  Caddy TLS + güvenlik başlıkları
FastAPI  ── Auth · Sanitize · PII mask · Rate limit · Audit
   │
   ▼
LangGraph çoklu-ajan akışı
   │
   ├─ Triaj            (domain + response_intent + olgu çıkarımı)
   ├─ Policy           (deterministik karar — LLM yok)
   ├─ Clarifier        (eksik bilgide dur-ve-sor)
   ├─ Mevzuat ∥ Emsal  (paralel retrieval)
   ├─ Draft            (kaynaklı cevap üretimi)
   ├─ Verify           (4 katman doğrulama)
   ├─ Debate           (constitutional self-critique)
   ├─ Compose          (kapsam-dışı doğal yönlendirme)
   └─ Finalize         (güven skoru + disclaimer)
   │
   ├─ Qdrant       — hukuk vektörleri
   ├─ PostgreSQL   — feedback, api key, audit, eval kayıtları
   ├─ Redis        — session, rate limit, cache
   └─ llama-server — lokal Qwen LLM
```

Ayrıntılı mimari + sequence diyagramları: [docs/architecture.md](docs/architecture.md)

## Karar Katmanı

Sistemin omurgası, üretimden **önce** ne yapılacağına karar veren deterministik
bir katmandır. Bu karar eskiden triaj/verify/debate/finalize'a dağılmıştı; V2 ile
tek bir saf, test edilebilir fonksiyonda toplandı.

- **Policy Engine** (`agents/policy.py`) — `decide_path(state)` saf fonksiyon (LLM
  yok, aynı state → aynı karar). Beş yoldan birini seçer:
  `answer · clarify · redirect · reject_sensitive · smalltalk`.
- **Clarifier** (`agents/nodes/clarifier.py`) — olgu eksikse domain başına **sabit
  soru bankasından** 2-4 Türkçe takip sorusu sorar ve durur. Retrieval/draft'a hiç
  girmez → sıfır halüsinasyon yüzeyi. `CLARIFY_MARKER` loop-guard'ı sonsuz
  soru-sorma döngüsünü kapatır.
- **Composer** (`agents/nodes/compose.py`) — kapsam-dışı/hukuk-dışı soruyu
  cevaplamadan, sıcak bir yönlendirme metni üretir. Hukuki cevap yolunda no-op.
- **ResponseIntent** (`agents/state.py`): `legal_answer`, `needs_clarification`,
  `redirect_to_scope`, `smalltalk`, `out_of_scope_sensitive`, `reject_unverified`.

Örnek çok-turlu akış:

```text
Kullanıcı : Kira depozitomu alamıyorum.
Asistan   : (eksik bilgi → clarify) Sözleşme sona erdi mi? Evi teslim ettiniz mi? …
Kullanıcı : Evet, geçen ay sona erdi ve evi temiz teslim ettim.
Asistan   : (artık yeterli → answer) Kaynaklı, durumunuza özel hukuki yanıt.
```

## Doğrulama Katmanları

Her draft cümlesinden çıkarılan iddialar sırayla geçer:

| Katman | Yöntem | Görev |
|---|---|---|
| L1 — Rules | regex | Madde/karar referansının sentaktik geçerliliği |
| L2 — Fuzzy | rapidfuzz | Snippet eşleşmesi; iddianın söylediği madde corpus'ta yoksa **uydurma atıf** yakalanır |
| L2.5 — LettuceDetect | token-grounding (TR) | Cümlenin kaynakta gerçekten desteklenip desteklenmediği |
| L3 — NLI veto | mDeBERTa XNLI | Çelişki ≥ 0.70 → veto (kalibre-optimal eşik) |
| L4 — Debate | Constitutional self-critique | Bütünsel hakemlik; pass / retry / reject |

**Fail-closed:** `VERIFY_STRICT=1` iken doğrulayıcı (NLI/LettuceDetect) çökerse
cevap reddedilir — doğrulayıcı çalışmadıysa iddia "doğrulanmış" sayılamaz
(SIFIR HALÜSİNASYON ilkesi). Doğrulanamayan cümleler son cevaptan çıkarılır.

## Hızlı Başlangıç

**Gereksinimler:** Python 3.11 · [uv](https://docs.astral.sh/uv/) · Docker

### 1. Dev servislerini başlat (Qdrant + Redis)

```bash
git clone https://github.com/cozalss/adalet-agent.git
cd adalet-agent
docker compose -f docker-compose.dev.yml up -d
```

### 2. Backend'i mock LLM ile çalıştır

```bash
cd backend
uv sync --extra dev

# PowerShell:  $env:LLM_MODE="mock"
# bash:        export LLM_MODE=mock
uv run uvicorn main:app --reload --port 8000
```

Swagger UI: `http://127.0.0.1:8000/docs` · Sağlık: `http://127.0.0.1:8000/health`

### 3. Testleri çalıştır

```bash
cd backend
uv run --extra dev pytest tests/ -q
uv run --extra dev ruff check .
uv run --extra dev mypy .
```

## Production Deploy

Production profili tam yığını başlatır: **Qdrant · Redis · PostgreSQL · Backend ·
Caddy (TLS) · llama-server**.

Ön koşullar: NVIDIA GPU + `nvidia-container-toolkit` · `backend/models/` altında
GGUF model dosyası · `.env` içinde zorunlu secret'lar (JWT_SECRET, POSTGRES_PASSWORD,
REDIS_PASSWORD, QDRANT_API_KEY) · Caddy TLS için DNS kaydı.

```bash
cp .env.example .env          # secret değerlerini doldur
docker compose --profile production --env-file .env up -d
docker compose --profile production ps
```

Adımlar: [docs/runbooks/deploy-staging.md](docs/runbooks/deploy-staging.md) ·
LLM kurulumu: [docs/runbooks/llm-production-setup.md](docs/runbooks/llm-production-setup.md)

## API

| Method | Path | Auth | Açıklama |
|---|---|:---:|---|
| `GET` | `/health` | public | Derin sağlık kontrolü |
| `POST` | `/ask` | gerekli | Ana hukuk asistanı cevabı |
| `POST` | `/ask/stream` | gerekli | SSE ile aşamalı cevap (event sözleşmesi v1) |
| `DELETE` | `/ask/session/{id}` | gerekli | Konuşma geçmişini temizler |
| `POST` | `/multimodal/ocr` | gerekli | Belge görselinden metin çıkarır |
| `POST` | `/multimodal/stt` | gerekli | Sesi metne çevirir |
| `POST` | `/multimodal/tts` | gerekli | Metni sese çevirir |
| `GET` | `/api/dilekce/{conversation_id}` | gerekli | Üretilen dilekçe PDF'ini indirir |
| `DELETE` | `/api/dilekce/{conversation_id}` | gerekli | Dilekçe PDF'ini siler |
| `POST` | `/auth/invite/{code}` | public | Davet kodundan JWT üretir |
| `GET` | `/auth/me` | gerekli | Kimlik bilgisini döndürür |
| `POST` | `/feedback` | gerekli | Kullanıcı geri bildirimi alır |

`/ask/stream` SSE event'leri: `triage` (intent + domain), `clarify`, `sources`,
`drafting`, `node`, `final`, `error` — her biri `v: 1` şema sürümü taşır.

```http
POST /ask
Authorization: Bearer <jwt>
Content-Type: application/json

{ "question": "5 yıldır çalıştığım işten çıkarıldım, kıdem tazminatı alabilir miyim?" }
```

## LLM Modları

| Mod | Kullanım |
|---|---|
| `mock` | Lokal geliştirme ve CI (kod fallback varsayılanı) |
| `llamacpp_server` | **Production önerisi** — HTTP üzerinden ayrı `llama-server` process'i |
| `llamacpp` | In-process llama.cpp (CUDA gerektirir; tek-process basit dev) |

> Production'da `llama-server` ayrı bir process/container'da koşar; retrieval'ın
> (BGE-M3, reranker — CPU) llama.cpp ile aynı süreçte CPU thread yarışına girmesini
> önler. Bu izolasyon ölçülen uçtan-uca gecikmeyi belirgin düşürür.

## Test ve Kalite

```bash
cd backend
uv run --extra dev pytest tests/ -q                 # 787 passed, 6 skipped
uv run --extra dev ruff check .                      # geniş strict kural seti
uv run --extra dev mypy .                            # strict
uv run --extra dev bandit -r . -c pyproject.toml -ll -ii
uvx pip-audit --ignore-vuln CVE-2025-69872
```

CI ([.github/workflows/backend-ci.yml](.github/workflows/backend-ci.yml)) dört
kapı koşar: **lint + types · pytest + coverage gate (≥%80) · pip-audit + bandit ·
Docker build smoke.** Mevcut coverage: ~%89.

## Veri ve Eval

Seed ve değerlendirme komutları `backend/` dizininden çalışır:

```bash
uv run python -m scripts.seed_mevzuat
uv run python -m scripts.seed_hf_yargitay --shards 0,1,2 --cap-per-domain 2000
uv run python -m scripts.eval_run --version v2            # retrieval benchmark
uv run python -m eval.policy_eval                         # karar-katmanı eval
uv run python -m eval.draft_quality                       # draft kalite (gerçek LLM)
```

Eval setleri (`backend/data/eval_benchmark/`):

| Set | Vaka | Ölçtüğü |
|---|---:|---|
| `benchmark_v2.jsonl` | 186 | retrieval domain/keyword |
| `answer_cases.jsonl` | 100 | genel soru doğrudan cevaplanıyor mu (over-clarify kalkanı) |
| `multiturn_cases.jsonl` | 50 | clarify → answer ilerlemesi |
| `out_of_scope_cases.jsonl` | 30 | ceza/aile/smalltalk yönlendirme |
| `prompt_injection_cases.jsonl` | 20 | injection dayanıklılığı |
| `verify_gold.jsonl` | 59 | doğrulama kalibrasyonu |

Tahmin modeli pipeline'ı:

```bash
uv run python -m scripts.predictive.auto_label --cap-per-class 6000
uv run python -m predictive.train --data data/predictive/labeled_v2.jsonl
uv run python -m scripts.predictive.calibrate_model --data data/predictive/labeled_v2.jsonl
```

## Klasör Yapısı

```text
adalet-agent/
├── backend/
│   ├── agents/          LangGraph düğümleri + policy + clarifier + compose
│   ├── api/             FastAPI routes, auth, PII, audit, limiter
│   ├── db/              PostgreSQL engine, modeller, repository (dosya-fallback)
│   ├── retrieval/       Qdrant, hybrid search, rerank, RAPTOR, GraphRAG
│   ├── verifier/        NLI, LettuceDetect, RARR
│   ├── multimodal/      OCR, STT, TTS
│   ├── predictive/      BERT-TR tahmin modeli
│   ├── eval/            benchmark, policy_eval, draft_quality, ablation
│   ├── scripts/         seed, backup, smoke ve operasyon scriptleri
│   └── tests/           pytest suite (787+)
├── frontend/            placeholder — UI henüz uygulanmadı
├── mobile/              Flutter çalışma alanı — aktif ürün yüzeyi değil
├── docs/                mimari, ADR, runbook ve tez dokümanları
├── infra/               Caddy ve deploy altyapısı
├── docker-compose.yml   production stack + production profili
└── docker-compose.dev.yml
```

## Güvenlik İlkeleri

- **Sıfır halüsinasyon:** hukuki kaynak uydurma yoktur; doğrulanamayan iddia reddedilir.
- Production'da `VERIFY_STRICT=1` ile fail-closed davranış hedeflenir.
- Production'da **bulut LLM varsayılanı yoktur** (yalnız lokal model).
- Secret'lar hardcode edilmez; `.env` + secret guard kullanılır.
- PII maskeleme TCKN, telefon, e-posta, IBAN ve plaka alanlarını kapsar.
- Container: read-only filesystem, cap-drop ALL, no-new-privileges.
- Test/örnek verilerde gerçek kişisel veri yoktur (sahte: "Ayşe Yılmaz" vb.).

## Dokümantasyon

- Mimari: [docs/architecture.md](docs/architecture.md)
- Ölçülmüş sonuçlar: [docs/theses/measured-results.md](docs/theses/measured-results.md)
- Staging deploy: [docs/runbooks/deploy-staging.md](docs/runbooks/deploy-staging.md)
- LLM production kurulumu: [docs/runbooks/llm-production-setup.md](docs/runbooks/llm-production-setup.md)
- Secret rotation: [docs/runbooks/secret-rotation.md](docs/runbooks/secret-rotation.md)
- ADR kayıtları: [docs/decisions/](docs/decisions/)

## Lisans

MIT — ayrıntı için [LICENSE](LICENSE).

## Akademik Not

Bu proje Çankaya Üniversitesi Yazılım Mühendisliği bitirme projesi kapsamında
geliştirilmektedir. Hukuki doğruluk, kaynak gösterimi, ölçülebilir retrieval
kalitesi ve lokal veri işleme ana tasarım hedefleridir.
