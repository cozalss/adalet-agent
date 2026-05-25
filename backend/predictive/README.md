# predictive — ERTELENDİ (Sprint-7/8, Mart-Nisan 2027)

> **Durum:** Bu modül **henüz implement edilmemiştir**. Yol haritasında Sprint-7/8
> dilimine planlandı. Bitirme jürisinde "Sprint-3+ tamamlandı, predictive bir
> sonraki sprint" şeffaf olarak belirtilir.

Kazanma olasılığı tahmini — BERT-TR + classification head ile dava sonucu
tahmini. Sprint-3 (Kasım 2026) → Sprint-6 (Şubat 2027) arası, projenin asıl
çekirdek değeri olan **doğrulamalı çoklu-ajan RAG** zinciri tamamlanıyor.
Tahmin modeli ondan SONRA, sağlam temel üstüne oturtulacak.

## Neden ertelendi?

1. **Veri toplama riski:** Etiketli Yargıtay kararı (kazanan/kaybeden) için
   manuel anotasyon ya da hukuk-akademisi ortağı şart. Sprint-3+ kapsamı
   buna yetmedi.
2. **Önceliklendirme:** Halüsinasyon kapısı (verify+debate) hukukta sıfır-hata
   gereksinimi nedeniyle KRİTİK. Tahmin modeli "katma değer", verify "sıfır
   regret" şartı.
3. **Sprint-7/8 ile uyum:** RAPTOR / GraphRAG / LoRA fine-tune ile birlikte
   tek bir "model training sprint" oluşturmak daha verimli (GPU saatleri,
   tek-amaçlı veri pipeline'ı).

## Planlanan teknik tasarım (Sprint-7/8'de detaylanacak)

- **Base model:** `dbmdz/bert-base-turkish-cased`
- **Head:** Binary classification (won/lost) + confidence calibration
- **Veri:** ~10.000 etiketli Yargıtay kararı (Sprint-7'de toplama scripti)
- **Hedef metrik:** F1 ≥ 0.75, ECE ≤ 0.05 (calibration)
- **Inference latency:** p95 ≤ 200ms (BERT-base CPU)
- **Entegrasyon:** opsiyonel 8. ajan — `tahmin_node`, draft sonrası tetiklenir

## Sprint-7/8 yapılacaklar

- [ ] Veri etiketleme protokolü + 3-kişi inter-annotator agreement
- [ ] Yargıtay HİT (Hukuk Genel Kurulu) → kazanan/kaybeden çıkarma scripti
- [ ] BERT-TR fine-tune pipeline (HuggingFace Trainer, mixed precision)
- [ ] Calibration (Platt scaling veya temperature scaling)
- [ ] Holdout + Ragas (cevap kalitesiyle tahmin tutarlılığı)
- [ ] Inference HTTP wrapper (`predictive/inference.py`)
- [ ] Graph entegrasyonu (`agents/nodes/tahmin.py`, opsiyonel toggle)
- [ ] Ablation: tahmin var/yok jüri sunumu için

## Yol haritasındaki yeri

```
Sprint-3+ (TAMAM, v12)  → 7-ajan RAG, halüsinasyon kapısı, 8/8 pass
Sprint-4   (Aralık 26)  → ColBERT + LLM-Judge + Ragas
Sprint-5/6 (Şub 2027)   → Multimodal (OCR/STT/TTS) + multi-turn
Sprint-7/8 (Mar-Nis 27) → RAPTOR + GraphRAG + LoRA + PREDICTIVE  ← BURASI
Sprint-9/10 (May-Haz 27)→ Blind test + paper + bitirme jüri
```

Detaylar için: kök dizinde `CLAUDE.md` §13 + planning docs (`docs/`).
