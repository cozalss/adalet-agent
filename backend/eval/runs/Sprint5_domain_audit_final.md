# Sprint-5 Final Domain Audit

> Tarih: 2026-05-25T23:57:54.444972+00:00
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
| tapu | 54 | 53 | 300 | **407** | 700 | 293 | 58% |
| idari | 0 | 57 | 300 | **357** | 1000 | 643 | 36% |
| **TOPLAM** | — | — | — | **4319** | **8800** | **4481** | **49%** |

## Notlar

- Hedefler `eval/domain_audit.SPRINT5_TARGETS` içinde tanımlı.
- `Gap` = hedef - şu an. Sprint-5 sonunda 0 olmalı (veya küçük tolerans).
- `%` = (şu an / hedef) × 100. Domain bazlı progress göstergesi.

## Qdrant Live Counts

| Domain | Cases | Regulator | Total | Hedef | % |
|---|---|---|---|---|---|
| tuketici | 6900 | 208 | **7108** | 1500 | 474% |
| isHukuku | 20043 | 0 | **20043** | 2000 | 1002% |
| kira | 4578 | 0 | **4578** | 1200 | 382% |
| icra | 11262 | 0 | **11262** | 800 | 1408% |
| trafik | 949 | 0 | **949** | 800 | 119% |
| vergi | 544 | 475 | **1019** | 800 | 127% |
| tapu | 5314 | 0 | **5314** | 700 | 759% |
| idari | 4827 | 231 | **5058** | 1000 | 506% |
| **DOMAIN TOPLAM** | — | — | **55331** | **8800** | **629%** |

**Kanun (mevzuat) chunks**: 5496
**Qdrant overall total chunks**: 62188
