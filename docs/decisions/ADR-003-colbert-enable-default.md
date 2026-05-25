# ADR-003 — ColBERT query default ON

**Durum:** Accepted
**Tarih:** 2026-05-19
**Sprint:** 4 / W1.1

## Bağlam
Sprint-3 sonu: hybrid retrieval BGE-M3 dense + sparse RRF birleştirilmişti.
ColBERT (multi-vector late-interaction) yazılmış ama `COLBERT_QUERY_ENABLED=0`
default ile kapalıydı.

Literatür (Khattab & Zaharia 2020) BEIR ve passage ranking task'larında
ColBERT'in dense + sparse'a +3-7pp Recall@10 kattığını göstermiş. Türkçe
hukuk corpus'unda Sprint-3 baseline'da D@1 = 0.26.

## Karar
`COLBERT_QUERY_ENABLED=1` default. Qdrant collection'larda ColBERT vector zaten
mevcuttu (W3 sonu); production'da query path'inde aktif edildi.

Maliyet:
- Query embedding: +200ms (BGE-M3 token-level)
- Qdrant scroll: +20ms (multi-vector skor)
- Toplam +220ms — production p95 30s bütçesinde ihmal edilebilir

Risk: dense + sparse + ColBERT üç vector ile RRF normalization daha gürültülü
olabilir. RRF k=60 default korundu (W1.6 sweep'inde stabil).

## Sonuç
W1 sonu freeze_baseline (v1_w1):
- D@1: 0.26 → 0.32 (+6pp)
- kanun@5: 0.54 → 0.60 (+6pp)
- p95 latency: +0.22s

Tüketici sorularında ColBERT madde-spesifik citation'ı dense'in kaçırdığı
yerlerde bulduğu doğrulandı (örn. TKHK m.48 cayma hakkı).

## Alternatifler
- **BGE-M3 dense only**: baseline; budget içinde ama D@1 < target
- **Parent-doc retrieval**: chunk-parent reranking; W1.5 buffer plan'da

## İlgili
- [retrieval/embedding.py:33](../../adalet-agent/backend/retrieval/embedding.py#L33)
- [retrieval/vector_store.py:33](../../adalet-agent/backend/retrieval/vector_store.py#L33)
- eval/runs/W1_changes.md
