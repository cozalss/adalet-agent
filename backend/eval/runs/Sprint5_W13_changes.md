# Sprint-5 W13 — Tier-1 Zayıf Domain Genişletme

> Tarih: 2026-05-25
> Hedef: icra, trafik, vergi, tapu, idari → 100 → 800 karar/domain.

## Değişiklikler

### 1. `scripts/seed/sources.py` — Tarih penceresi 4 → 8

`_DATE_WINDOWS`: 2014-2026 (4 pencere) → 2010-2026 (8 pencere). Beklenen coverage artışı 2× per-keyword.

### 2. `scripts/seed/sources.py` — Chamber filter desteği

`DecisionSource.iter_refs` Protocol'üne `chamber: str | None = None` parametresi eklendi.

- `_BedestenSource.iter_refs`: `chamber` Bedesten API'sine `birimAdi` parametresi olarak iletilir.
- `AnayasaSource.iter_refs`: AYM chamber filter desteklemez (Genel Kurul/Komisyon ayrımı farklı yere düşer), parametre alır ama yok sayar.

### 3. `scripts/seed/config.py` — DomainConfig.chambers field

Frozen dataclass'a `chambers: dict[str, tuple[str, ...]] | None` eklendi. Default None (geri uyumluluk).

### 4. `scripts/seed/config.py` — Zayıf domainlere chambers

| Domain | Court | Chambers |
|---|---|---|
| icra | yargitay | 12. HD (icra-iflas), 19. HD (kambiyo), 23. HD (iflas) |
| trafik | yargitay | 17. HD (tazminat), 4. HD (sigorta tahkim) |
| trafik | danistay | 12. Daire (sürücü belgesi) |
| vergi | danistay | 4. Daire (gelir), 7. Daire (gümrük), 9. Daire (genel vergi) |
| tapu | yargitay | 1. HD (tapu iptali), 8. HD (izale-i şuyu), 14. HD (kadastro) |
| tapu | danistay | 6. Daire (kamulaştırma) |
| idari | danistay | 5. D (memur), 6. D (imar), 10. D (genel), 12. D (eğitim), 13. D (ihale) |

### 5. `scripts/seed/config.py` — Domain keyword genişleme (+6 keyword/domain)

| Domain | Yeni keyword'ler |
|---|---|
| icra | maaş haczi, üçüncü kişi istihkak, hisse haczi, ihtiyati haciz, icra emri, borçlu temerrüdü |
| trafik | ZMSS poliçesi, sürücü belgesi iptali, tutanak süresi, trafik para cezası, ağır kusur, sigorta limiti |
| vergi | özel tüketim vergisi, damga vergisi, motorlu taşıt vergisi, emlak vergisi, amme alacağı, vergi ceza ihbarnamesi |
| tapu | kamulaştırma bedeli, kamulaştırmasız el atma, imar planı iptali, ifraz tevhid, ruhsatsız yapı, kentsel dönüşüm |
| idari | ihaleden yasaklanma, ihale uhdesinde kalma, memur soruşturması, çevre para cezası, belediye meclis kararı, yapı tatil tutanağı |

### 6. `scripts/seed/fetch.py` — Chamber-aware streaming

`stream_decisions` her keyword × her chamber → ayrı iter_refs çağrısı. chambers=None ise tek-pass (eski davranış).

### 7. `eval/domain_audit.py` — yeni dosya

Per-domain karar sayım raporu (status=ok kayıtlar). `SPRINT5_TARGETS` ile karşılaştırır, gap tablosu çıkarır.

Kullanım:
```bash
uv run python -m eval.domain_audit
# Konsola tablo + eval/runs/Sprint5_domain_audit_<ts>.md yazar

uv run python -m eval.domain_audit --final
# Sprint-5 final dosya adı: Sprint5_domain_audit_final.md
```

## Beklenen API Yük Artışı

Sprint-5 W13 ile zayıf domain'lerde:
- Keyword sayısı: ~20 → ~26 (×1.3)
- Tarih penceresi: 4 → 8 (×2)
- Chamber filter: 1 → 2-5 (×2-5)

Toplam multiplicative: 5.2 - 13× per domain. Bedesten rate limiter (10/30s) ile bottleneck olmaz; seed run zamanı uzar (~2x-3x).

## Sonraki Adımlar

W14 — Güçlü domain (tuketici, isHukuku, kira) alt-kategori derinleştirme:
- TKHK m.4/11/48/49/61/66/83/84 keyword'leri
- İK m.17/24/25/41/55 + SGK m.4-4/86 keyword'leri
- TBK m.299/315/339/344/347/350/351/355 keyword'leri
- AYM bireysel başvuru + Yargıtay İBK seed
- `retrieval/chunker.py`: karar gerekçe/sonuç ayrımı

## Verify

```bash
# Test yeşil (mevcut test'ler bozulmadı)
uv run pytest tests/agents/test_mevzuat_node.py tests/scripts/ -v

# Yeni weak domain seed (offline ~12h, 5 domain × 700 ek karar)
uv run python -m scripts.seed_decisions --domain icra --limit-per-domain 800
# benzer şekilde trafik, vergi, tapu, idari

# Audit kontrol
uv run python -m eval.domain_audit
# Beklenen: zayıf domain'ler ≥ 700 toplam
```
