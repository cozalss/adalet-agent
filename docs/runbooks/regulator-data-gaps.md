# Regulator Data Gaps — BDDK, Sigorta Tahkim, SPK

> Tarih: 2026-05-26
> Sprint-5 W15 sonu: 4 regulator aktif (KVKK, Rekabet, Sayıştay, GİB Özelge).
> 3 regulator hâlâ erişilemez.

## Durum Tablosu

| Regulator | MCP Tool | Durum | Domain | Sprint-5 Karar |
|---|---|---|---|---|
| KVKK | search_kvkk_decisions | ✅ Aktif | tuketici | 208 chunk |
| Rekabet | search_rekabet_kurumu_decisions | ✅ Aktif | tuketici | 155 chunk |
| Sayıştay | search_sayistay_unified | ✅ Aktif | idari | 231 chunk |
| GİB Özelge | search_gib_ozelge | ✅ Aktif | vergi | 475 chunk |
| **BDDK** | search_bddk_decisions | ❌ **Tavily 433** | tuketici (finans) | Sprint-6 defer |
| **Sigorta Tahkim** | search_sigorta_tahkim_decisions | ❌ **Tavily 433** | trafik, tuketici | Sprint-6 defer |
| **SPK** | (public MCP tool yok) | ❌ Tool yok | tuketici (yatırım) | Sprint-7+ defer |

## BDDK + Sigorta Tahkim — Tavily 433 Sorunu

yargi-mcp v0.2 BDDK ve Sigorta Tahkim için Tavily Search API kullanıyor.
Tavily endpoint 433 status döndürüyor (probable: trial limit veya quota
exhausted, maintainer'ın hesabında).

**Test (2026-05-26):**
```python
data = await client._call_tool("search_bddk_decisions", {"keywords": "kredi"})
# → {"decisions": [], "error": "Failed to search BDDK decisions:
#                  Client error '433 ' for url 'https://api.tavily.com/search'"}
```

### Çözüm Yolları (Sprint-6'da)

#### A) Maintainer'a issue aç (önerilen)
- yargi-mcp GitHub: https://github.com/saidsurucu/yargi-mcp
- Issue title: "BDDK + Sigorta Tahkim search returns Tavily 433 error"
- Beklenen: maintainer kendi Tavily key'ini yeniler veya direct scraper'a geçer (1-2 hafta)

#### B) Direkt scraper yaz
- BDDK: https://www.bddk.org.tr/Kararlar — HTML scrape
- Sigorta Tahkim: https://www.sigortatahkim.org.tr/karar-arama — HTML scrape
- Effort: ~2 gün her biri için
- Risk: ToS uyumluluk; sayfa yapısı değişir

#### C) Manuel JSONL (acil ihtiyaç olursa)
- Public özet derleyiciler:
  - BDDK: yıllık faaliyet raporu (PDF) → 50-100 önemli karar
  - Sigorta Tahkim: Hakem Karar Dergisi (64 sayı 2010-2025)
- Mevcut `data/seed_state/regulator_*.jsonl` formatına uygun
- `scripts/seed/regulators.py`'de JSONL fallback path yeniden eklenebilir
- Effort: 1 gün hazırlık + seed

## SPK — Public API Yok

SPK (Sermaye Piyasası Kurulu) için:
- yargi-mcp'de tool yok
- spk.gov.tr/karar-arama — JS-heavy, scrape zor
- Yatırımcı şikayetleri Tüketici Hakem Heyeti'nde de görülür (tuketici domain'i zaten kapsar)

**Karar**: SPK'yı Sprint-7+'a defer et. Etkisi düşük (tüketici yatırımcı
şikayetleri Yargıtay 13.HD'de zaten var).

## Sprint-5 Sonu Karar

3 broken regulator için:
1. **Issue aç** (yargi-mcp GitHub'a) — 5 dk
2. **Sprint-6 plan'a B option ekle** (direct scraper, eğer issue 2 hafta içinde çözülmezse)
3. **Mevcut 4 regulator + 47K case + 5500 mevzuat ile yeterli baseline** (Sprint-5 hedef ulaşıldı, %538 üstü)

## Etki Analizi

Eksik 3 regulator'un kritikliği:

| Use Case | Etkilenir mi? | Niye |
|---|---|---|
| "Bankam izinsiz veri paylaştı" | Hafif | KVKK zaten kapsar |
| "Kredimden gizli ücret kesildi" | Orta | BDDK yokluğu hissedilir — TKHK + 6502 kapsayabilir |
| "Trafik sigortam ödemiyor" | Orta | Sigorta Tahkim yokluğu hissedilir — 17.HD ve TBK kısmen kapsar |
| "Yatırım fonu zararı" | Düşük | SPK yokluğu hissedilir ama tüketici hakem heyeti zaten var |

Sonuç: Beta launch'ta belirgin gap yok. Sprint-6'da Tavily fix gelirse
otomatik aktif olur (kod hazır).
