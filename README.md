<div align="center">

# ⚖️ ADALET-AGENT

### Türkçe Hukuk için Çok Modlu, Çoklu-Ajan ve Doğrulamalı Yapay Zeka Vatandaş Asistanı

*Avukat tutamayan vatandaşa — **uydurmadan**, gerçek Yargıtay/Danıştay kararları ve mevzuatla **doğrulanmış**, **lokal** ve **açık kaynak** Türkçe hukuk yardımı.*

<br/>

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2-1C3C3C)](https://langchain-ai.github.io/langgraph/)
[![Qdrant](https://img.shields.io/badge/Qdrant-159k%20vektör-DC244C?logo=qdrant&logoColor=white)](https://qdrant.tech)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-compose-2496ED?logo=docker&logoColor=white)](https://docker.com)
<br/>
[![Tests](https://img.shields.io/badge/tests-705%20passing-success)](backend/tests)
[![ruff](https://img.shields.io/badge/ruff-passing-success?logo=ruff)](https://docs.astral.sh/ruff/)
[![mypy](https://img.shields.io/badge/mypy-strict%20(227)-blue)](https://mypy-lang.org)
[![bandit](https://img.shields.io/badge/bandit-clean-success)](https://bandit.readthedocs.io)
[![Lisans](https://img.shields.io/badge/Lisans-MIT-green)](LICENSE)

**`%81.2` retrieval@1 · `%97.3` @5 · `0.825` tahmin f1 · `159k` hukuk vektörü · `0` halüsinasyon hedefi**

*Çankaya Üniversitesi Yazılım Mühendisliği — Bitirme Projesi · 2026-2027*

</div>

---

<details>
<summary><b>📑 İçindekiler</b></summary>

- [Neden ADALET-AGENT?](#-neden-adalet-agent)
- [ChatGPT vs ADALET-AGENT](#-chatgpt-vs-adalet-agent)
- [Öne Çıkanlar](#-öne-çıkanlar)
- [Ölçülmüş Sonuçlar](#-ölçülmüş-sonuçlar)
- [Mimari](#-mimari)
- [Nasıl Çalışır — Bir Sorunun Yolculuğu](#-nasıl-çalışır--bir-sorunun-yolculuğu)
- [Örnek İstek & Yanıt](#-örnek-istek--yanıt)
- [Dava Sonucu Tahmini](#️-dava-sonucu-tahmini-bert-tr)
- [Kurulum](#-kurulum)
- [Teknoloji Yığını](#-teknoloji-yığını)
- [API Endpoint'leri](#-api-endpointleri)
- [Veritabanları & LLM Modları](#️-veritabanları--llm-modları)
- [Test & Kalite](#-test--kalite)
- [Klasör Yapısı](#-klasör-yapısı)
- [Mutlak Kurallar](#️-mutlak-kurallar)
- [Yol Haritası & Yarışmalar](#️-yol-haritası--yarışmalar)
- [Ekip & Lisans](#-ekip--lisans)

</details>

---

## 🎯 Neden ADALET-AGENT?

Türkiye'de milyonlarca vatandaş — tüketici, işçi, kiracı — basit bir hukuki soruya cevap ararken ya avukat parası ödeyemiyor ya da **yasa uyduran** genel amaçlı LLM'lere güveniyor.

> **Sorun:** ChatGPT/Gemini hukukta sık sık **var olmayan madde numarası ve karar referansı** üretir (halüsinasyon). Hukukta bu yalnız yanlış değil — **tehlikelidir.**

ADALET-AGENT bunu **iddia-doğrulamalı çoklu-ajan** mimarisiyle çözer: cevap içindeki **her yasal referans gerçek kaynaktan getirilir**, metin-eşleşmesiyle doğrulanır, **doğrulanamayan cevap reddedilir**.

> ### 🛡️ Sıfır Halüsinasyon İlkesi
> Hiçbir ajan, kaynağı doğrulanmamış bir iddia üretemez. Her madde/karar `mevzuat.gov.tr` veya yargı kaynağından fetch edilip token-düzeyinde eşleştirilir. Belirsizse cevap **reddedilir** → *"Bir avukata danışın."*

---

## ⚔️ ChatGPT vs ADALET-AGENT

| | 🤖 Genel LLM (ChatGPT/Gemini) | ⚖️ ADALET-AGENT |
|---|---|---|
| **Yasal referans** | Uydurabilir (halüsinasyon) | Gerçek kaynaktan fetch + **doğrulanır** |
| **Doğrulanamayan iddia** | Yine de sunulur | **Reddedilir** (fail-closed) |
| **Kaynak gösterimi** | Yok / yanlış | Her iddiaya `[src: …]` + URL |
| **Güven skoru** | Yok | Her yanıtta **kalibre** %X |
| **Veri** | Eğitim kesiti (eski) | **159k güncel** Yargıtay/Danıştay/mevzuat |
| **Gizlilik** | Bulut, log'lanır | **Lokal** model, KVKK-uyumlu, PII maskeli |
| **Şeffaflık** | Kapalı kutu | Açık kaynak + ajan-bazlı explainability |
| **Çok modlu** | Sınırlı | Belge fotoğrafı (OCR) + sesli (STT/TTS) |

---

## ✨ Öne Çıkanlar

- 🔍 **Hibrit retrieval** — BM25 (sparse) + BGE-M3 (dense) + ColBERT + RRF füzyon + cross-encoder rerank + domain tier-sort
- 🛡️ **4-katman doğrulama** — fuzzy eşleşme + LettuceDetect token-grounding + mDeBERTa NLI veto + Constitutional debate
- 🧩 **12-node LangGraph** — triaj → mevzuat∥emsal → draft → verify → debate → (tahmin/dilekçe) → finalize; retry'da **yeniden retrieval**
- ⚖️ **Dava sonucu tahmini** — BERT-TR fine-tune, 3-class, **f1_macro 0.825**, temperature-kalibre (ECE 0.011)
- 📚 **159k gerçek hukuk verisi** — Yargıtay 88k + Anayasa 46k + Danıştay 15k + mevzuat 7k + GİB özelge
- 🗣️ **Çok modlu** — OCR (Tesseract + Qwen2-VL) · STT (faster-whisper) · TTS (Piper)
- 🔒 **Production-hardened** — JWT + API-key (hash'li), IDOR fail-closed, security headers, PII maskeleme, rate-limit
- 🏠 **Lokal-only** — production'da bulut LLM YOK; Qwen 2.5 14B + tüm modeller lokal (KVKK)
- 🐳 **Tek-komut deploy** — `docker compose --profile production up -d` → TLS (Caddy) + GPU LLM (llama-server)

---

## 📊 Ölçülmüş Sonuçlar

<div align="center">

| Metrik | Değer | Açıklama |
|---|:---:|---|
| **Corpus** | `159.362` vektör | 8 hukuk alanı · Yargıtay+Danıştay+Anayasa+mevzuat+GİB |
| **Retrieval Accuracy @1** | **`%81.2`** | top-1 doğru domain (186-vaka benchmark) |
| **Retrieval Accuracy @5** | **`%97.3`** | top-5'te doğru domain |
| **MRR** | **`0.879`** | mean reciprocal rank |
| **Dava Sonucu Tahmini** | **`f1_macro 0.825`** | 3-class · acc %82.6 · ECE 0.011 (kalibre) |
| **Test** | `705` geçiyor | ruff ✅ · mypy strict (227 dosya) ✅ · bandit ✅ · pip-audit ✅ |

</div>

> 📈 **Mod karşılaştırması bulgusu:** Cross-encoder rerank, domain@1'i iyileştirmiyor ama ~10× latency getiriyor → **domain-öncelikli tier-sort** ile triaj prior'ı kullanılır. (Türkçe konuşma-dilinde cross-encoder gürültü tabanı verir.)

Tam ölçüm + metodoloji: [`docs/theses/measured-results.md`](docs/theses/measured-results.md)

---

## 🧠 Mimari

```
                              KULLANICI SORUSU
                          (web · mobil · belge · ses)
                                     │
                              ┌──────▼──────┐
                              │    TRİAJ     │  hangi hukuk alanı? (8 domain)
                              │   (Qwen)     │  ceza/aile → unknown (kapsam dışı)
                              └──────┬──────┘
                       ┌─────────────┴─────────────┐
                       ▼ (paralel)                  ▼
               ┌───────────────┐           ┌───────────────┐
               │ MEVZUAT Ajanı │           │  EMSAL Ajanı  │
               │ kanun maddesi │           │ Yargıtay/Dan. │
               │ +HyDE +rerank │           │ +tier-sort    │
               └───────┬───────┘           └───────┬───────┘
                       └─────────────┬─────────────┘
                                     ▼
                               ┌──────────┐
                               │  DRAFT   │  cevap taslağı + iddialar (Qwen 14B)
                               └────┬─────┘
                                    ▼
                        ┌────────────────────────┐
                        │  VERIFY — 4 katman      │  her iddiayı kaynakla eşleştir
                        │  fuzzy·Lettuce·NLI·grnd │
                        └───────────┬────────────┘
                                    ▼
                        ┌────────────────────────┐
                        │  DEBATE (hakem)         │  Constitutional self-critique
                        └───────────┬────────────┘
                  ┌─────────────────┼─────────────────┐
            retry │ (re-retrieve)   │ pass            │ reject
                  └─────────────────┘                 ▼
                                     ┌──────────────────────────┐
                                     │ [TAHMİN] [DİLEKÇE]        │  opsiyonel ajanlar
                                     │      → FİNALİZE            │  güven skoru + disclaimer
                                     └──────────────────────────┘
```

**Orkestrasyon:** LangGraph (12 node, persistent state). `retry → mevzuat+emsal RE-RETRIEVE` (HyDE stokastik olduğundan varyasyonlu yeniden arama), `MAX_RETRY` ile sınırlı, `merge_citations` dedup reducer ile.

---

## 🔬 Nasıl Çalışır — Bir Sorunun Yolculuğu

1. **Triaj** — Soru 8 hukuk alanından birine sınıflanır (güven skoru ile). Ceza/aile → `unknown`, kibarca reddedilir.
2. **Paralel retrieval** — Mevzuat ajanı kanun maddelerini, emsal ajanı Yargıtay/Danıştay kararlarını hibrit aramayla getirir.
3. **Draft** — Qwen 14B, **yalnız getirilen kaynaklardan** yapılandırılmış cevap üretir; her iddiaya `[src: …]` ekler.
4. **Verify (sıfır-halüsinasyon kapısı)** — Her iddia 4 katmandan geçer:

   | Katman | Yöntem | Rol |
   |---|---|---|
   | **L1 Fuzzy** | rapidfuzz pozitif eşleşme | hızlı yüzeysel destek |
   | **L2 LettuceDetect** | token-level grounding | iddia kaynakta gerçekten geçiyor mu? |
   | **L3 mDeBERTa NLI** | entailment / **contradiction veto** | kaynakla çelişen iddiayı **reddet** |
   | **L4 Debate** | Constitutional self-critique | hakem ajan nihai kararı verir |

5. **Debate** — Hakem ajan taslağı ilkeler karşısında eleştirir: `pass` / `retry` (yeniden retrieval) / `reject`.
6. **Finalize** — Güven skoru (kalibre) + zorunlu hukuki disclaimer + opsiyonel dava-sonucu tahmini + dilekçe taslağı.

---

## 💬 Örnek İstek & Yanıt

```http
POST /ask
Authorization: Bearer <jwt>
Content-Type: application/json

{ "question": "5 yıldır çalıştığım işten çıkarıldım, kıdem tazminatı alabilir miyim?" }
```

```jsonc
{
  "answer": "**Hukuki Çerçeve:** Kıdem tazminatı, en az 1 yıl çalışmış işçiye iş\n  sözleşmesi belirli sebeplerle sona erdiğinde her tam yıl için 30 günlük brüt\n  ücret olarak ödenir [src: ik-32].\n  **Şart Analizi:** 5 yıl > 1 yıl → kıdem şartı SAĞLANIYOR ...\n  **Yapılacaklar:** 1. İşverene yazılı talep ... 2. Sonuç alınmazsa İş Mahkemesi ...",
  "verdict": "pass",
  "confidence": 0.86,
  "citations": [
    { "source_id": "ik-32", "title": "4857 sayılı İş Kanunu — Kıdem",
      "url": "https://mevzuat.gov.tr/...", "score": 0.91 }
  ],
  "prediction": { "verdict_class": "kazandi", "confidence": 0.74,
                  "reasoning": "Benzer emsallerde işçi lehine eğilim ..." },
  "disclaimer": "Bu bilgilendirme amaçlıdır, kesin işlem için avukata danışın."
}
```

> Her cevapta: **verdict** (pass/retry/reject) · **kalibre güven** · **kaynaklı citation** · **disclaimer**. Doğrulanamayan iddialar cevaba girmez.

---

## ⚖️ Dava Sonucu Tahmini (BERT-TR)

Vatandaşın "açsam kazanır mıyım?" sorusunu yanıtlayan opsiyonel 8. ajan.

- **Model:** `dbmdz/bert-base-turkish-cased` + 3-class head (kazandı / kaybetti / kısmi)
- **Veri:** 613k Yargıtay kararından **leak-free silver-label** — model girdisi olay+gerekçe, etiket **hükümden** (model "cevabı okuyamaz" → dürüst tahmin)
- **Sonuç:** **f1_macro 0.825** · accuracy %82.6 · **ECE 0.011** (temperature scaling ile kalibre → "%X kazanırsın" gerçekten %X)
- **Bulgu:** dengeli 18k veri, ham 26k imbalanced'ı geçti (**denge > boyut**)
- **Pipeline:** `auto_label` (CPU) → `train` (GPU) → `calibrate` → `inference` (checkpoint varsa BERT, yoksa heuristic fallback)

> Tahmin asla mahkeme garantisi değildir; güven `≤0.85` ile sınırlı, verify/debate kapısını etkilemez (yalnız bilgilendirme).

---

## 🚀 Kurulum

### Yerel geliştirme (mock LLM, GPU gerekmez)

```powershell
git clone https://github.com/cozalss/adalet-agent.git
cd adalet-agent

# Bootstrap: Python + uv + Docker + modeller + test
.\scripts\bootstrap.ps1          # -SkipModels / -SkipDocker ile hızlandır

cd backend
uv run uvicorn main:app --reload  # → http://127.0.0.1:8000/docs (Swagger)
```

### Tek-komut production (TLS + gerçek LLM)

```bash
cp .env.example .env              # ZORUNLU secret'ları doldur (openssl rand -hex 32)
docker compose --profile production up -d
#  → qdrant · redis · postgres · backend · caddy (TLS) · llama-server (GPU Qwen)
```

> **Önkoşul:** NVIDIA GPU + nvidia-container-toolkit · `backend/models/<gguf>` · domain DNS (ACME TLS için).
> Çekirdek dev stack için profil olmadan: `docker compose up -d`.

---

## 🧰 Teknoloji Yığını

| Katman | Teknoloji |
|---|---|
| **API** | FastAPI · slowapi (rate-limit) · structlog · PyJWT |
| **Orkestrasyon** | LangGraph 1.2 · 12-node state graph |
| **LLM** | Qwen 2.5 14B (llama-cpp, lokal GPU) · MockLLM (dev) |
| **Retrieval** | Qdrant · BGE-M3 (dense+sparse+ColBERT) · BGE-reranker-v2-m3 · RAPTOR · GraphRAG |
| **Doğrulama** | mDeBERTa NLI · LettuceDetect · RARR-lite |
| **Tahmin** | BERT-TR (transformers + PyTorch) · temperature scaling |
| **Veritabanı** | PostgreSQL 16 (SQLModel + asyncpg + Alembic) · Redis · Qdrant |
| **Multimodal** | Tesseract 5 · faster-whisper · Piper |
| **DevOps** | Docker Compose · Caddy 2 (TLS) · GitHub Actions CI |
| **Değerlendirme** | Ragas · Langfuse · 186-vaka benchmark + verify ablation |

---

## 🌐 API Endpoint'leri

| Method | Path | Auth | Açıklama |
|---|---|:---:|---|
| `GET` | `/health` | public | Derinlemesine sağlık (qdrant+redis+llm) |
| `POST` | `/ask` | 🔒 | 12-ajan zinciri (JSON) |
| `POST` | `/ask/stream` | 🔒 | SSE — aşama aşama (per-node event) |
| `DELETE` | `/ask/session/{id}` | 🔒 | Konuşma geçmişini temizle |
| `POST` | `/multimodal/ocr` | 🔒 | Belge fotoğrafı → metin |
| `POST` | `/multimodal/stt` | 🔒 | Ses → metin |
| `POST` | `/multimodal/tts` | 🔒 | Metin → WAV |
| `POST` | `/auth/invite/{code}` | public | Davet kodu → JWT (gizlilik onayı) |
| `POST` | `/feedback` | 🔒 | 👍/👎 + yorum |

---

## 🗄️ Veritabanları & LLM Modları

| DB | Rol | Devreye |
|---|---|---|
| **Qdrant** | 159k vektör (hibrit arama) | her zaman |
| **PostgreSQL** | feedback · api_key · audit · eval | `DATABASE_URL` set ise (yoksa dosya fallback) |
| **Redis** | session · rate-limit · cache | `SESSION_STORE_KIND=redis` |

**`LLM_MODE`** (`.env`): `mock` (dev/test) · `llamacpp_server` (production, Qwen HTTP) · `llamacpp` (in-proc CUDA).
Gerçek LLM kurulumu → [`docs/runbooks/llm-production-setup.md`](docs/runbooks/llm-production-setup.md)

---

## ✅ Test & Kalite

```powershell
cd backend
uv run --extra dev pytest tests/ -q                       # 705 test
uv run --extra dev ruff check .                           # 0 hata
uv run --extra dev mypy .                                 # 227 dosya, 0 hata
uv run --extra dev bandit -r . -c pyproject.toml -ll -ii  # güvenlik
```

**CI** (`.github/workflows/backend-ci.yml`): lint+types → test+coverage (≥%80) → security (pip-audit `--strict` + bandit) → docker-build.

<details>
<summary>🌱 <b>Qdrant Seed & Eval komutları</b></summary>

```powershell
cd backend
uv run python -m scripts.seed_mevzuat                                  # kanun maddeleri
uv run python -m scripts.seed_hf_yargitay --shards 0,1,2 --cap-per-domain 2000
uv run python -m scripts.seed_danistay_hf --cap-per-domain 2000
uv run python -m scripts.eval_run --version v2 --rerank                # retrieval benchmark

# Tahmin modeli pipeline (CPU veri → GPU eğitim)
uv run python -m scripts.predictive.auto_label --shards 0,1,2,3,4,5,6,7,8 --cap-per-class 6000
uv run python -m predictive.train --data data/predictive/labeled_v2.jsonl
uv run python -m scripts.predictive.calibrate_model --data data/predictive/labeled_v2.jsonl
```

</details>

---

## 📁 Klasör Yapısı

```
adalet-agent/
├── backend/                 # FastAPI + LangGraph + RAG (Python 3.11)
│   ├── agents/              # 12-node: triaj·mevzuat·emsal·draft·verify·debate·finalize·tahmin·dilekçe
│   ├── api/                 # routes + auth (JWT/API-key) + rate-limit + PII + audit
│   ├── db/ · alembic/       # PostgreSQL (repository pattern, env-gated) + async migration
│   ├── retrieval/           # BGE-M3 hybrid + RAPTOR + GraphRAG + reranker + tier-sort
│   ├── multimodal/          # OCR (Tesseract) + STT (Whisper) + TTS (Piper)
│   ├── predictive/          # BERT-TR tahmin: data_loader·train·calibrate·inference (f1 0.825)
│   ├── verifier/            # NLI + LettuceDetect + RARR
│   ├── eval/                # benchmark runner + verify ablation + edge_cases + Ragas
│   ├── scripts/             # seed + bootstrap + predictive/auto_label + cron
│   └── tests/               # 705 test
├── mobile/                  # Flutter iOS+Android (yapım aşamasında)
├── docs/                    # ADR · runbooks · theses (ölçülmüş sonuçlar)
├── infra/Caddyfile          # production TLS reverse-proxy
├── docker-compose.yml       # dev + --profile production (Caddy + llama-server)
└── scripts/bootstrap.ps1    # sıfırdan kurulum (Windows)
```

---

## ⚠️ Mutlak Kurallar

| | Kural |
|:---:|---|
| 🚫 | **Hukuki referans uydurma** — şüpheliyse `[DOĞRULA: …]` placeholder, asla uydurma |
| 🔐 | **Test verisinde gerçek TCKN/telefon/isim YOK** — hep sahte (`Ayşe Yılmaz`, `0555-123-4567`) |
| 🏠 | **Production'da bulut LLM YOK** — yalnız lokal model (KVKK) |
| 🔑 | **Hardcoded secret YOK** — `.env` + zorunlu-secret guard |
| ⚖️ | **8 sivil hukuk alanı** (tüketici·iş·kira·icra·trafik·vergi·tapu·idari) — **ceza/aile kapsam dışı** |
| 🛡️ | **Production'da fail-closed** — `VERIFY_STRICT=1`, doğrulayıcı çökerse cevap reddedilir |

---

## 🗺️ Yol Haritası & Yarışmalar

| Hedef | Durum |
|---|---|
| Doğrulamalı 12-node RAG + 159k corpus | ✅ Çalışıyor (ölçüldü) |
| Dava sonucu tahmin modeli (BERT-TR) | ✅ Eğitildi (f1 0.825) |
| Production deploy (TLS + lokal LLM) | ✅ Tek-komut compose |
| Çok modlu (OCR/STT/TTS) | ✅ Backend · 🔜 mobil UI |
| **TÜBİTAK 2209-A** | 🎯 Başvuru |
| **Teknofest 2027** (Türkçe NLP) | 🎯 Hedef |
| Akademik makale (TIDE-TR / SIU) | 📝 Taslak |

---

## 👥 Ekip & Lisans

3 kişilik bitirme ekibi · **Çankaya Üniversitesi** Yazılım Mühendisliği · **MIT** lisansı (açık kaynak).

Tam vizyon & yol haritası: [`CLAUDE.md`](CLAUDE.md) · Mimari detay: [`docs/architecture.md`](docs/architecture.md) · Kararlar: [`docs/decisions/`](docs/decisions/)

---

<div align="center">

**⚖️ Hukuki tavsiye değildir — bilgilendirme amaçlıdır. Karmaşık durumlarda mutlaka bir avukata danışın.**

<sub>ADALET-AGENT · MIT · Türkçe hukuk için açık kaynak yapay zeka</sub>

</div>
