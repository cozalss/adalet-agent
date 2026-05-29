<div align="center">

# ⚖️ ADALET-AGENT

### Türkçe Hukuk için Çok Modlu, Çoklu-Ajan ve Doğrulamalı Yapay Zeka Vatandaş Asistanı

Avukat tutamayan vatandaşa (tüketici · işçi · kiracı) **uydurmadan**, **gerçek Yargıtay/Danıştay kararları ve mevzuatla doğrulanmış** Türkçe hukuk yardımı.

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2-1C3C3C)](https://langchain-ai.github.io/langgraph/)
[![Qdrant](https://img.shields.io/badge/Qdrant-159k%20vektör-DC244C?logo=qdrant&logoColor=white)](https://qdrant.tech)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://postgresql.org)
[![Lisans](https://img.shields.io/badge/Lisans-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-705-success)](backend/tests)
[![ruff](https://img.shields.io/badge/ruff-passing-success?logo=ruff)](https://docs.astral.sh/ruff/)
[![mypy](https://img.shields.io/badge/mypy-strict-blue)](https://mypy-lang.org)

*Çankaya Üniversitesi Yazılım Mühendisliği — Bitirme Projesi*

</div>

---

## 🎯 Neden?

Mevcut LLM'ler (ChatGPT, Gemini) hukukta **yasa uydurur** — madde numarası, karar referansı halüsine eder. Bu tehlikelidir. ADALET-AGENT bunu **iddia-doğrulamalı çoklu-ajan** mimarisiyle çözer: her yasal referans gerçek kaynaktan getirilir, **doğrulanamayan cevap reddedilir**.

> **Sıfır halüsinasyon ilkesi:** Hiçbir ajan kaynağı doğrulanmamış iddia üretemez. Her madde/karar mevzuat.gov.tr veya yargı kaynağından fetch + metin-eşleşmesiyle doğrulanır. Belirsizse → *"Bir avukata danışın."*

---

## 📊 Ölçülmüş Durum

<div align="center">

| Metrik | Değer | |
|---|---|---|
| **Corpus** | 159.362 vektör | 8 hukuk alanı, Yargıtay+Danıştay+Anayasa+mevzuat |
| **Retrieval Accuracy @1** | **%81.2** | top-1 doğru domain (186 vaka benchmark) |
| **Retrieval Accuracy @5** | **%97.3** | top-5'te doğru domain |
| **MRR** | **0.879** | mean reciprocal rank |
| **Dava Sonucu Tahmini** | **f1_macro 0.825** | BERT-TR, 3-class, ECE 0.011 (kalibre); 18k dengeli silver-label |
| **Test** | 705 | ruff ✅ · mypy strict (227 dosya) ✅ · bandit ✅ |

</div>

Ayrıntılı ölçüm: [docs/theses/measured-results.md](docs/theses/measured-results.md)

---

## 🧠 Mimari

```
                          KULLANICI SORUSU
                                │
                         ┌──────▼──────┐
                         │    TRİAJ     │  hangi hukuk alanı? (8 domain)
                         └──────┬──────┘
                  ┌─────────────┴─────────────┐
                  ▼ (paralel)                  ▼
          ┌───────────────┐           ┌───────────────┐
          │ MEVZUAT Ajanı │           │  EMSAL Ajanı  │
          │ kanun madde   │           │ Yargıtay/Dan. │
          │ +HyDE +rerank │           │ +tier-sort    │
          └───────┬───────┘           └───────┬───────┘
                  └─────────────┬─────────────┘
                                ▼
                          ┌──────────┐
                          │  DRAFT   │  cevap taslağı (Qwen 14B)
                          └────┬─────┘
                               ▼
                       ┌───────────────┐   4 katman:
                       │ VERIFY (doğr.)│   fuzzy + LettuceDetect +
                       └───────┬───────┘   mDeBERTa NLI + grounding
                               ▼
                       ┌───────────────┐
                       │ DEBATE (hakem)│   Constitutional self-critique
                       └───────┬───────┘
                  ┌────────────┼────────────┐
            retry │ (re-retrieve)           │ pass/reject
                  └────────────┘            ▼
                               ┌──────────────────────┐
                               │ [TAHMİN] [DİLEKÇE]    │  opsiyonel
                               │      → FİNALİZE        │  güven skoru + disclaimer
                               └──────────────────────┘
```

**Orkestrasyon:** LangGraph (12 node). `retry → mevzuat+emsal re-retrieve` (HyDE stokastik → varyasyonlu yeniden arama), `MAX_RETRY` ile sınırlı. Cross-encoder Türkçe konuşma-dilinde zayıf olduğundan **domain-öncelikli tier-sort** ile triaj prior'ı kullanılır.

---

## ✨ Öne Çıkanlar

- 🔍 **Hibrit retrieval** — BM25 (sparse) + BGE-M3 (dense) + ColBERT + RRF füzyon + cross-encoder rerank
- 🛡️ **4-katman doğrulama** — fuzzy + LettuceDetect token-grounding + mDeBERTa NLI + Constitutional debate
- 📚 **159k gerçek hukuk verisi** — Yargıtay (88k) + Anayasa (46k) + Danıştay (15k) + mevzuat (7k) + GİB özelge
- 🗣️ **Çok modlu** — OCR (Tesseract+Qwen2-VL) · STT (Whisper) · TTS (Piper) — belge fotoğrafı + sesli giriş
- 🔒 **Production-hardened** — JWT+API-key auth (hash'li), IDOR koruması, security headers, PII maskeleme (KVKK), rate-limit
- 🗄️ **PostgreSQL katmanı** — feedback + api_key + audit (env-gated, repository pattern, Alembic)
- 🏠 **Lokal-only** — production'da bulut LLM YOK; Qwen 2.5 14B + tüm modeller lokal (KVKK)

---

## 🚀 Quickstart (Windows, ~10 dk)

```powershell
# 1) Klonla
git clone https://github.com/cozalss/adalet-agent.git
cd adalet-agent

# 2) Bootstrap (Python+uv+Docker+modeller+test)
.\scripts\bootstrap.ps1

# 3) Backend başlat (MockLLM mode — dev default)
cd backend
uv run uvicorn main:app --reload

# 4) Tarayıcıda Swagger UI → http://127.0.0.1:8000/docs
```

Hızlı atlatma: `-SkipModels` (11 GB model indirimini atla) · `-SkipDocker` (container'ları manuel başlat)

---

## 🧰 Teknoloji Yığını

| Katman | Teknoloji |
|---|---|
| **API** | FastAPI · slowapi (rate-limit) · structlog · PyJWT |
| **Ajanlar** | LangGraph 1.2 · 12-node orkestrasyon |
| **LLM** | Qwen 2.5 14B (llama-cpp, lokal GPU) · MockLLM (dev) |
| **Retrieval** | Qdrant · BGE-M3 · BGE-reranker-v2-m3 · RAPTOR · GraphRAG |
| **Doğrulama** | mDeBERTa NLI · LettuceDetect · RARR |
| **Veritabanı** | PostgreSQL 16 (SQLModel+asyncpg+Alembic) · Redis (session/cache) |
| **Multimodal** | Tesseract · faster-whisper · Piper |
| **Değerlendirme** | Ragas · Langfuse · 186-vaka benchmark |

---

## 📁 Klasör Yapısı

```
adalet-agent/
├── backend/                 # FastAPI + LangGraph + RAG (Python 3.11)
│   ├── agents/              # triaj·mevzuat·emsal·draft·verify·debate·finalize·dilekçe·tahmin
│   ├── api/                 # FastAPI route + auth (JWT/API-key) + rate-limit + PII
│   ├── db/                  # PostgreSQL — engine + models + repositories (env-gated)
│   ├── alembic/             # DB migration (async)
│   ├── retrieval/           # BGE-M3 hybrid + RAPTOR + GraphRAG + reranker
│   ├── multimodal/          # OCR (Tesseract) + STT (Whisper) + TTS (Piper)
│   ├── predictive/          # Tahmin modeli (BERT-TR — eğitildi: f1_macro 0.825)
│   ├── verifier/            # NLI + LettuceDetect + RARR
│   ├── eval/                # Ragas + benchmark runner + verify kalibrasyon
│   ├── scripts/             # Seed (mevzuat/HF/Danıştay/GİB) + bootstrap + cron
│   └── tests/               # 705 test (api·agents·db·retrieval·verifier·multimodal)
├── mobile/                  # Flutter iOS+Android (Üye 2 — yapım aşamasında)
├── docs/
│   ├── decisions/           # ADR-001..009
│   ├── runbooks/            # Langfuse · LLM production · secret rotation · deploy
│   └── theses/              # Bitirme tezleri + ölçülmüş sonuçlar
├── data/                    # Eval benchmark + seed_state JSONL
├── docker-compose.yml       # Production stack (Qdrant + Redis + PostgreSQL + backend)
└── scripts/bootstrap.ps1    # Sıfırdan kurulum (Windows)
```

---

## 🗄️ Veritabanları

| DB | Rol | Devreye |
|---|---|---|
| **Qdrant** | 159k vektör (hibrit arama) | her zaman |
| **PostgreSQL** | feedback · api_key · audit · eval (kalıcı) | `DATABASE_URL` set ise (yoksa dosya fallback) |
| **Redis** | session (multi-turn) · rate-limit · cache | `SESSION_STORE_KIND=redis` |

**LLM mode** (`.env` → `LLM_MODE`): `mock` (local dev/test) · `llamacpp_server` (production Qwen 14B HTTP) · `llamacpp` (in-proc CUDA). Gerçek LLM: [docs/runbooks/llm-production-setup.md](docs/runbooks/llm-production-setup.md)

---

## 🌱 Qdrant Seed (gerçek retrieval için)

```powershell
cd backend
uv run python -m scripts.seed_mevzuat          # kanun maddeleri (~7k chunk)
uv run python -m scripts.seed_hf_yargitay --shards 0,1,2 --cap-per-domain 2000   # HF Yargıtay
uv run python -m scripts.seed_danistay_hf --cap-per-domain 2000                  # Danıştay (idari+vergi)
uv run python -m scripts.eval_run --version v2 --rerank   # benchmark ölçümü
```

---

## ✅ Test & Kalite

```powershell
cd backend
uv run --extra dev pytest tests/ -q                          # 705 test
uv run --extra dev ruff check .                              # 0 hata
uv run --extra dev mypy .                                    # 227 dosya, 0 hata
uv run --extra dev bandit -r . -c pyproject.toml -ll -ii     # güvenlik taraması
```

---

## ⚠️ Mutlak Kurallar

| | Kural |
|---|---|
| 🚫 | **Hukuki referans uydurma** — madde/karar şüpheliyse `[DOĞRULA: ...]` placeholder |
| 🔐 | **Test verisinde gerçek TCKN/telefon/isim YOK** — hep sahte (`Ayşe Yılmaz`, `0555-123-4567`) |
| 🏠 | **Production'da bulut LLM YOK** — yalnız lokal model (KVKK) |
| 🔑 | **Hardcoded secret YOK** — `.env` kullan |
| ⚖️ | **8 sivil hukuk alanı** (tüketici·iş·kira·icra·trafik·vergi·tapu·idari) — **ceza/aile kapsam dışı** (etik + yetkinlik), triaj `unknown` döndürür |

---

## 👥 Ekip & Kapsam

3 kişilik bitirme ekibi · Çankaya Üniversitesi · MIT lisans (açık kaynak).
Hedef: TÜBİTAK 2209-A · Teknofest 2027 (Türkçe NLP) · akademik makale.

Tam vizyon & yol haritası: [CLAUDE.md](CLAUDE.md) · Mimari: [docs/architecture.md](docs/architecture.md)

---

<div align="center">

**⚖️ Hukuki tavsiye değildir — bilgilendirme amaçlıdır. Karmaşık durumlarda avukata danışın.**

</div>
