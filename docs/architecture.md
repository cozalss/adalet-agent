# Mimari

## Üst Seviye Görünüm

```
[ Frontend (Next.js) ]   [ Mobile (Flutter) ]
        \\                       //
         \\                     //
          >> [ Backend (FastAPI) ] <<
                      |
                      v
            [ Agents (LangGraph) ]
                  /        \
                 v          v
         [ Retrieval ]   [ Predictive (opsiyonel) ]
            /     \              |
           v       v              v
      [ Qdrant ] [ yargi-mcp ] [ BERT-TR ]
                    |
                    v
              [ mevzuat.gov.tr ]
```

## Veri Akışı (Bir Soru)

1. Kullanıcı frontend/mobile'da soru yazar
2. Backend soruyu LangGraph'a verir
3. **Triaj ajanı** alanı belirler (örn. "iş hukuku")
4. **Mevzuat + Emsal** paralel çalışır
5. **Dilekçe ajanı** taslak yazar
6. **Doğrulama ajanı** her iddiayı kaynaktan check eder
7. Doğrulanmazsa → ajan yeniden dener (max 3 iter)
8. **Tartışma ajanı** ajan görüşlerini karşılaştırır
9. Backend → istemciye SSE ile akar

## Sıfır Halüsinasyon

Her hukuki referans şu pipeline'dan geçer:

```
Ajan iddiası → fetch original (mevzuat.gov.tr / yargi-mcp)
            → metin eşleşmesi (fuzzy ≥ 0.85)
            → eşleşirse [GEÇERLİ]
            → eşleşmezse [REDDET, ajan yeniden dene]
```

Doğrulama başarısız 3 kez → kullanıcıya:
*"Bu konuda emin değilim, avukata danışmanızı öneririm."*

## Yol Haritası (12 Sprint)

| Sprint | Tarih | Hedef |
|--------|-------|-------|
| 0 | Yaz 2026 | Öğrenme + iskelet |
| 1-2 | Eyl-Ekim 2026 | Backend MVP, 3 ajan, frontend prototip |
| 3-4 | Kas-Ara 2026 | 7 ajan, Doğrulama, Tübitak 2209-A başvuru, tez seçimi |
| 5-6 | Oca-Şub 2027 | Multimodal, mobil beta, Teknofest başvuru |
| 7-8 | Mar-Nis 2027 | Blind test (30 hukuk öğrencisi), tahmin modeli (opsiyonel) |
| 9-10 | May-Haz 2027 | Bitirme teslim, jüri sunumu, makale taslak |
| 11-12 | Tem-Eyl 2027 | Teknofest finalleri, open source launch |

## Riskler

| Risk | Olasılık | Etki | Plan |
|------|----------|------|------|
| Yargıtay açık veri erişim kısıtlanır | Orta | Yüksek | yargi-mcp arşiv + lokal cache |
| Qwen-32B donanım yetersiz | Düşük | Orta | 7B fallback + RAG ağırlığı arttır |
| Hukuki hata → güven kaybı | Orta | Kritik | Verifier + disclaimer + avukat danışman |
| Ekip üyesi düşer | Düşük | Yüksek | Rol ataması yok, dokümantasyon kritik |
