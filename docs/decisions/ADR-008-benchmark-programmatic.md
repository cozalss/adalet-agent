# ADR-008 — Programmatic benchmark generation

**Durum:** Accepted
**Tarih:** 2026-05-13
**Sprint:** 4 / W2

## Bağlam
Sprint-3 sonu benchmark **50 vaka** (manuel kürasyon). Bu:
- Akademik makale için yeterli istatistik gücü yok (paper baseline)
- Tek alan ağırlıklı (İK %48), generalization metrik yanlı
- Yeni mode (RAPTOR, GraphRAG) ölçümünde varyans yüksek

Genişletme seçenekleri:
1. **Manuel** — 4 kişi × 40 saat = 160 saat. Plan'da yer yok (250h toplam).
2. **Programmatic + manual review** — yargi-mcp'den karar başlıklarını
   çek, LLM ile soru çıkar, %20 sample manuel review.
3. **Crowd-source** — Çankaya Hukuk Fakültesi öğrencileri (4. yıl).
   Sınav dönemi + KVKK consent karmaşık, Sprint-4'e yetişmez.

## Karar
**Programmatic generation + sample QA review** (seçenek 2).

`scripts/generate_benchmark.py`:
- `data/eval_benchmark/topics_v2.json` — 8 domain × ~17 topic phrase
- Her topic için `_QUESTION_PATTERNS` regex→template mapping (deterministik)
- `--variants N` ile her topic'ten N varyant
- `--online` flag: yargi-mcp'den gerçek karar fetch + meta enrichment

`scripts/merge_benchmark_v2.py`:
- Legacy 50 vaka + generated → dedup (Levenshtein 0.85)
- ID re-sequence `V_{domain}_{NNN}`

Hedef dağılım:
- 60 İK + 50 Tüketici + 40 Kira + 30 TBK + 20 idari/vergi/trafik = 200

Sprint-4 W2 sonu: **186 vaka** (50 legacy + 136 generated). %100 hedef
Sprint-5 (Hafta 11+) sonrası.

## Sonuç
- W2 benchmark v2 ile freeze_baseline koşturuldu (4 mode × 186 vaka)
- W10 final v3 run plana göre 5 mode × 200 vaka
- Akademik makaleye yetecek istatistik gücü
- Manuel review sonra (Sprint-5 sonrası), %20 örneklem ile kalite kontrol

## Alternatifler
- **GPT-4 ile soru çıkarımı**: CLAUDE.md "production'da OpenAI yok" kuralı.
  Sadece offline benchmark prep'te kullanılabilir; ama generated quality
  takip için kararname.
- **HuggingFace Turkish-QA datasets**: hukuk-specific yok, generic
  Türkçe QA (e.g., MKQA-TR) bizim taskımıza uymuyor.
- **Existing benchmark (KILT-TR, XQuAD)**: legal alan yok.

## İlgili
- [scripts/generate_benchmark.py](../../adalet-agent/backend/scripts/generate_benchmark.py)
- [data/eval_benchmark/topics_v2.json](../../adalet-agent/backend/data/eval_benchmark/topics_v2.json)
- [data/eval_benchmark/benchmark_v2.jsonl](../../adalet-agent/backend/data/eval_benchmark/benchmark_v2.jsonl)
- eval/runs/W2_changes.md
