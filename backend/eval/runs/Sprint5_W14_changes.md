# Sprint-5 W14 — Tier-2 Güçlü Domain Derinlik + Section-Aware Chunking

> Tarih: 2026-05-25
> Hedef: tuketici, isHukuku, kira için TKHK/İK/TBK madde bazlı alt-kategori; karar metinlerinde gerekçe/sonuç ayrımı.

## Değişiklikler

### 1. `retrieval/chunker.py` — `chunk_decision` yeni

Yargıtay/Danıştay karar metnini section marker'ları ile böler:
- **OLAY/DAVA/İSTEM** → section="olay"
- **GEREKÇE/HUKUKİ DEĞERLENDİRME** → section="gerekce"
- **HÜKÜM/SONUÇ/KARAR** → section="sonuc"

Marker yoksa fallback `chunk_text` (section="gerekce" default).

Retrieval kalitesi:
- "tazminat miktarı hesabı" → gerekçe section'a yakın
- "karar verildi mi" → sonuc section'a yakın

### 2. `scripts/seed/pipeline.py` — section payload

`_build_pending_chunks` artık `chunk_decision` çağırır. Her chunk payload'una `section` field eklenir. Schema değişikliği: yeni payload field, geri uyumlu (default "gerekce").

### 3. `scripts/seed/config.py` — Tier-2 alt-kategori keyword'leri

| Domain | Yeni keyword'ler |
|---|---|
| tuketici | TKHK 11 cayma, TKHK 48 mesafeli cayma, TKHK 49 kapıdan cayma, TKHK 61 garanti, TKHK 66 abonelik, TKHK 83 hakem, TKHK 84 mahkeme, ayıp ihbarı süresi, yenilemesiz iade |
| isHukuku | İK 17 süreli fesih, İK 24 işçi haklı, İK 25 işveren haklı, İK 41 fazla mesai, İK 55 yıllık izin, SGK 4-1a sigortalılık, SGK 86 emeklilik, iş sözleşmesi geçersizlik, ücret bordrosu eksik |
| kira | TBK 299 fesih bildirim, TBK 315 ihtarname, TBK 339 kefil, TBK 344 artış, TBK 347 yenileme, TBK 350 tahliye sebepleri, TBK 351 kiraya veren ihtiyaç, TBK 355 işyeri kirası, sözleşme süre bitimi |

### 4. `scripts/seed/config.py` — Tier-2 chamber filtreleri

| Domain | Court | Chambers |
|---|---|---|
| isHukuku | yargitay | 9. HD (genel), 22. HD (özel), 21. HD (iş kazası) |
| kira | yargitay | 3. HD (alacak), 6. HD (sözleşme) |

(tuketici için chambers eklenmedi — 13. HD primary, mevcut keyword-based seed yeterli.)

### 5. `tests/retrieval/test_chunker_decision.py` — yeni

7 test:
- Section marker'larla 3 section yakalanır
- Marker yoksa flat fallback + default "gerekce"
- KARAR: → sonuc classification
- Boş metin → boş liste
- min_chars altı → boş
- Content preservation
- chunk_text uyumluluk

### 6. AYM Bireysel Başvuru + İBK Seeding (mevcut altyapı reuse)

Anayasa Mahkemesi seed mevcut altyapıda zaten Anayasa Mahkemesi'nin bireysel başvuru kararlarını çekiyor (`AnayasaSource` + `decision_type="bireysel_basvuru"`). Yeni TKHK/İK/TBK madde-bazlı keyword'ler AYM'de de aratılacak — mülkiyet hakkı, çalışma hakkı, eşit muamele ihlali iddiası içeren bireysel başvuru kararları otomatik kapsanır.

Yargıtay Hukuk Genel Kurulu (HGK) ve İçtihatları Birleştirme Kararları (İBK) için ayrı chamber tanımı gerekirdi ancak Bedesten API'sinde bunlar "Hukuk Genel Kurulu" / "İçtihatları Birleştirme Genel Kurulu" gibi birimAdi ile geçer. Sonraki sprint'te eklenebilir.

## Sonraki Adımlar

W15 — Düzenleyici otorite kararları:
- `scripts/seed/regulators.py` (KVKK + Rekabet + SPK + BDDK + Sayıştay)
- Vector store payload: `regulator` field
- Domain mapping: REGULATOR_TO_DOMAINS (zaten W12'de hazırlandı)

## Verify

```bash
# Yeni chunker testleri
uv run pytest tests/retrieval/test_chunker_decision.py -v

# Mypy
uv run mypy retrieval/chunker.py scripts/seed/pipeline.py --strict

# Tier-2 re-seed (offline ~6h, 3 domain × ~700 yeni karar)
uv run python -m scripts.seed_decisions --domain tuketici,isHukuku,kira

# Section dağılımı kontrol
uv run python -c "
from retrieval.vector_store import get_qdrant
client = get_qdrant()
for sec in ('olay', 'gerekce', 'sonuc'):
    n = client.count('mevzuat_chunks', count_filter={'must':[{'key':'section','match':{'value':sec}}]}).count
    print(f'{sec}: {n}')
"
# Beklenen: gerekce > olay > sonuc (tipik karar dağılımı)
```
