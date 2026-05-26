# Sprint-5 Domain Audit (20260525T222353Z)

> Tarih: 2026-05-25T22:23:53.703001+00:00
> Kaynak: `data\seed_state/*.jsonl`

## Per-Domain Karar Dağılımı (status=ok)

| Domain | Yargıtay | Danıştay | AYM | Toplam | Hedef | Gap | % |
|---|---|---|---|---|---|---|---|
| tuketici | 200 | 143 | 302 | **645** | 1500 | 855 | 43% |
| isHukuku | 170 | 165 | 975 | **1310** | 2000 | 690 | 66% |
| kira | 192 | 165 | 213 | **570** | 1200 | 630 | 48% |
| icra | 88 | 0 | 618 | **706** | 800 | 94 | 88% |
| trafik | 77 | 71 | 20 | **168** | 800 | 632 | 21% |
| vergi | 80 | 56 | 20 | **156** | 800 | 644 | 20% |
| tapu | 54 | 53 | 20 | **127** | 700 | 573 | 18% |
| idari | 0 | 57 | 20 | **77** | 1000 | 923 | 8% |
| **TOPLAM** | — | — | — | **3759** | **8800** | **5041** | **43%** |

## Notlar

- Hedefler `eval/domain_audit.SPRINT5_TARGETS` içinde tanımlı.
- `Gap` = hedef - şu an. Sprint-5 sonunda 0 olmalı (veya küçük tolerans).
- `%` = (şu an / hedef) × 100. Domain bazlı progress göstergesi.

## Qdrant Live Counts

| Domain | Cases | Regulator | Total | Hedef | % |
|---|---|---|---|---|---|
| tuketici | 7147 | 208 | **7355** | 1500 | 490% |
| isHukuku | 20311 | 0 | **20311** | 2000 | 1016% |
| kira | 4781 | 0 | **4781** | 1200 | 398% |
| icra | 11926 | 0 | **11926** | 800 | 1491% |
| trafik | 970 | 0 | **970** | 800 | 121% |
| vergi | 544 | 0 | **544** | 800 | 68% |
| tapu | 352 | 0 | **352** | 700 | 50% |
| idari | 399 | 231 | **630** | 1000 | 63% |
| **DOMAIN TOPLAM** | — | — | **46869** | **8800** | **533%** |

**Kanun (mevzuat) chunks**: 5496
**Qdrant overall total chunks**: 53726
