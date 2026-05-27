# Verify-Katman Kalibrasyon Bulguları

> Harness: `eval/verify_calibration.py` · Altın küme: `data/eval_benchmark/verify_gold.jsonl`
> Koşum: `uv run python -m eval.verify_calibration [--nli] [--out ...]`
> Tarih: 2026-05-27 · Küme: 59 vaka (v2; ilk 31'den genişletildi)

## Neden

`agents/config.py` içindeki verify eşikleri (FUZZY 0.55, LETTUCE 0.45/0.15,
NLI 0.55/0.70, MIN_VERIFIED_CLAIMS_RATIO 0.20) elle, **ölçüm yapılmadan**
ayarlanmıştı — yorumlar bunu itiraf ediyor (`0.72→0.60→0.55`, `0.50→0.30→0.20`).
Bir eşiği körlemesine kaydırmak verdict dağılımını (pass/retry/reject) sessizce
bozabilirdi. Bu harness, etiketli 59 vakalık bir altın küme üzerinde verify
**kararını** ölçer → bundan sonra her eşik değişikliği ölçülen bir delta.

Altın küme SENTETİK fixture'lar (CLAUDE.md §1: kullanıcıya sunulan uydurma
referans yok). Kategoriler: exact (11), paraphrase (14), unsupported (16),
contradiction (13), format_bad (5). 8 domain (tuketici/isHukuku/kira/icra/
trafik/vergi/tapu/idari) kapsanır.

## Ölçülen sonuçlar (59 vaka)

### Model-free yol (L1 + fuzzy; NLI/Lettuce yok)
Mevcut FUZZY=0.55 → **P=0.54 R=0.52 F1=0.53 Acc=0.61**.

Fuzzy eşik taraması (bu küme):

| th | P | R | F1 |
|----|----|----|----|
| 0.45 | 0.59 | 0.92 | **0.72** |
| 0.55 (mevcut) | 0.54 | 0.52 | 0.53 |
| 0.70 | 0.67 | 0.32 | 0.43 |

### Tam pipeline (NLI + fuzzy + L1)
Mevcut eşiklerde → **P=0.92 R=0.92 F1=0.92 Acc=0.93** (TP=23 FP=2 TN=32 FN=2).

NLI çelişki eşiği taraması:

| th | contradiction recall | supported'a yanlış-veto |
|----|----|----|
| 0.50 | 0.77 | 1 |
| 0.60 | 0.77 | 1 |
| **0.70 (mevcut)** | **0.77** | **0** |
| 0.80 | 0.77 | 0 |
| 0.90 | 0.62 | 0 |

NLI entailment ayrımı: supported=0.74 vs unsupported=0.02 → **gap +0.72**.

### Sağlamlık (31 → 59 vaka)
Bulgular küme neredeyse iki katına çıkıp 8 domaine yayıldığında **stabil
kaldı** — ilk 31-vaka sonuçları overfit artefaktı değildi:

| metrik | 31 vaka | 59 vaka |
|----|----|----|
| tam pipeline F1 | 0.93 | 0.92 |
| model-free fuzzy F1 | 0.64 | 0.53 |
| NLI 0.70 yanlış-veto | 0 | 0 |
| entailment gap | +0.66 | +0.72 |

NLI'nin katkısı büyüdü (model-free zayıfladıkça): F1 +0.29 → **+0.39**.

## Bulgular (kanıta dayalı)

1. **NLI yük taşıyan katman.** Tek başına fuzzy F1=0.53; NLI eklenince F1=0.92
   (+0.39). Fuzzy + L1 deterministik yol bir ön-filtre; gerçek ayrımı NLI yapar.

2. **Fuzzy çelişkiyi YAKALAYAMAZ.** contradiction kategorisi model-free karar
   doğruluğu **0.23** (fuzzy=0.64 yüksek token örtüşmesi, ama anlam ters).
   Negation'ı token örtüşmesi göremez → NLI vetosu yapısal olarak zorunlu.
   Bu, `VERIFY_STRICT` fail-closed tasarımını DOĞRULAR (NLI yoksa reddet).

3. **NLI_CONTRADICTION_THRESHOLD=0.70 bu kümede optimal.** 0.70'te maksimum
   çelişki recall (0.77) + SIFIR yanlış-veto. 0.50/0.60'ta gerçek bir
   desteklenen claim yanlışlıkla veto ediliyor; 0.90'da recall 0.62'ye düşüyor.
   Elle ayarlanan 0.70 tam doğru noktada — `[[adalet_nli_finding]]` ile uyumlu.

4. **Lettuce fallback skoru, kullanılmadığı hâlde fuzzy'den daha ayırt edici**
   (gap +0.19 vs fuzzy +0.09). Production `verify_node`, lettuce dallarını
   `not l25_fallback` ile kapıladığından model-free yolda bu sinyal atılıyor.
   Potansiyel iyileştirme; ama production'a almak verify_node değişikliği +
   gerçek model doğrulaması ister (bkz. Sonraki adım).

## Karar: eşik DEĞİŞTİRİLMEDİ

Ölçüm, mevcut tam-pipeline kalibrasyonunun **sağlam** olduğunu gösteriyor
(F1=0.92, contradiction eşiği optimal, sağlamlık 31→59'da teyit edildi).
"Measure first" disiplininin koruduğu şey tam da budur: iyi eşikleri sezgiyle
kaydırmamak. Model-free fuzzy=0.45'in daha iyi görünmesi sentetik kümeye
overfit riski taşır ve production yolu zaten NLI ile çalışır → değişiklik yok.

## Sonraki adım (production-grade kalibrasyon)

- Altın kümeyi büyüt (59 → 100+), gerçek retrieval snippet'leriyle doldur
  (Qdrant'tan çekilmiş kanıt) — sentetik fixture overfit riskini azalt.
- Lettuce fallback'i pozitif sinyal olarak verify_node'a almayı A/B ölç
  (gap +0.19 umut verici); önce gerçek LettuceDetect modeliyle doğrula.
- MIN_VERIFIED_CLAIMS_RATIO'yu çok-claim'li gerçek cevaplarda ölç (şu an
  saf-fonksiyon karakterizasyonu var; verdict dağılımı E2E benchmark ister).
