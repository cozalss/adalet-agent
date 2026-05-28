# ADR-009 — Tahmin Ajanı (Predictive Justice): Heuristic → BERT-TR Yol Haritası

- **Tarih:** 2026-05-28
- **Durum:** Önerildi (Sprint-7/8)
- **Karar verenler:** ADALET-AGENT ekibi
- **İlgili dosyalar:** [predictive/inference.py](../../backend/predictive/inference.py), [agents/nodes/tahmin.py](../../backend/agents/nodes/tahmin.py), [predictive/README.md](../../backend/predictive/README.md)

## Bağlam

Tahmin Ajanı (8. ajan), kullanıcıya "Benzer 47 davadan 41'i tüketici lehine sonuçlandı — kazanma olasılığınız yaklaşık %87" gibi nicel bir öngörü sunmayı hedefler (CLAUDE.md projeyi tanımlayan üç bilimsel katkıdan biri).

Mevcut durum (`PREDICTIVE_ENABLED=1` ile canlı):

- `predict_outcome()` heuristic baseline — Yargıtay karar metinlerindeki `kabulüne / reddine / kısmen` ifadelerini regex ile oylar.
- Tavan: `confidence ≤ 0.85` (kesinlik ima etmez).
- Hüküm-izolasyonu eklendi (28.05.2026): heuristic artık metnin tamamını değil yalnız `HÜKÜM:` / `SONUÇ:` bölümünü tarar — gerekçe bölümündeki "alt mahkeme reddine" atıfları false-label etmiyor.

Yetersizlik (mle-reviewer bulguları):

1. **Türkçe morfoloji eksiği** — `"kabulü ile karar"` gibi varyantlar pattern listesini geçmez.
2. **Bozma + kısmi karar karmaşası** — Yargıtay bozma kararları nüans gerektirir; regex bu hiyerarşiyi göremez.
3. **Domain-özelinde zayıf** — vergi/idare hukukunda "iptal isteminin reddi" gibi alanın özel kalıpları yok.
4. **Açıklanabilirlik** — şu an yalnız oy dağılımı; faktör çıkarımı yok.

## Karar

`predict_outcome()` arayüzünü **stabil tut**; içeride strategy pattern ile BERT-TR fine-tune backend'i ekle:

```
predict_outcome(question, similar_case_texts, similar_case_ids) ->
    if PREDICTOR_BACKEND == "bert" and model_loaded:
        bert_predict(...)
    else:
        _heuristic_predict(...)   # her zaman fallback
```

`PREDICTOR_BACKEND` env değişkeni ile A/B test ve rollback kontrol edilir.

## 4 Haftalık Uygulama Yol Haritası

### Hafta 1 — Veri toplama + hüküm izolasyonu pipeline

- `scripts/predictive/fetch_yargitay_outcomes.py` — yargi-mcp ile tüketici/iş/kira/icra dairelerinden 12K karar
- `scripts/predictive/extract_hukum.py` — `HÜKÜM:` / `SONUÇ:` regex izole et (yeni: predictive/inference.py'daki `_isolate_hukum` referans)
- `scripts/predictive/auto_label.py` — mevcut heuristic'i izole HÜKÜM üzerinde çalıştır → weak label
- **Çıktı:** `data/predictive/raw_v1.jsonl` (~12K), `auto_labeled_v1.jsonl` (~10K)

### Hafta 2 — Etiket kalitesi + temporal split

- 300 vakalık stratified sample (domain × sınıf), **3 anotatör**
- Cohen's Kappa hedef: ≥0.70 (düşükse rehberi revize)
- Qwen 14B ile düşük güven (~3K) re-label
- **Temporal split:** Train 2010-2021 / Val 2022 / Test 2023-2024 (rastgele split YASAK — mevzuat değişimi sızıntısı)
- **Class weight:** `kismi` sınıfı için ×2.5 (en nadir, %20)

### Hafta 3 — Fine-tune + eval

- Model: `dbmdz/bert-base-turkish-cased` (HF SHA pin)
- **Tam fine-tune** (LoRA değil — BERT-base RTX 4070 12GB'a sığar)
- Hyperparameter grid: LR ∈ {1e-5, 2e-5, 3e-5} × epoch ∈ {3, 4, 5} = 9 run
- **Loss:** focal loss γ=2 + class weights (kismi sınıfı için)
- **Calibration:** Platt scaling (validation üzerinde fit), ECE ölçümü
- **MLflow** lokal tracking (W&B yerine, KVKK + offline)

### Hafta 4 — Inference entegrasyon + A/B test

- `inference.py`'a BERT path ekle (heuristic fallback korunur)
- **ONNX export + INT8 quantize** — p95 latency ≤200ms hedefi
- `PREDICTOR_BACKEND=shadow` modu (BERT loglanır, heuristic gösterilir)
- `predictive/calibration_eval.py` — haftalık karşılaştırma (verify_calibration.py paterni)
- Monitoring: prediction distribution, confidence histogram, drift uyarısı

## Hedef Metrikler

| Metrik | Hedef | Notlar |
|---|---|---|
| Macro-F1 | ≥0.75 | Test split (2023-2024 holdout) |
| `kismi` sınıfı F1 | **≥0.60** | mle-reviewer kritik: macro F1 yüksek görünse de kismi gizlenebilir |
| ECE (calibration error) | ≤0.05 | Platt scaling sonrası |
| Latency p95 | ≤200ms | ONNX + INT8 |
| Confidence tavan | **0.85** | BERT'te de zorla clip (sıfır halüsinasyon felsefesi) |

## Etik ve Risk

- **Hukuki bağlam:** Loomis v. Wisconsin (2016) ve AB Yapay Zeka Tüzüğü (2024) çerçevesinde "yüksek riskli AI". Savunma:
  - Karar veren hâkim; sistem yalnız bilgi sunar
  - Her tahminde zorunlu disclaimer
  - Confidence tavan %85
- **Bias kontrolü:** 3 kesit analizi (domain × yıl × Yargıtay dairesi). Cinsiyet/coğrafya karar metninde görünmez → limitasyon tezde belirtilir.
- **Açıklanabilirlik:** mevcut `similar_case_ids` yeterli; SHAP/IG opsiyonel.

## Geri Çekme

- Model yüklenemiyor / OOM / inference >2s → `asyncio.wait_for` hard timeout → `_heuristic_predict` fallback
- `PREDICTIVE_ENABLED=0` ile node tamamen graph'tan çıkar
- `PREDICTOR_BACKEND=heuristic` ile BERT pasifleştir (model dosyası diskte kalır, rollback hızlı)

## Bağlam: ADALET-AGENT Bilimsel Katkıları

Bu yol haritası tamamlandığında **CLAUDE.md §7'de listelenen 3 katkıdan biri** somutlaşır:

> "Türkçe Yargıtay kararları üzerinde eğitilmiş, dava sonucu olasılığı tahmin eden bir derin öğrenme modeli. Predictive justice alanında Türkçe ilk açık modeldir."

Akademik makale potansiyeli: TIDE-TR / SIU / LREC-COLING Hukuk Atölyesi.

## Referanslar

- mle-reviewer raporu (28.05.2026 ECC Agent)
- [predictive/README.md](../../backend/predictive/README.md) — Sprint-7/8 orijinal tasarım
- [retrieval/turkish_text.py](../../backend/retrieval/turkish_text.py) — `tr_lower` utility
- HuggingFace: `dbmdz/bert-base-turkish-cased`
