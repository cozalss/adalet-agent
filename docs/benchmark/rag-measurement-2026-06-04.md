# RAG Ölçüm Raporu — 2026-06-04 (ölçüm-sürücülü iyileştirme)

> 186-vaka benchmark (`benchmark_v2.jsonl`), `adalet_mursit_hybrid` koleksiyonu (159.769 nokta),
> Mursit dense + BGE-M3 sparse. LLM gerekmez (hybrid/rerank mode). Yeni **madde_recall@5** metriği
> = "doğru MADDEYİ getirdik mi" (domain@1 'doğru ALAN'ı ölçer, abartılı proxy). Üret:
> `cd backend && uv run python -m scripts.run_baseline --mode rerank`

## Headline bulgu: query-time `doc_type=law` filtresi → madde_recall@5 +15.2pp (ÖLÇÜLDÜ)

| Aşama | madde_recall@5 | kanun@5 | domain@1 |
|-------|:--:|:--:|:--:|
| Ham baseline (hybrid) | %19.7 | %51 | %80 |
| Ham baseline (rerank) | %21.8 | %48 | %83 |
| **+ doc_type=law (hybrid)** | **%35.4** | %83 | %83 |
| **+ doc_type=law (rerank) ← PRODUCTION** | **%37.0** | %82 | %83 |

**Kök neden:** corpus %64 case-law (anayasa bireysel başvuru). mevzuat_node retrieve-SONRA-post-filter
yapıyordu → case-law chunk'ları top-K'yı doldurup mevzuat maddelerini HAVUZDAN ÇIKARIYORDU; post-filter
çıkmış maddeyi kurtaramıyor. Query-time `doc_type=law` (Qdrant FieldCondition) tüm slotları law yapar.
**Commit 7b07002 — production'a uygulandı** (5 retrieval çağrısı; emsal case-law kolu AYRI).

### Domain-bazlı (rerank + law-filter, production):
icra %37 · isHukuku %36 · vergi %25 · kira %28 · tüketici %64 · trafik %22 · idari %20 · **tapu %10**

## Test edilen ama işe yaramayan hipotezler (ölçümle elendi)
- **candidates_n 20→50:** madde_recall %21.8 → %21.2 (DÜŞTÜ). Darboğaz havuz değil → CE'nin kendisi
  (daha çok aday = daha çok gürültü). Knob: `EVAL_RERANK_CANDIDATES`.
- **CE rerank on/off:** law-filtreli sonuçlarda CE +1.6pp net-pozitif (domain-karışık: icra/isHukuku/
  tüketici'de yardımcı, vergi/kira/trafik'te zararlı). KORUNUR (net-pozitif).

## Kalan zayıf noktalar + sonraki lever
- **tapu %10, idari %20:** law-filtre sonrası bile düşük. tapu kanun@5=%70 (doğru kanun) ama madde %10 =
  "doğru kanun, yanlış madde" → **chunk granülerliği (#2, commit 5ede892)**. chunk_mevzuat uzun-madde
  alt-bölme YAPILDI ama **RE-SEED gerektiriyor** (seed_mevzuat mevzuat.gov.tr'den canlı fetch eder).
  Re-seed sonrası bu domainlerde madde_recall artışı beklenir.
- **trafik domain@1 %45 (rerank):** rerank trafik'i bozuyor (hybrid %73) → domain-seçici rerank ablasyonu.

## Ölçüm altyapısı (kullanıcı koşar)
- `scripts/run_baseline.py --mode {hybrid,rerank}` — domain-bazlı madde_recall@5.
- `EVAL_DOC_TYPE=law` / `EVAL_RERANK_CANDIDATES=N` — ablation knob'ları.
- `scripts/demo_measure_rag.py` — hızlı 8-vaka demo. `eval/rerank_cutoff_sweep.py` — cutoff sweep.
- `HYBRID_FUSION=dbsf` — DBSF füzyon A/B. `scripts/exp_law_filter.py` — law-filter A/B deneyi.
