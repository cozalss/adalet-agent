# Verify-Katman Kalibrasyon Bulguları

> Harness: `eval/verify_calibration.py` · Altın küme: `data/eval_benchmark/verify_gold.jsonl`
> Koşum: `uv run python -m eval.verify_calibration [--nli] [--out ...]`
> Tarih: 2026-05-27

## Neden

`agents/config.py` içindeki verify eşikleri (FUZZY 0.55, LETTUCE 0.45/0.15,
NLI 0.55/0.70, MIN_VERIFIED_CLAIMS_RATIO 0.20) elle, **ölçüm yapılmadan**
ayarlanmıştı — yorumlar bunu itiraf ediyor (`0.72→0.60→0.55`, `0.50→0.30→0.20`).
Bir eşiği körlemesine kaydırmak verdict dağılımını (pass/retry/reject) sessizce
bozabilirdi. Bu harness, etiketli 31 vakalık bir altın küme üzerinde verify
**kararını** ölçer → bundan sonra her eşik değişikliği ölçülen bir delta.

Altın küme SENTETİK fixture'lar (CLAUDE.md §1: kullanıcıya sunulan uydurma
referans yok). Kategoriler: exact (6), paraphrase (8), unsupported (9),
contradiction (5), format_bad (3).

## Ölçülen sonuçlar

### Model-free yol (L1 + fuzzy; NLI/Lettuce yok)
Mevcut FUZZY=0.55 → **P=0.64 R=0.64 F1=0.64 Acc=0.68**.

Fuzzy eşik taraması (bu küme):

| th | P | R | F1 |
|----|----|----|----|
| 0.45 | 0.68 | 0.93 | **0.79** |
| 0.55 (mevcut) | 0.64 | 0.64 | 0.64 |
| 0.70 | 0.78 | 0.50 | 0.61 |

### Tam pipeline (NLI + fuzzy + L1)
Mevcut eşiklerde → **P=0.93 R=0.93 F1=0.93 Acc=0.94** (TP=13 FP=1 TN=16 FN=1).

NLI çelişki eşiği taraması:

| th | contradiction recall | supported'a yanlış-veto |
|----|----|----|
| 0.50 | 0.80 | 1 |
| 0.60 | 0.80 | 1 |
| **0.70 (mevcut)** | **0.80** | **0** |
| 0.80 | 0.80 | 0 |
| 0.90 | 0.60 | 0 |

NLI entailment ayrımı: supported=0.68 vs unsupported=0.02 → **gap +0.66**.

## Bulgular (kanıta dayalı)

1. **NLI yük taşıyan katman.** Tek başına fuzzy F1=0.64; NLI eklenince F1=0.93
   (+0.29). Fuzzy + L1 deterministik yol bir ön-filtre; gerçek ayrımı NLI yapar.

2. **Fuzzy çelişkiyi YAKALAYAMAZ.** contradiction kategorisi model-free karar
   doğruluğu **0.00** (fuzzy=0.71 yüksek token örtüşmesi, ama anlam ters).
   Negation'ı token örtüşmesi göremez → NLI vetosu yapısal olarak zorunlu.
   Bu, `VERIFY_STRICT` fail-closed tasarımını DOĞRULAR (NLI yoksa reddet).

3. **NLI_CONTRADICTION_THRESHOLD=0.70 bu kümede optimal.** 0.70'te maksimum
   çelişki recall (0.80) + SIFIR yanlış-veto. 0.50/0.60'ta gerçek bir
   desteklenen claim yanlışlıkla veto ediliyor; 0.90'da recall 0.60'a düşüyor.
   Elle ayarlanan 0.70 tam doğru noktada — `[[adalet_nli_finding]]` ile uyumlu.

4. **Lettuce fallback skoru, kullanılmadığı hâlde fuzzy'den daha ayırt edici**
   (gap +0.28 vs fuzzy +0.14). Production `verify_node`, lettuce dallarını
   `not l25_fallback` ile kapıladığından model-free yolda bu sinyal atılıyor.
   Potansiyel iyileştirme; ama production'a almak verify_node değişikliği +
   gerçek model doğrulaması ister (bkz. Sonraki adım).

## Karar: eşik DEĞİŞTİRİLMEDİ

Ölçüm, mevcut tam-pipeline kalibrasyonunun **sağlam** olduğunu gösteriyor
(F1=0.93, contradiction eşiği optimal). "Measure first" disiplininin koruduğu
şey tam da budur: iyi eşikleri sezgiyle kaydırmamak. Model-free fuzzy=0.45'in
daha iyi görünmesi 31 sentetik vakaya overfit riski taşır ve production yolu
zaten NLI ile çalışır → değişiklik gerekçesi yok.

## Sonraki adım (production-grade kalibrasyon)

- Altın kümeyi büyüt (31 → 100+), gerçek retrieval snippet'leriyle doldur
  (Qdrant'tan çekilmiş kanıt) — sentetik fixture overfit riskini azalt.
- Lettuce fallback'i pozitif sinyal olarak verify_node'a almayı A/B ölç
  (gap +0.28 umut verici); önce gerçek LettuceDetect modeliyle doğrula.
- MIN_VERIFIED_CLAIMS_RATIO'yu çok-claim'li gerçek cevaplarda ölç (şu an
  saf-fonksiyon karakterizasyonu var; verdict dağılımı E2E benchmark ister).
