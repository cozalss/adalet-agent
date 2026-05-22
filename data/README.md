# Veri

- `benchmark/` → 500 vakalık Türkçe hukuk test seti (versiyonlu)
- `training/` → ML modeli için fine-tune verisi
- `eval/` → Ragas trace'leri, Langfuse export'ları, sonuç raporları

## Kurallar

- **Gerçek TCKN, telefon, isim yasak.** Hep sahte (`Ayşe Yılmaz`, `0555-123-4567`)
- Büyük dosyalar Git LFS ile (`*.csv`, `*.parquet`, `*.json` > 10 MB)
- Model checkpoint'leri commit yok (`.gitignore`'da)
- Raw eğitim verisi `training/raw/` gitignore'lu

## Veri Kaynakları

Tümü kamuya açık → KVKK / etik kurul sorunu yok:
- Yargıtay açık kararlar (yargitay.gov.tr + yargi-mcp)
- Mevzuat Bilgi Sistemi (mevzuat.gov.tr)
- Danıştay (danistay.gov.tr)
- Resmi Gazete (resmigazete.gov.tr)

## Benchmark Şeması

`benchmark/v1.jsonl` formatı:

```json
{
  "id": "tuk-001",
  "domain": "tuketici",
  "question": "...",
  "expected_statutes": ["TKHK m.11"],
  "expected_outcome_class": "tuketici-lehine",
  "difficulty": "kolay"
}
```

500 vaka hedef — Sprint 3-4'te 100, Sprint 7'de 500'e tamamlanır.
