# Regulator Karar Seed — Veri Hazırlama Rehberi

> Sprint-5 W15 — KVKK, Rekabet, SPK, BDDK, Sayıştay kararlarının manuel hazırlanması.

## Neden Manuel?

KVKK ve Rekabet Kurumu **resmi public JSON-API** sunmaz. Mevcut yollar:

1. **Resmi web sayfası** — kurum sitelerinde kararlar HTML olarak yayınlanır.
2. **PDF/Word indirme** — uzun karar metinleri PDF olarak verilir.
3. **Web scraping** — sayfanın yapısı değişebilir, ToS kısıtlı.

Bu nedenle Sprint-5 yaklaşımı: **kamuya açık karar özetleri** manuel olarak
JSONL'a kopyalanır, MIT-uyumlu açık veri ilkesiyle açık kaynak repo'ya commit edilir.

## JSONL Schema

Her satır bir karar:

```json
{
  "decision_id": "kvkk-2024-001",
  "title": "Kısa karar başlığı",
  "date": "2024-03-15",
  "body": "OLAY: ...\n\nGEREKÇE: ...\n\nSONUÇ: ...",
  "source_url": "https://www.kvkk.gov.tr/Icerik/karar/...",
  "regulator": "kvkk",
  "domain": "tuketici"
}
```

**Önemli kurallar:**

1. `body` içinde **section başlıkları** (OLAY / GEREKÇE / SONUÇ) varsa,
   `chunk_decision` otomatik bölecek ve her chunk'a section metadata ekleyecek.
2. **PII koruması**: Kararı anonimleştirilmiş halde alın. Şirket isimleri yerine
   "veri sorumlusu", "ihlal eden firma" gibi genel ifadeler kullanın.
3. **decision_id** unique olmalı: `<regulator>-<yıl>-<sıra>` formatı önerilir.
4. **source_url** resmi karar sayfasına link — citation/verifier için gerekir.
5. **domain** primary domain. Bir regulator birden fazla domain'i kapsayabilirse
   (örn. KVKK → tuketici + isHukuku), karar içeriğine göre uygun olanı seçin.

## Hedef Hacim (Sprint-5 Sonu)

| Regulator | Hedef karar sayısı | Mevcut JSONL'da |
|---|---|---|
| KVKK | 200 | 2 (örnek) |
| Rekabet Kurumu | 150 | 1 (örnek) |
| SPK | 100 | 1 (örnek) |
| BDDK | 80 | 1 (örnek) |
| Sayıştay | 170 | 2 (örnek) |
| **Toplam** | **700** | **7** |

## Veri Hazırlama Süreci (Öneri)

1. **Kaynak liste**: Kurum web sayfasındaki "Karar Özetleri" / "Kararlar" bölümü.
2. **Filtre**: Son 5 yıl (2020-2025) — güncel uygulama emsali.
3. **Kopyalama**:
   - Karar metnini OLAY/GEREKÇE/SONUÇ section'larına ayır.
   - Eğer kararda yalnız özet varsa, tek `body` blok'unda olur.
4. **Sanitize**:
   - Gerçek şahıs/şirket isimlerini "X firması", "şikayetçi", "veri sorumlusu" gibi placeholder ile değiştir.
   - TCKN/telefon vb. zaten kararlarda olmaz, ama varsa MUTLAKA çıkar.
5. **JSONL append**: Her karar tek satır olarak ilgili `regulator_<kurum>.jsonl` dosyasına eklenir.

## Çalıştırma

```bash
# Tüm regulator'ları seed et
uv run python -m scripts.seed.regulators

# Sadece KVKK
uv run python -m scripts.seed.regulators --regulator kvkk
```

Seed sonrası verify:

```bash
uv run python -c "
from retrieval.vector_store import get_qdrant
client = get_qdrant()
for reg in ('kvkk', 'rekabet', 'spk', 'bddk', 'sayistay'):
    n = client.count('mevzuat_chunks', count_filter={
        'must': [{'key': 'regulator', 'match': {'value': reg}}]
    }).count
    print(f'{reg}: {n} chunks')
"
```

## Hukuki Notlar

- Kararlar **public domain** kategorisindedir (T.C. kamu kurumu yayını).
- MIT lisans uyumlu — açık paylaşıma engel yok.
- Karar **gerçek hukuki uygulamayı** yansıtır — sistemde "uydurulmuş emsal" yok.
- Her chunk'ın `source_url` field'ı orijinal kararın resmi web sayfasına link.
