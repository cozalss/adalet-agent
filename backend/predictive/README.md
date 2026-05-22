# predictive (opsiyonel)

Kazanma olasılığı tahmini — BERT-TR + classification head.

> Bitirme zorunlu kapsamı **dışında**. Sprint 5+ sonrasında zaman varsa devreye alınır. Öncelik düşük.

## Bileşenler

- `data/` — Veri toplama ve etiketleme scriptleri
- `train.py` — Fine-tune pipeline (HuggingFace Trainer)
- `evaluate.py` — Hold-out + Ragas metrik
- `inference.py` — Production inference

## Model

- **Base:** `dbmdz/bert-base-turkish-cased`
- **Head:** Binary classification + confidence
- **Hedef:** F1 ≥ 0.75

## Yapılacaklar

- [ ] Veri etiketleme protokolü
- [ ] BERT-TR fine-tune iskelet
- [ ] Calibration (temperature scaling)
- [ ] Inference HTTP wrapper
