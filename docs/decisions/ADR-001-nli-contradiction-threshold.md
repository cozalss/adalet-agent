# ADR-001 — NLI contradiction threshold 0.70

**Durum:** Accepted
**Tarih:** 2026-05-12
**Sprint:** 4 / W4.5
**Karar veren:** Backend lead

## Bağlam
Verify katmanlarında mDeBERTa-v3 XNLI tabanlı NLI (contradiction veto) Türkçe
hukuk paraphrase'lerinde 0.50-0.70 aralığında **false-positive contradiction**
skoru üretiyordu. v7 ölçümünde 3/4 supported claim varken 1 contradiction
nedeniyle tüm cevap reject ediliyordu.

İlk denemeler:
- 0.40 → çok agresif, çoğu paraphrase reject
- 0.50 → orta agresif, hâlâ %15+ false-pos
- 0.70 → sadece açık çelişkiler veto
- 0.85 → pratik olarak hiç tetiklenmiyor

## Karar
`NLI_CONTRADICTION_THRESHOLD=0.70` default. ENV-override edilebilir.

Veto SADECE contradiction için kullanılır; entailment ratio aggregation
kararı için kullanılır (`_verdict_from_ratio` içinde MIN_VERIFIED_CLAIMS_RATIO
= 0.20). Çapraz koruma: fuzzy 0.55 + LettuceDetect 0.45 + RARR-lite.

> **Güncelleme (2026-06):** fuzzy destek eşiği sonradan **0.45**'e indirildi
> (`config.py` `FUZZY_SUPPORT_THRESHOLD`; evrim 0.72→0.60→0.55→0.45). Bu ADR'nin
> çekirdek kararı (NLI contradiction 0.70) geçerli; yalnız buradaki çapraz-koruma
> fuzzy değeri güncel kodda 0.45'tir (tarihsel kayıt korunur).

## Sonuç
- E2E success 5/8 → 7/8 (ilgili sprint ölçümleri)
- Hatalı reject oranı düştü
- Açık halüsinasyon (örn. uydurma madde no) hâlâ yakalanıyor
  (test_yargitay_regression — 8 fabricated case)

## Alternatifler
- **Daha güçlü NLI modeli** (DeBERTa-v3 large XNLI): VRAM 4GB, latency 2x.
  Kabul edilmedi — RTX 4070 12GB'da budget yok.
- **Türkçe-specific NLI** (BERTurk-NLI): henüz literatürde yok. Hafta 10
  sonrası araştırma sürebilir.
- **LLM-as-Judge contradiction**: pahalı, Türkçe paraphrase eğitiminde de
  benzer false-pos riski.

## İlgili
- [agents/config.py:23](../../adalet-agent/backend/agents/config.py#L23)
- [agents/verifier_layers.py:134](../../adalet-agent/backend/agents/verifier_layers.py#L134)
- Memory: `[[adalet_nli_finding]]`
