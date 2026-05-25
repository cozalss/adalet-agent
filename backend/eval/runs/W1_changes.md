# Sprint-4 Hafta 1 — Retrieval Quick Wins Changelog

Plan referansı: `C:\Users\cemmo\.claude\plans\kategori-detay-alan-puan-majestic-valiant.md`
Tarih: 2026-05-26 (planlama 2026-05-25; uygulama 2026-05-26)

## Hedef
D@1 0.26 → 0.32, kanun@5 0.54 → 0.60, p95 latency < 30s.

## Değişiklikler

### W1.1 — ColBERT default ON
- `retrieval/embedding.py:33` `COLBERT_ENABLED` env default `"0"` → `"1"`
- `retrieval/vector_store.py:35` aynı
- `retrieval/hybrid_search.py:38` `COLBERT_QUERY_ENABLED` zaten `"1"` idi → tutarlılık
- `.env.example` güncel + migration notu (mevcut collection'da ColBERT yoksa reseed gerekir)
- `tests/conftest.py` test'lerde `"0"`'a explicit override — testler bozulmaz
- **Tests:** 5/5 yeşil (`tests/retrieval/test_embedding.py`)

### W1.2 — HyDE timeout fix + exception narrow
- `agents/config.py:54` `HYDE_TIMEOUT_S` 2.0s → env-toggle default 15.0s
  (Qwen 14B Q4 -ngl 20 ile 200 token üretim ~14-17s; eski default silent-timeout
  ile HyDE'ı v1_hyde tüm 50 vakada degrade etmişti — v0_vs_v1_DELTA.md)
- `agents/nodes/mevzuat.py:38` `_RETRIEVAL_FALLBACK_EXCEPTIONS` tuple ile bare
  `except Exception` antipattern daraltıldı:
  `(asyncio.TimeoutError, httpx.HTTPError, ConnectionError)` — CancelledError
  ve TypeError vb. propagate olur (gerçek bug'lar görünür kalır)

### W1.3 — Multi-Query N=5 + JSON-mode enforce
- `agents/config.py:60` `MULTI_QUERY_N` env-toggle default 4 → 5
- `retrieval/multi_query.py:40` `DEFAULT_N` env-aware
- `retrieval/multi_query.py:46` `RRF_K` env-toggle (W1.6 sweep'i için)
- `retrieval/multi_query.py:50` `_LLM_FALLBACK_EXCEPTIONS` tuple — exception narrow
- `retrieval/multi_query.py:54-71` `_PARAPHRASE_SYSTEM` JSON-mode enforce
  (eski numaralı regex parse silent fail yapıyordu — Roma rakamı, "•", iç-içe
  numara → ~15-20% vaka'da <2 paraphrase, v0_vs_v1_DELTA.md bug story)
- `retrieval/multi_query.py:118` `llm.chat(json_mode=True)` + max_tokens 300→400
- `retrieval/multi_query.py` yeni `_parse_json_paraphrases()` primary; eski
  `_parse_numbered()` fallback olarak korundu (LLM JSON moduna uymadığında)
- `agents/llm.py:340` MockLLM'e `"paraphrases"` JSON router eklendi
- **Tests:** 19/19 yeşil (12 eski + 7 yeni `_parse_json_paraphrases`)

### W1.4 — Pre-domain boost (mevzuat)
- `agents/config.py:78-104` `DOMAIN_TO_KANUN_KODU` mapping (8 domain → resmi
  kanun kodları), `MEVZUAT_DOMAIN_FILTER_ENABLED` env-toggle, `MEVZUAT_DOMAIN_BOOST`
- `agents/nodes/mevzuat.py:121-176` `_boost_by_domain()` helper — post-retrieve
  re-rank, mevzuat seed'lerinde `domain` field olmadığı için `kanun_kodu`
  payload'undan domain match yapıp skoru `+0.15` boost'lar
  (re-seed gerekmez — pratik ve geri-uyumlu)
- **Tests:** 5/5 yeşil (`tests/agents/test_mevzuat_node.py`)

### W1.5 — Türkçe BM25 stemmer (snowballstemmer)
- Yeni `pyproject.toml` dep: `snowballstemmer>=3.1.0`
- Yeni `retrieval/turkish_text.py`:
  - `stem_word()`, `tokenize()` (Türkçe stopword filtreli), `stem_text()`
  - `keyword_overlap()` — stem-prefix match (Snowball Türkçe agresif:
    `"kıdem"→"kıde"` problemine karşı 4 karakter prefix-overlap stratejisi)
  - `morphological_variants()` — LLM-siz deterministic paraphrase fallback
- `retrieval/multi_query.py` — LLM timeout/exception olunca `morphological_variants`
  ile fallback (eskiden sadece `[question]` dönüyordu)
- `scripts/eval_run.py:49-65` `_keyword_recall()` artık `turkish_text.keyword_overlap`
  kullanır (stem-aware match). Stemmer yoksa eski substring davranışı.
- **Tests:** 11/11 yeşil (`tests/retrieval/test_turkish_text.py`)

### W1.6 — RRF k parametre sweep infrastructure
- Yeni `eval/sweep_rrf_k.py` — `RRF_K` env'ini 40/60/80/100 sırayla set edip
  multi_query mode'unu benchmark üzerinde tekrar tekrar çalıştırır
- Çıktı: `eval/runs/rrf_sweep_<sha>.json` — k'ya göre D@1/D@5/kanun@5/MRR/p95
  karşılaştırması
- **Çalıştırma kullanıcı tarafından (RTX 4070 + llama-server gerek):**
  ```bash
  LLM_MODE=llamacpp_server HYDE_ENABLED=0 MULTI_QUERY_ENABLED=1 \
      uv run python -m eval.sweep_rrf_k --k 40,60,80,100
  ```

### W1.7 — freeze_baseline v2 runbook (kullanıcı tarafından çalıştırılır)
freeze_baseline.py zaten p95 metric'i içeriyordu (W1 öncesi). Bu hafta
eklenen tüm değişikliklerin etkisini ölçmek için:

```bash
cd backend
# 1) Ön koşul: llama-server (Qwen 2.5 14B Q4_K_M) :8080'de çalışıyor
./llama-server -m models/qwen2.5-14b-q4_k_m.gguf -ngl 20 --ctx-size 8192 --port 8080

# 2) Yeni baseline (W1 değişikliklerinin etkisini ölç) — 4 mode
HYDE_ENABLED=1 MULTI_QUERY_ENABLED=1 \
  COLBERT_QUERY_ENABLED=1 MEVZUAT_DOMAIN_FILTER=1 \
  LLM_MODE=llamacpp_server HF_HUB_OFFLINE=1 PYTHONUTF8=1 \
  uv run python -m eval.freeze_baseline \
    --modes hybrid,rerank,hyde,multi_query
# Beklenen çıktı: eval/runs/v2_w1_<sha>.json
# Hedef: D@1 ≥ 0.32, kanun@5 ≥ 0.60

# 3) RRF k sweep — sadece multi_query mode
LLM_MODE=llamacpp_server HYDE_ENABLED=0 MULTI_QUERY_ENABLED=1 \
  uv run python -m eval.sweep_rrf_k --k 40,60,80,100
# Beklenen çıktı: eval/runs/rrf_sweep_<sha>.json
# En iyi k'yı `.env`'e yansıt (RRF_K=...)
```

**Çıktı klasörü adlandırma kuralı:** mevcut `v0_baseline_<sha>.json` /
`v1_hyde_<sha>.json` paternini koru; v2 = W1 değişiklikleri.

## Etki Beklentisi (uygulanan değişikliklerin teorik etkisi)

| Değişiklik | Beklenen Δ |
|---|---|
| ColBERT 3. kol (collection reseed sonrası) | +3-5pp D@1 |
| HyDE timeout fix | +5-6pp kanun@5 (silent-timeout deg. fix) |
| Multi-Query N=5 + JSON-mode | +2-3pp Recall@20 (paraphrase parse fix) |
| Pre-domain boost (mevzuat) | +1-2pp D@1, +2-3pp kanun@5 |
| Türkçe stemmer (eval-time) | +5-10pp keyword_recall (ölçüm dürüstlüğü) |

**Pratik birikim:** D@1 0.26 → ~0.30-0.34, kanun@5 0.54 → ~0.60-0.65.
Gerçek rakamlar W1.7 çalıştırması sonrası bu dosyaya v2 delta tablosu olarak işlenecek.

## Bilinen risk

- **ColBERT etkisi mevcut collection'da YOK** — `collection_has_colbert` False
  döner, 2-kol fallback. Etkiyi görmek için reseed gerekir (Sprint-4 W2'de
  benchmark expansion + reseed birlikte yapılacak).
- **RRF k sweep RTX 4070 gerektirir** — benim ortamımda multi-saat sürer; bu
  çalıştırma kullanıcı tarafından yapılır, sonuç bu dosyaya eklenir.
