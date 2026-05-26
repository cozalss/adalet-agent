# ADR-009: Dava Sonucu Tahmin Modeli — BERT-TR + Platt Calibration

**Status**: Accepted (Plan)
**Date**: 2026-05-26
**Sprint**: Sprint-7/8 (Mart-Nisan 2027)
**Owner**: Üye 4 (ML Lead)

## Bağlam

Vatandaş "açsam kazanır mıyım?" diye soruyor. RAG zinciri (mevzuat + emsal +
verify) bilgi veriyor ama olasılık tahmini yapmıyor. Sprint-3+ verify+debate
halüsinasyon kapısı tamamlandı; bu temel üzerine kazanma olasılığı tahmin
modülü eklemek gerekiyor.

## Karar

**BERT-TR (`dbmdz/bert-base-turkish-cased`) + 3-class classification head +
Platt scaling calibration** kullanılacak.

### Seçim Karşılaştırması

| Aday | Pro | Con | Karar |
|---|---|---|---|
| **BERT-TR + head** | Türkçe optimize, küçük (110M), inference hızlı | Sadece encoder | ✅ Seçildi |
| XLM-RoBERTa large | Daha güçlü, multi-dil | 560M, latency p95 > 500ms | ❌ Çok büyük |
| Qwen-fine-tune | Generative + reasoning | Eğitim pahalı, calibration zor | ❌ Sprint-7'de overkill |
| LSTM + TF-IDF | Çok hızlı | Türkçe morfoloji düşük accuracy | ❌ Baseline only |

### Calibration: Platt vs Temperature Scaling

- **Platt** (logit→sigmoid): Binary için optimal, 3-class için one-vs-rest
- **Temperature scaling**: Softmax/T, multiclass için doğal
- **Karar**: Her ikisini de eğit, validation ECE'sine göre seç (A/B test)

### 3-class (won/lost/partial) vs Binary (won/lost)

Yargıtay kararlarının ~%30'u "kısmen kabul/kısmen ret". Binary kabul edersek bu
vakaları zorla bir sınıfa atmak veriyi kirletir. **3-class daha gerçekçi.**

## Sonuçlar (Beklenen)

- F1 macro ≥ 0.75 holdout (1K vaka)
- ECE ≤ 0.05 (calibration kalitesi)
- Inference p95 ≤ 200ms (BERT-base CPU yeterli)
- VRAM < 2 GB (Qwen ile aynı RTX 4070'te)

## Düşüş Senaryoları

- Cohen's Kappa < 0.6: Etiketleme rehberi sıkılaştır, gerekirse 5K vaka ile baseline
- F1 < 0.65: BERT-TR yetmez → XLM-R fallback (aynı pipeline)
- ECE > 0.1: Daha fazla validation data + isotonic regression dene

## Etkilenen Modüller

- Yeni: `backend/predictive/` (train, inference, calibrate)
- Yeni: `backend/agents/nodes/tahmin.py` (8. ajan, opt-in)
- Değişiklik: `backend/agents/graph.py` (PREDICTIVE_ENABLED toggle)
- Değişiklik: `backend/agents/state.py` (Prediction TypedDict)
- Değişiklik: `backend/api/schemas.py` (PredictionSchema, AskResponse.prediction)

## Referanslar

- `backend/predictive/README.md` — full implementation plan
- `docs/theses/tez-4-predictive.md` — akademik çerçeve
- [Niculescu-Mizil & Caruana 2005] — Platt scaling for SVM probability
- [Guo et al. 2017] — Temperature scaling for modern NN
