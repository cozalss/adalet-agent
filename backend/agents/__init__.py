"""ADALET-AGENT — LangGraph 7-ajan beyin katmanı.

Ajanlar:
  triaj       — soruyu domain'e ata
  mevzuat     — kanun maddelerini getir
  emsal       — Yargıtay/Danıştay/Anayasa kararları
  draft       — LLM ile cevap taslağı + claim üretimi
  verify      — her claim'i kaynakla NLI ile doğrula
  debate      — çelişki/halüsinasyon hakemliği (Constitutional AI)
  dilekce     — istenirse resmi dilekçe taslağı
  finalize    — disclaimer + güven skoru + birleşik yanıt
  predict     — kazanma olasılığı tahmini (faz-2)
"""
