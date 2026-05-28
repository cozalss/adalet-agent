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

## 4. Ölçülen vs Bekleyen (dürüst durum)

**Ölçüldü:**
- Retrieval rerank modu (yukarıda) ✅
- Real-LLM smoke (paper-draft §4.4, 3 vaka, Qwen 14B) ✅

**Henüz ölçülmedi (gelecek iş — Üye 4):**
- Retrieval mod karşılaştırması (hybrid-only / hyde / multi_query / raptor) — yalnız
  rerank koşuldu; paper §4.1 diğer satırları bunlarla dolacak.
- Ragas faithfulness / answer_relevancy / context_precision tam koşum (186 vaka).
- Verify ON/OFF halüsinasyon tespit oranı (paper §4.2).
- Edge-case (OWASP LLM Top-10, 24 vaka) pass/reject doğruluğu (paper §4.3).
- Tahmin modeli (BERT-TR) — eğitilmedi; tez deneyleri bekliyor.

## 5. Reproducibility
```bash
# Corpus istatistikleri
uv run python -m scripts.eval_run --version v2 --rerank --out results.json
# Verify kalibrasyon (corpus-bağımsız; gold: verify_gold.jsonl 24.5k)
uv run python -m eval.verify_calibration
```
