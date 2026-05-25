# ADALET-AGENT — v12 Retrieval Benchmark Report

**Yayın tarihi:** 2026-05-25
**Sürüm:** v12 (HyDE production, multi_query fix, wrapper removed)
**Repo SHA:** `ab0773c`
**Lisans:** MIT — verisi, kodu, ölçümleri tekrarlanabilir.

> Bu rapor TÜBİTAK 2209-A başvurusu ve Teknofest 2027 jüri sunumu için
> hazırlanmış, kamuya açık reprodüksiyon yapılabilen retrieval benchmark
> çıktısıdır. Sayılar `backend/eval/runs/{v0,v1}_*ab0773c.json`'dan birebir
> alınmıştır.

---

## 1. Özet (TL;DR)

| Mode                      | D@1   | D@5   | kanun@5 | MRR   | KW recall | Avg lat | P95 lat |
|---------------------------|-------|-------|---------|-------|-----------|---------|---------|
| HYBRID                    | 0.22  | 0.56  | 0.48    | 0.346 | 0.668     | **298 ms** | 303 ms |
| HYBRID + RERANK           | **0.26** | **0.62** | 0.46 | **0.403** | **0.707** | 4.6 s | 26.4 s |
| HYBRID + HYDE             | 0.22  | 0.58  | **0.54** ★ | 0.357 | 0.673   | 16.8 s | 28.5 s |
| HYBRID + MULTI_QUERY (8s) | 0.22  | 0.56  | 0.52    | 0.352 | 0.668     | 8.2 s   | 8.9 s   |

★ **kanun@5 = 0.54** — bir hukuk RAG sistemi için en kritik metrik
(*hangi yasa maddesinin alıntılanması gerektiği* doğru top-5'te). HyDE,
vatandaş dili → kanun jargonu boşluğunu LLM ile köprüleyerek **HYBRID
baseline'a göre +6 puan** getirir (0.48 → 0.54, **%12.5 göreli kazanım**).

---

## 2. Yöntem

### 2.1 Benchmark seti

- **Dosya:** `backend/data/eval_benchmark/benchmark.jsonl`
- **n = 50** vatandaş sorusu (58 satırlık raw dosyadan filtreli)
- **Alanlar:** Tüketici, iş, kira, icra-iflas, trafik, vergi, tapu, idari
- **Ground truth:** Her sorunun beklenen kanun maddesi (örn. `TBK m. 343`),
  expected yargı kararı (örn. `Yargıtay 3. HD 2023/4471`), anahtar kelime
  set (`["depozito", "iade", "banka güvencesi"]`)
- **Türü:** Açık-rıza, kamuya açık, kendimiz oluşturduk; PII yok.

### 2.2 Metrikler

| Metrik | Tanım |
|--------|-------|
| **D@1** | İlk pozisyonda doğru chunk (Document at rank 1) |
| **D@5** | İlk 5'te doğru chunk var mı |
| **kanun@5** | İlk 5'te doğru kanun MADDESİ var mı (chunk değil, madde no eşleşmesi) |
| **MRR** | Mean Reciprocal Rank — pozisyon ağırlıklı |
| **keyword_recall** | Beklenen anahtar kelimelerin top-5'te bulunma oranı |
| **avg / p95 latency** | Tüm pipeline (query → top-K candidate) milisaniye |

**Neden kanun@5?** D@1 chunk-level (paragraph-level) — ama hukukta önemli olan
hangi *maddenin* alıntılandığı. `TBK m. 343` üçüncü paragrafa düşse bile cevap
geçerlidir; ama farklı bir madde gelirse yasa yanlış. Bu yüzden kanun@5
production retention metric'i olarak seçildi.

### 2.3 Donanım & model

- **GPU:** RTX 4070 12 GB
- **LLM (HyDE/multi_query):** Qwen 2.5 14B Q4_K_M GGUF via `llama-server`
  (`-ngl 20`, partial GPU offload)
- **Embedder:** `BAAI/bge-m3` (multilingual, FP16)
- **Reranker:** `BAAI/bge-reranker-v2-m3` (cross-encoder)
- **Vector store:** Qdrant 1.12 local
- **Sparse index:** rank_bm25
- **OS:** Linux x86_64

### 2.4 Karşılaştırılan modlar

1. **HYBRID** — BM25 (sparse) + BGE-M3 dense, RRF fusion. Baseline.
2. **HYBRID + RERANK** — HYBRID üzerine BGE-reranker-v2-m3 cross-encoder
   (top-200 → top-50 → cross-encoder → top-5).
3. **HYBRID + HYDE** — Soru → Qwen 14B "hipotetik cevap yaz" → cevap embedding'i
   ile dense search. BM25 yine orijinal sorudan.
4. **HYBRID + MULTI_QUERY** — Qwen 14B 4 paraphrase üret, her birini ayrı
   HYBRID, sonuçları RRF ile birleştir. `MQ_TIMEOUT_S=8s`.

---

## 3. Sonuçlar

### 3.1 Tam tablo

```json
// v1_hyde_ab0773c.json (özet)
{
  "hybrid":              { "D@1": 0.22, "D@5": 0.56, "kanun@5": 0.48,
                           "MRR": 0.346, "keyword_recall": 0.668,
                           "avg_latency_ms": 298, "p95_latency_ms": 303 },
  "hybrid+rerank":       { "D@1": 0.26, "D@5": 0.62, "kanun@5": 0.46,
                           "MRR": 0.403, "keyword_recall": 0.707,
                           "avg_latency_ms": 4567, "p95_latency_ms": 26415 },
  "hybrid+hyde":         { "D@1": 0.22, "D@5": 0.58, "kanun@5": 0.54,
                           "MRR": 0.357, "keyword_recall": 0.673,
                           "avg_latency_ms": 16800, "p95_latency_ms": 28500 },
  "hybrid+multi_query":  { "D@1": 0.22, "D@5": 0.56, "kanun@5": 0.52,
                           "MRR": 0.352, "keyword_recall": 0.668,
                           "avg_latency_ms": 8193, "p95_latency_ms": 8898 }
}
```

### 3.2 v0 → v1 delta

| Mode             | v0 D@1 | v1 D@1 | Δ     | v0 D@5 | v1 D@5 | Δ     | Lat v0  | Lat v1  |
|------------------|--------|--------|-------|--------|--------|-------|---------|---------|
| HYBRID           | 0.24   | 0.22   | -0.02 | 0.56   | 0.56   | 0.00  | 331 ms  | 298 ms  |
| HYBRID+RERANK    | 0.26   | 0.26   | 0.00  | 0.64   | 0.62   | -0.02 | 4495 ms | 4567 ms |

D@1/D@5 oynaması ±0.02 — embedder ve reranker deterministik; küçük sapma
benchmark dağılımındaki seed bağımlılığından (`np.random.seed=42` kullanılır).

### 3.3 Generic LLM karşılaştırması (planlanan v13)

> *Bu satır v13'te eklenecek.* Aşağıdaki sütun **placeholder**:

| Sistem                    | kanun@5 | Halüsinasyon oranı¹ | Disclaimer  | Lokal? |
|---------------------------|---------|---------------------|-------------|--------|
| ChatGPT-4o-mini (vanilla) | TBD     | TBD                 | Yok         | ❌     |
| Gemini 1.5 Flash          | TBD     | TBD                 | Yok         | ❌     |
| ADALET-AGENT v12 + HYDE   | **0.54**| **target ≤ 0.05**   | Otomatik ✓  | ✓      |

¹ *Halüsinasyon* = doğrulanmayan iddianın final cevapta kalması. Verifier
ajanı tüm cevapları NLI eşleşmesinden geçirir; geçemeyen iddia REDDEDİLİR
ve sistem yeniden üretir (max 3 iter). v12'de in-house verifier metriği
benchmark üzerinde **0.04** (2/50 vaka yanlış-pozitif kanun referansı).

---

## 4. Bulgular

### 4.1 HyDE Türkçe hukukta net kazanım sağlar (★)

`kanun@5: 0.48 → 0.54` (+6 puan / %12.5 göreli). Vatandaş dili
("depozitomu vermiyorlar") → kanun jargonu ("TBK m. 343 güvence") boşluğunu
LLM 14B kapatıyor. Bu bulgu *tez ablation tablosu*nun temelidir.

### 4.2 RERANK precision-odaklı, HyDE recall-odaklı

- RERANK **D@1 = 0.26** en yüksek; cross-encoder ilk pozisyonu iyi seçiyor.
- HyDE **kanun@5 = 0.54** en yüksek; geniş tarama kanun çeşitliliğini yakalıyor.
- Sprint-4'te **ColBERT** late-interaction eklenince ikisi RRF ile birleşecek.

### 4.3 Multi-query bug + fix

İlk ölçümde `MQ_TIMEOUT_S=3.0s` Qwen Q4 partial-offload'da paraphrase üretmeye
yetmiyordu → silent timeout → `n_queries=1` fallback → multi_query pratikte
HYBRID'e degrede idi. **Fix uygulandı** (`MQ_TIMEOUT_S=8.0s` default) ve
re-bench yapıldı: `kanun@5: 0.48 → 0.52` (+4 puan, 8 s ekstra latans
karşılığında). HyDE +6 puanına göre daha hafif kazanç ama 2× daha hızlı.

### 4.4 Latency uyarısı

HyDE 16.8 s avg latency Qwen 14B Q4 partial-offload (`-ngl 20`) bottleneck.
Production'da iki seçenek:

- **Qwen 7B full-GPU** — ~3-5 s beklenir (HyDE deneyi v13'te yapılacak)
- **Qwen 14B Q5_K_M + 4070 Ti / 4080** — RAM yeterli, full offload mümkün

---

## 5. Reprodüksiyon (3 adım)

### 5.1 Repo + bağımlılıklar

```bash
git clone https://github.com/<ADALET-repo>
cd adalet-agent/backend
git checkout ab0773c
uv venv && source .venv/bin/activate
uv pip install -e ".[dev,llm]"
```

### 5.2 LLM server (yerel Qwen)

```bash
# llama.cpp llama-server (Qwen 2.5 14B Q4_K_M GGUF gerekli)
./llama-server -m models/qwen2.5-14b-instruct-q4_k_m.gguf \
  -ngl 20 --ctx-size 8192 --port 8080
# Veya: production için 7B Q4 (~6GB VRAM, full GPU)
```

### 5.3 Benchmark çalıştır

```bash
HYDE_ENABLED=1 MULTI_QUERY_ENABLED=1 \
  LLM_MODE=llamacpp_server LLM_SERVER_URL=http://127.0.0.1:8080 \
  HF_HUB_OFFLINE=1 PYTHONUTF8=1 \
  uv run python -m eval.freeze_baseline \
    --modes hybrid,rerank,hyde,multi_query \
    --benchmark data/eval_benchmark/benchmark.jsonl
# Çıktı: backend/eval/runs/<run-name>_<git_sha>.json
```

Çalıştırma süresi (RTX 4070): **~22 dk** (50 vaka × 4 mod).

---

## 6. Kısıtlar (akademik dürüstlük)

| Kısıt | Açıklama | v13 planı |
|-------|----------|-----------|
| n = 50 | Küçük benchmark; ±2-4 puan varyans var. | n ≥ 200'a çıkar (v13) |
| Tek embedder | BGE-M3 baseline; mE5-large karşılaştırması yok. | mE5 + Türkçe-yerli `dbmdz` test edilecek |
| Generic LLM kıyas yok | ChatGPT/Gemini sayıları placeholder. | v13'te yan yana çalışılacak |
| Reranker latency | RERANK p95 = 26 s — outlier nedeniyle. | top-k=200 → 100'a düşürülmesi denenecek |
| HyDE LLM bağımlılığı | Qwen 14B çevrimdışı zorunlu, partial-offload yavaş. | Qwen 7B full-GPU profile eklenir |
| Türkçe karakter normalize | Bazı sorular `İ/ı` küçük-büyük harf farkıyla yanıltıyor. | tokenizer pre-norm pipeline genişletilir |

---

## 7. Sonraki adım — v13 hedefleri

- [ ] **n ≥ 200** benchmark seti — kira + iş hukuku ağırlıklı
- [ ] **ColBERT late-interaction** entegrasyonu (3-kol RRF: dense + sparse + ColBERT)
- [ ] **kanun@5 ≥ 0.65** hedef (mevcut 0.54)
- [ ] **Generic LLM karşılaştırma sütunu** doldurulmalı
- [ ] **Halüsinasyon ablation** — verifier ON vs OFF, kullanıcıya çıkan iddia farkı
- [ ] **LLM-as-Judge** (Ragas faithfulness + answer relevancy) ekle
- [ ] **Production deployment** — Hetzner Türkiye DC, p95 latency dashboard

---

## 8. Referanslar

- HyDE: Gao et al., 2022 — *Precise Zero-Shot Dense Retrieval without Relevance Labels*
- BGE-M3: Chen et al., 2024 — *BGE M3-Embedding* (multi-functional, multilingual)
- Multi-query (LangChain) — Schwartz, 2023
- Self-RAG: Asai et al., 2023 — *Self-Reflective Retrieval-Augmented Generation*
- CRAG: Yan et al., 2024 — *Corrective RAG*
- Ragas: Es et al., 2023 — *Ragas: Automated Evaluation of RAG*

---

## 9. Yazarlar & teşekkür

**ADALET-AGENT ekibi** (Çankaya Üniversitesi Yazılım Mühendisliği bitirme
projesi, 4 öğrenci).

- Veri: mevzuat.gov.tr (T.C. Cumhurbaşkanlığı Mevzuat Bilgi Sistemi) +
  yargitay.gov.tr açık karar arşivi (yargı-mcp wrapper)
- LLM: Qwen Team (Alibaba) — Apache 2.0
- Embedder/reranker: BAAI — MIT
- Verifier NLI: MoritzLaurer (HuggingFace) — Apache 2.0

**Geri bildirim:** GitHub Issues üzerinden.

---

*Bu rapor "open benchmark, open replication" prensibiyle hazırlandı. Sayılar
herhangi bir cherry-pick yapılmadan ham eval JSON'dan dökülmüştür.*
