# agents

LangGraph üzerinde 7 ajan orkestrasyonu.

## Ajanlar

| Ajan | Görev |
|------|-------|
| Triaj | Soruyu hukuk alanına sınıflandır |
| Mevzuat | Yasa maddelerini getir |
| Emsal | Yargıtay'dan benzer dava bul |
| Dilekçe | Resmi formatta taslak yaz |
| Doğrulama | Her iddiayı kaynaktan doğrula |
| Tartışma | Ajan görüşlerini karşılaştır |
| Tahmin | Kazanma olasılığı (ML köprü) |

## Akış

```
Triaj → Mevzuat + Emsal (paralel) → Dilekçe → Doğrulama → Tartışma → Cevap
```

## Sıfır Halüsinasyon

Doğrulama ajanı her madde/karar referansını orijinal kaynaktan fetch eder. Doğrulanmazsa max 3 iter sonra reddedilir.

## Yapılacaklar

- [ ] `graph.py` — LangGraph StateGraph
- [ ] `schemas.py` — State + ajan çıktı tipleri
- [ ] Triaj sınıflandırma
- [ ] Mevzuat fetch (retrieval üzerinden)
- [ ] Verifier metin eşleşme
- [ ] Constitutional debate döngüsü
