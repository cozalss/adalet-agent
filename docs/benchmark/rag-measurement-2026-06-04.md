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

## #2 chunk sub-split: ÖLÇÜMLE REDDEDİLDİ (değerli negatif sonuç)
Scoped re-seed testi (7293 law chunk → 12267 sub-chunk → test koleksiyonu → benchmark,
`scripts/exp_subchunk_reseed.py`): madde_recall@5 %35.4 → **%36.6 (+1.2pp net, KARIŞIK)**.
tüketici %53→%71 (+18pp) AMA **icra %33→%25, vergi %38→%25 DÜŞTÜ.** Neden: overlap'li sub-split
çok-maddeli vakalarda (icra [32,33]) tek maddenin 3-4 overlapping sub-chunk'ını top-5'e doldurup
DİĞER beklenen maddeleri itiyor. **→ Production re-seed DEĞMEZ** (ağır + marjinal + icra/vergi'yi bozar).
Ölçüm bizi yanlış bir corpus-rebuild'den kurtardı. (chunk_mevzuat fix commit 5ede892 kodda kalır —
zararsız, default-safe; ama production'a re-seed ÖNERİLMEZ.)

## Kalan zayıf noktalar (diminishing returns — daha ağır iş gerektirir)
- **"Yanlış KANUN" vakaları** (V_idari_009/010 IYUK→DMK, V_tapu_004/006 TMK→KMK/HMK): query yanlış
  yasaya daha yakın embed oluyor → **embedding limiti (Mursit)** veya benchmark-etiketi. Daha iyi
  embedding modeli (heavy swap) veya benchmark review gerektirir.
- **trafik domain@1 %45 (rerank):** rerank trafik'i bozuyor (hybrid %73) → domain-seçici rerank ablasyonu.
- **SONUÇ:** Büyük lever (doc_type=law +15.2pp) yakalandı. Kalan kazançlar diminishing returns —
  ölçüm-sürücülü loop maksimum FP-safe iyileştirmeyi sağladı.

## Ölçüm altyapısı (kullanıcı koşar)
- `scripts/run_baseline.py --mode {hybrid,rerank}` — domain-bazlı madde_recall@5.
- `EVAL_DOC_TYPE=law` / `EVAL_RERANK_CANDIDATES=N` — ablation knob'ları.
- `scripts/demo_measure_rag.py` — hızlı 8-vaka demo. `eval/rerank_cutoff_sweep.py` — cutoff sweep.
- `HYBRID_FUSION=dbsf` — DBSF füzyon A/B. `scripts/exp_law_filter.py` — law-filter A/B deneyi.
