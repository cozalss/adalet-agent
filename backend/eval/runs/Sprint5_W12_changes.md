# Sprint-5 W12 — Mevzuat Genişletme 17 → 41 Kanun

> Tarih: 2026-05-25
> Hedef: Her domain için 5+ ilgili kanun seeded.

## Değişiklikler

### 1. `retrieval/mevzuat_client.py` — KANUN_KODU_TO_NUMARA expand

17 → 41 kanun. Yeni eklenenler (24 adet):

| Kategori | Kanun | Kanun No |
|---|---|---|
| Çekirdek (özel) | TTK | 6102 |
| Sosyal güvenlik | DMK, DIK, BMC, OGK | 657, 854, 5953, 5188 |
| Ekonomik düzen | BK, SIGORTA, KVKK, OHK | 5411, 5684, 6698, 6493 |
| Vergi | GVK, KVK, OTV, DV, MTV, EMLAKV, AATUHK, MYK, GIBK | 193, 5520, 4760, 488, 197, 1319, 6183, 5018, 5345 |
| Trafik/ulaşım | KGK | 4925 |
| Tapu/imar | IMARK, KAMK, KDK | 3194, 2942, 6306 |
| İdari | IHK, IHSK, DIHK, BLDK, IOIK, CK | 4734, 4735, 3071, 5393, 5302, 2872 |
| Afet | AYK | 7269 |

### 2. `scripts/seed_mevzuat.py` — TARGET_LAWS expand

17 → 41 entry. Alias (TK=KTK, KK=TPK) entries seed'den çıkarıldı, sadece canonical isimler seed ediliyor.

### 3. `agents/config.py` — DOMAIN_TO_KANUN_KODU expand

Her domain için 5+ kanun. Toplam mapping satırı 8 domain × ortalama 7 kanun:

| Domain | Kanun sayısı (öncesi → sonrası) | Yeni eklenenler |
|---|---|---|
| tuketici | 1 → 8 | TBK, TTK, BK, Sigortacılık, KVKK, RKHK, Ödeme H. |
| isHukuku | 3 → 9 | İSGK, DMK, TBK, Deniz İş, Basın, Özel Güvenlik |
| kira | 1 → 5 | TMK, KMK, Kentsel Dönüşüm, Belediye |
| icra | 1 → 6 | TTK, AATUHK, BK, SGK, Konkordato |
| trafik | 2 → 5 | Sigortacılık, TBK, Karayolu Taşıma |
| vergi | 3 → 10 | KVK, ÖTV, DV, MTV, EmlakV, AATUHK, Mali Yönetim |
| tapu | 3 → 6 | KMK, Kamulaştırma, Kentsel Dönüşüm |
| idari | 3 → 9 | İhale, İhale Sözleşmeleri, Dilekçe, Belediye, İl Özel, Çevre |

### 4. `agents/config.py` — REGULATOR_TO_DOMAINS yeni

Sprint-5 W15 hazırlığı: KVKK + Rekabet + SPK + BDDK + Sayıştay → domain mapping.

### 5. `scripts/smoke_mevzuat_coverage.py` — yeni dosya

8 domain × 3 sorgu = 24 koşma. Beklenen sonuç: `kanun@1 >= 0.85`.

Kullanım:
```bash
uv run python -m scripts.smoke_mevzuat_coverage
```

### 6. `tests/agents/test_mevzuat_node.py` — 2 yeni test

- `test_boost_sprint5_expanded_tuketici`: 8-kanun multi-koDu boost
- `test_boost_sprint5_kira_includes_kmk`: KMK 634 kira'ya eklenmiş

## Sonraki Adımlar

W13 — Tier-1 zayıf domain seed:
- `scripts/seed/config.py` DOMAINS keyword genişleme
- `scripts/seed/sources.py` Yargıtay daire (12.HD, 17.HD, vb.) + tarih penceresi 4→8
- `eval/domain_audit.py` per-domain karar sayım raporu

## Verify

```bash
# Test yeşil
uv run pytest tests/agents/test_mevzuat_node.py -v

# Mypy yeşil
uv run mypy retrieval/mevzuat_client.py agents/config.py scripts/seed_mevzuat.py scripts/smoke_mevzuat_coverage.py --strict

# Mevzuat seed (re-seed gerekirse — offline 10-12h)
uv run python -m scripts.seed_mevzuat

# Coverage smoke (re-seed sonrası)
uv run python -m scripts.smoke_mevzuat_coverage
```
