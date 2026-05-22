# Tez 3 — Doğrulamalı RAG: Türkçe Hukuki Citation Verification

> Yazar: TBD (Sprint 3'te belirlenir)
> Danışman: TBD
> Tarih: 2027 (taslak: Mart 2027)

## Soyut

> [Mart 2027'de yazılacak]

## 1. Giriş

- Problem: RAG'in citation halüsinasyonu
- Çözüm: fetch + metin eşleşme tabanlı verifier
- Katkı: Türkçe hukuki citation benchmark + verifier algoritması

## 2. İlgili Çalışmalar

- RAG paradigmaları (Lewis 2020, Asai 2024)
- Citation verification (Liu et al. 2023)
- BGE-M3 multilingual embedding
- yargi-mcp ve açık hukuk verisi

## 3. Metodoloji

- Hybrid retrieval: BM25 + dense + reranker
- Embedding: BGE-M3 Türkçe
- Verifier: fuzzy match (Levenshtein ≥ 0.85)
- Pipeline: ajan iddiası → fetch → match → kabul/red

## 4. Değerlendirme

- Citation precision / recall (manuel etiketli 500 vaka)
- Faithfulness skoru (Ragas)
- Latency: hybrid vs dense-only vs BM25-only

## 5. Sonuç

> [Sprint 8 sonu yazılacak]
