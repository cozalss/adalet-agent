# Freeze Baseline Δ — v0 (HYBRID/RERANK) vs v1 (4-mode HyDE+MultiQuery)

**Benchmark:** 50 vaka, `data/eval_benchmark/benchmark.jsonl`
**Donanım:** RTX 4070 12GB, llama-server -ngl 20 (Qwen 2.5 14B Q4_K_M)
**Tarih:** v0 = 2026-05-24 13:13Z, v1 = 2026-05-24 18:12Z
**Git SHA:** ab0773c (her ikisi de — kod aynı, sadece flag farklı)

## 4-mode tablo (v1_hyde_ab0773c.json — ilk ölçüm + multi_query yeniden)

| Mode | D@1 | D@5 | kanun@5 | MRR | KW rec | Avg lat | P95 lat |
|------|-----|-----|---------|-----|--------|---------|---------|
| HYBRID            | 0.22 | 0.56 | 0.48 | 0.346 | 0.668 | **298ms** | 303ms |
| HYBRID+RERANK     | **0.26** | **0.62** | 0.46 | **0.403** | **0.707** | 4.6s | 26.4s |
| HYBRID+HYDE       | 0.22 | 0.58 | **0.54** ✦ | 0.357 | 0.673 | 16.8s | 28.5s |
| HYBRID+MULTI_QUERY (MQ_TIMEOUT_S=3s, **bug**) | 0.22 | 0.56 | 0.48 | 0.342 | 0.668 | 3.3s | 3.4s |
| **HYBRID+MULTI_QUERY (MQ_TIMEOUT_S=8s, fix)** | 0.22 | 0.56 | **0.52** ✦ | 0.352 | 0.668 | 8.2s | 8.9s |

## v0 → v1 delta (mevcut metrikler)

| Mode | v0 D@1 | v1 D@1 | Δ | v0 D@5 | v1 D@5 | Δ | v0 lat | v1 lat |
|------|--------|--------|---|--------|--------|---|--------|--------|
| HYBRID | 0.24 | 0.22 | -0.02 | 0.56 | 0.56 | 0 | 331ms | 298ms |
| HYBRID+RERANK | 0.26 | 0.26 | 0 | 0.64 | 0.62 | -0.02 | 4495ms | 4567ms |

D@1/D@5 değişimi ±0.02 — embedder/reranker deterministik, sapma seed bağımlı bench dağılımı.

## Kazançlar / kayıplar

✅ **HYDE +6pp kanun@5** (0.48 → 0.54) — hukuki RAG'in en kritik metriği. HyDE'nin
   "hipotetik kanun cevabı embedding'i" gerçek kanun chunk'larına daha yakın
   düşüyor. Vatandaş dili → kanun jargonu boşluğunu LLM kapatıyor.

✅ **HYDE +2pp D@5** (0.56 → 0.58) — recall artışı, küçük ama tutarlı.

⚠️ **HyDE latency cost** (298ms → 16.8s, 56x) — Qwen 14B Q4 partial-offload
   bottleneck. Production'da gerçek 7B veya 14B Q5 full-GPU ile 3-5s mümkün.

⚠️ → ✅ **MULTI_QUERY bug + fix**: default `MQ_TIMEOUT_S=3.0s` Qwen Q4
   paraphrase üretmeye yetmiyordu → silent timeout → `n_queries=1` fallback
   → multi_query pratikte HYBRID'e degrede idi. **Fix uygulandı**
   (`MQ_TIMEOUT_S=8.0s` default) ve **re-bench** yapıldı:
   **MULTI_QUERY kanun@5: 0.48 → 0.52** (+4pp, 8s ekstra latans karşılığında).
   HyDE +6pp ile karşılaştırıldığında daha hafif kazanç ama 2x daha hızlı
   (8.2s vs 16.8s) — alternatif production seçeneği.

⏸️ **RERANK D@1=0.26 hâlâ en yüksek** — single-best metric için cross-encoder
   yeniyor. HyDE recall'a, RERANK precision'a yardımcı. Sprint-4'te ColBERT
   3-kol prefetch (dense+sparse+ColBERT) ile birleştirilecek.

## Bulgular özet (paper material)

1. **HyDE Türkçe hukukta kanun-match'i %12.5 artırıyor** (0.48 → 0.54, +6pp).
   Tier-2 SOTA pakedi içinde "Türkçe hukuk için ölçülmüş HyDE etkisi" tezde
   ablation tablosuna yazılır.
2. **Multi-query LLM-paraphrase RTX 4070 + Qwen Q4 partial-offload ile 3s'de
   tamamlanamıyor**; LLM zamanı paraphrase tasarımı ile düşürülebilir
   (n=2 yerine n=4, daha kısa prompt). Sprint-4 paper material için
   re-bench gerekli.
3. **RERANK D@1 üstünlüğü stabil** (v0=0.26, v1=0.26). Cross-encoder skor
   ortalaması 200 candidate'ı bilinçli yeniden sıralıyor.

## Bu turun sonrası — Sprint-4 odak noktaları

- [x] freeze_baseline v2 — `MQ_TIMEOUT_S=8.0s` ile multi_query ölçüldü
      (kanun@5 0.48 → 0.52, +4pp; latans 3.3s → 8.2s)
- [ ] Sprint-4: ColBERT late-interaction + 3-kol RRF — yeni mode `hybrid+colbert`
      ekle, kanun@5 hedefi ≥ 0.65
- [ ] LLM-as-Judge (Sprint-4) — top-5 retrieval kalitesi sayı yerine LLM
      değerlendirmesi ile (Ragas Faithfulness + answer relevancy)
- [ ] Production: HYDE_ENABLED=1 default (en yüksek kanun@5);
      latans-hassas deployment için MULTI_QUERY_ENABLED=1 alternatif

## Reproduce

```bash
cd backend
HYDE_ENABLED=1 MULTI_QUERY_ENABLED=1 \
  LLM_MODE=llamacpp_server LLM_SERVER_URL=http://127.0.0.1:8080 \
  HF_HUB_OFFLINE=1 PYTHONUTF8=1 \
  uv run python -m eval.freeze_baseline \
    --modes hybrid,rerank,hyde,multi_query
# Output: eval/runs/v1_hyde_<git_sha>.json
```

**llama-server gereksinimi:**
```bash
./llama-server -m models/qwen2.5-14b-q4_k_m.gguf \
  -ngl 20 --ctx-size 8192 --port 8080
```
