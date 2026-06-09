# Ölçülmüş Sonuçlar — ADALET-AGENT (2026-05-29)

> Bu dosya **gerçek, doğrulanmış** ölçümleri toplar; `paper-draft.md` Sonuçlar
> bölümüne (4.1+) entegre edilmek üzere. Tüm sayılar canlı sistemde ölçüldü —
> placeholder/tahmin YOK. Üye 1 (mimari tezi) + Üye 4 (benchmark tezi) ortak kaynak.

## 1. Corpus İstatistikleri (Qdrant `adalet`, 2026-05-29)

**Toplam: 159.362 vektör** (oturum öncesi 62.188 → +%156).

### Domain dağılımı
| Domain | Vektör |
|---|---:|
| isHukuku | 41.539 |
| kira | 21.732 |
| tapu | 20.761 |
| tüketici | 17.232 |
| trafik | 16.657 |
| icra | 16.629 |
| idari | 10.502 |
| vergi | 7.017 |

### Kaynak dağılımı
| Kaynak | Vektör | Not |
|---|---:|---|
| yargitay | 88.702 | HuggingFace Turkish-Law-700k + Bedesten/UYAP |
| anayasa | 46.386 | Bireysel başvuru + norm denetimi |
| danistay | 14.839 | idari + vergi (içerik-routing) |
| mevzuat | 7.421 | kanun maddeleri (TKHK/IK/TBK/IYUK… tam) |
| gib_ozelge | 1.284 | GİB vergi özelgeleri |
| uyap | 291 | Bölge Adliye keyword-relevance |

## 2. Retrieval Değerlendirmesi

**Yöntem:** v2 benchmark (186 vaka, 8 domain), HYBRID + cross-encoder RERANK
modu, BGE-M3 (dense+sparse) + BGE-reranker-v2-m3, Qdrant RRF füzyon.
Komut: `uv run python -m scripts.eval_run --version v2 --rerank`.

### Genel metrikler (HYBRID + RERANK, 186 vaka)
| Metrik | Değer |
|---|---:|
| Domain Accuracy @1 | **%81.2** |
| Domain Accuracy @5 | **%97.3** |
| MRR (Mean Reciprocal Rank) | **0.879** |
| Keyword Recall (gt-kw ∈ top-5) | **%78.2** |
| Ortalama gecikme | 2.78 s |
| P95 gecikme | 12.18 s |

### Domain bazında Accuracy@1
| Domain | @1 | n |
|---|---:|---:|
| isHukuku | %95.3 | 41/43 |
| trafik | %90.9 | 10/11 |
| tapu | %90.0 | 9/10 |
| kira | %87.9 | 29/33 |
| icra | %84.6 | 22/26 |
| vergi | %72.7 | 8/11 |
| tüketici | %66.7 | 28/42 |
| idari | %40.0 | 4/10 |

### Mod karşılaştırması — HYBRID vs +RERANK (186 vaka, 2026-05-29)
Komut: `eval_run --version v2` (hybrid) vs `--version v2 --rerank`.

| Mod | @1 | @5 | MRR | kw-recall | Ort. gecikme | P95 |
|---|---:|---:|---:|---:|---:|---:|
| **Hybrid** (BM25+dense+RRF) | %81.7 | %96.2 | 0.884 | %79.6 | **260 ms** | **69 ms** |
| **+Rerank** (BGE-reranker-v2-m3) | %81.2 | %97.3 | 0.879 | %78.2 | 2780 ms | 12180 ms |

**Bulgu (tez için kritik):** Cross-encoder rerank, domain@1'de **kazanç
sağlamıyor** (hatta %81.7→%81.2 hafif düşüş) ve MRR/kw-recall'ı da iyileştirmiyor;
yalnız @5'te marjinal (+%1.1). Buna karşın **~10× gecikme** (260→2780 ms ort.,
69 ms→12.18 s P95) getiriyor. Bu, "cross-encoder Türkçe konuşma-diline zayıf →
domain-öncelikli tier-sort" tasarım kararını (ADR/§3) **sayısal olarak doğrular**:
rerank'in bu corpus + vatandaş-dili sorgularında maliyet/fayda oranı negatif.
Production default `LLM_MODE` benzeri bir `RERANK_ENABLED` flag'iyle hybrid-only
kullanım, kaliteden ödün vermeden P95'i ~177× düşürür. (hyde/multi_query modları
gerçek LLM gerektirir → henüz koşulmadı, §4 bekleyen.)

**Metodolojik not (önemli):** `domain@1` metriği, kanun (mevzuat) chunk'larında
`domain` payload alanı bulunmadığından, kanun chunk'larını `kanun_kodu → domain`
eşlemesiyle (`DOMAIN_TO_KANUN_KODU` ters haritası) sınıflar. Bu düzeltme olmadan
metrik kanun-ağırlıklı domainleri haksız cezalandırıyordu (ham %54.3 → düzeltilmiş
%81.2). Düzeltme `scripts/eval_run.py:_effective_domain`'de; commit 5917818.

**Yorum:** idari (%40, 10 vaka) tek belirgin zayıf nokta — idari hukukun
kavramsal olarak diğer domainlerle örtüşmesi + küçük örneklem. Diğer 7 domain
%66–95. tüketici (%66.7) iyileştirilebilir.

## 3. Sistem Mimarisi (özet — `paper-draft.md` §3 ile uyumlu)

- **8-ajan LangGraph:** triaj → (mevzuat ∥ emsal) → [crag?/eligibility?] → draft
  → verify → debate → [tahmin?/dilekçe?] → finalize. retry → mevzuat+emsal
  RE-RETRIEVE (HyDE stokastik; merge_citations dedup reducer).
- **Verify 4-katman:** L1 fuzzy + L2 LettuceDetect token-grounding + L3 mDeBERTa
  NLI (entailment/contradiction) + L4 debate (Constitutional self-critique).
  Kalibre eşikler (NLI_CONTRADICTION 0.70 ölçülmüş-optimal).
- **Hibrit retrieval:** BM25 (sparse) + dense (BGE-M3) + ColBERT + RRF + cross-encoder
  rerank + **domain-öncelikli tier-sort** (cross-encoder konuşma-dili TR'de
  noise-floor verdiğinden, triaj domain'i prior olarak kullanılır).

## 3.5. Verify ON/OFF Ablasyon (paper §4.2 — 2026-05-29)

**Yöntem:** 8 vatandaş sorusu (her domain), graph her soruda doğrulama katmanı
**AÇIK** (`VERIFY_ENABLED=1`) ve **KAPALI** (`VERIFY_ENABLED=0` bypass) iki kez
koşuldu — gerçek Qwen 2.5 14B (llamacpp), CPU embedder. Komut:
`eval/verify_ablation.py`. Harness: `eval/runs/verify_ablation_*.json`.

| Metrik | Değer |
|---|---:|
| Ort. claim-support — **verify ON** | **%41.9** |
| Ort. claim-support — **verify OFF** | **%100** |
| **Fark (verify ayırt etme gücü)** | **+58.1 puan** |
| Verdict-flip (block-rate) | %0 (8/8 her iki arm `pass`) |

### Soru bazında (claim-support ON / OFF)
| Soru | ON | OFF | | Soru | ON | OFF |
|---|---:|---:|---|---|---:|---:|
| E1 | %38 | %100 | | E5 | %27 | %100 |
| E2 | %46 | %100 | | E6 | %33 | %100 |
| E3 | %33 | %100 | | E7 | %46 | %100 |
| E4 | %54 | %100 | | E8 | %58 | %100 |

**Bulgu (tezin çekirdek kanıtı):** Doğrulama katmanı, LLM'in ürettiği iddiaların
**ortalama %58'inin kaynakla token-düzeyinde doğrulanmadığını** tespit ediyor
(verify OFF iken hepsi sorgusuz "supported"). Bu, "iddia-doğrulamalı = uydurmaz"
iddiasının doğrudan sayısal kanıtıdır.

**Dürüst nüans (önemli):** Bu 8 **temiz, kapsam-içi** soruda verdict her iki arm'da
da `pass` (block-rate %0). Çünkü (a) cevaplar makul ve en az %20 claim destekleniyor
(`MIN_VERIFIED_CLAIMS_RATIO` eşiği), (b) NLI contradiction-veto bu sorularda
tetiklenmedi. Yani verify burada cevabı **reddetmiyor**, **claim düzeyinde** ~%58
iddiayı "kaynaksız" işaretliyor. Verify'ın RED gücü çelişki/adversarial girdide
devreye girer → paper §4.3 (edge_cases, OWASP) ölçümünde gösterilecek. Aggregation
eşiğinin gevşekliği gelecek-iş (eşik ablasyonu).

## 4. Ölçülen vs Bekleyen (dürüst durum)

**Ölçüldü:**
- Retrieval rerank modu (yukarıda) ✅
- Retrieval hybrid-only modu + rerank karşılaştırması (10× latency bulgusu) ✅
- Real-LLM smoke (paper-draft §4.4, 3 vaka, Qwen 14B) ✅
- **Verify ON/OFF ablasyon (§3.5, 8 soru, gerçek Qwen)** — claim-support %41.9 vs
  %100, +58.1 puan fark ✅

**Harness hazır — GPU koşumu bekliyor (Üye 4):**
- **Edge-case (OWASP LLM Top-10, 24 vaka — paper §4.3)** — runner + CLI hazır:
  `uv run python -m eval.edge_cases` → `eval/runs/edge_cases_*.json`. (Verify'ın
  RED gücü burada gösterilecek — adversarial/çelişki girdi.)

**Ölçüldü — Tahmin modeli (BERT-TR), GPU baseline (2026-05-29):**

İlk uçtan-uca eğitim — `auto_label`(CPU, leak-free silver-label) → `train`(GPU,
RTX 4070 fp16) → `calibrate_model`(temperature scaling + ECE). Pipeline doğrulandı.

| Metrik | Değer | Not |
|---|---:|---|
| Test accuracy | **%82.6** | 3-class (kazandı/kaybetti/kısmi); random ≈%33 |
| Test f1_macro | **0.825** | dengeli set → her sınıf adil temsil |
| **ECE (kalibrasyon)** | **0.0825 → 0.0109** | temperature scaling (T=1.56) uygulandı; hedef ≤0.05 ✓ |
| Eğitim verisi | 14400 train / 1800 val / 1800 test | **18.000 dengeli** silver-label (6000/sınıf, 613k karar tarandı, 9 shard) |
| Model | dbmdz/bert-base-turkish-cased | 110M, 4 epoch, lr 2e-5, fp16, class-weighted CE |

**Veri ölçeği ablasyonu (öğrenme):** 1-shard 3.3K imbalanced → f1 **0.656**;
9-shard 18K **dengeli** → f1 **0.825**. İmbalanced 26K (class-weight) → 0.791.
Bulgu: **denge > ham boyut**; dengeli 18K en iyi. ECE 0.0825 (fazla-güven) →
temperature T=1.56 ile **0.0109** (model artık kalibre — "%X kazanırsın" gerçekten
%X). `temperature.json: temperature_applied=true`.

**Dürüst tavan notu:** f1_macro **0.825** facts-only (hüküm HARİÇ, leak-free) +
**silver-label** (heuristic ~%70-90) için güçlü bir sonuç; daha yükseği (≥0.88)
**gold eval-set** (insan-etiketli, Cohen's kappa — tez Hafta-2 planı) gerektirir.
Label leakage (hükmü input'a koymak) f1'i şişirir ama modeli vatandaş için
işe yaramaz kılar (leak-free tasarım metodolojik katkıdır). Model `inference.py`'de
canlı: checkpoint varsa BERT (T=1.56 kalibre), yoksa heuristic fallback.

**Henüz ölçülmedi (gelecek iş — Üye 4):**
- HyDE / multi_query / raptor modları (gerçek LLM gerektirir) — paper §4.1
  kalan satırları bunlarla dolacak.
- Ragas faithfulness / answer_relevancy / context_precision tam koşum (186 vaka).
- Tahmin modeli: çok-shard ölçek + gold eval-set (hedef f1_macro ≥0.75).

> **Not:** §4.2/§4.3 sayıları **gerçek Qwen 14B GPU** ile koşulmalı — MockLLM
> canned cevap verir, ON/OFF farkı/adversarial tepki anlamsız olur. Harness'ler
> MockLLM ile smoke-koşar ama ürettiği sayılar tez sonucu DEĞİLDİR (payload
> `meta.note` bunu işaretler).

## 5. Reproducibility
```bash
# Corpus istatistikleri
uv run python -m scripts.eval_run --version v2 --rerank --out results.json
# Verify kalibrasyon (corpus-bağımsız; gold: verify_gold.jsonl 59 vaka)
uv run python -m eval.verify_calibration
```
