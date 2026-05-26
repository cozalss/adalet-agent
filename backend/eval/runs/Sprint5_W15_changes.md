# Sprint-5 W15 — Düzenleyici Otorite Kararları

> Tarih: 2026-05-25 (initial JSONL plan) → 2026-05-26 (**MCP refactor**)
> Hedef: KVKK + Rekabet + SPK + BDDK + Sayıştay = ~700-1500 karar, yeni dimension (regulator).

## 🔄 2026-05-26 Refactor — Local yargi-mcp MCP Tools

Sprint-5 W15 implementation sırasında **local yargi-mcp v0.2.0+** kurulurken
26 tool keşfedildi: `search_kvkk_decisions`, `search_rekabet_kurumu_decisions`,
`search_sayistay_unified`, `search_gib_ozelge` ve daha fazlası. Bu, **manuel JSONL
hazırlama planını gereksiz kıldı** — MCP'den tek çağrı ile binlerce karar
gelebilir.

### Refactor Özeti

| Eski (Manuel JSONL) | Yeni (MCP Tools) |
|---|---|
| 5 stub JSONL dosyası | Aktif HTTP MCP fetch |
| ~7 örnek karar | ~1500+ karar (4 regulator × 5 sayfa) |
| Manuel anonim hazırlama gerekli | Public API'den direkt |
| BDDK / SPK / Sigorta Tahkim: yok | KVKK / Rekabet / Sayıştay / GİB Özelge: var |

### Çalışan Regulator Tools (probe 2026-05-26)

| Regulator | Tool | Durum | Notlar |
|---|---|---|---|
| KVKK | `search_kvkk_decisions` | ✅ | Karar başına title+description (summary) — 10/sayfa |
| Rekabet Kurumu | `search_rekabet_kurumu_decisions` | ✅ | Karar başına UUID + tarih — 10/sayfa |
| Sayıştay | `search_sayistay_unified` | ✅ | `decision_type=daire`, 7414 toplam — 20/sayfa |
| GİB Özelge | `search_gib_ozelge` | ✅ | 18000+ özelge, vergi yorumları — 20/sayfa |
| BDDK | `search_bddk_decisions` | ❌ | Tavily 433 — upstream broken |
| Sigorta Tahkim | `search_sigorta_tahkim_decisions` | ❌ | Tavily 433 — upstream broken |

### Yeni Dosyalar / Değişiklikler

**`retrieval/yargi_client.py`** (+~200 satır):
- `RegulatorDecision` dataclass (yeni)
- 6 yeni async metod: `search_kvkk`, `search_rekabet`, `search_sayistay`,
  `search_bddk`, `search_gib_ozelge`, `search_sigorta_tahkim`
- `get_regulator_document(regulator, doc_ref)` — markdown fetch
- `_extract_decision_list()` + `_parse_regulator_items()` generic parserlar

**`scripts/seed/regulators.py`** (refactor, 200 → 280 satır):
- JSONL okuyucu yerine MCP fetch loop
- `REGULATOR_KEYWORDS`: her regulator için 8-10 broad keyword
- Dedup: aynı `decision_id` farklı keyword'lerden tekrarlanmaz
- `--max-pages` argument: kontrollü hacim

**`agents/config.py`** (REGULATOR_TO_DOMAINS güncelleme):
- `gib_ozelge → ("vergi",)` eklendi
- `sigorta_tahkim → ("trafik", "tuketici")` eklendi (kullanılmıyor şu an)
- Yorumlarda upstream durumu belirtildi

### CLAUDE.md Uyum

- Hukuki referans uydurma yok — MCP gerçek public karar verisi döndürür
- Test verisinde gerçek PII yok — KVKK/Rekabet/Sayıştay public arşivleri zaten
  anonimleştirilmiş (kurumlar PII'yi resmi olarak temizler)
- Production'da OpenAI/Anthropic API yok — yargi-mcp lokal self-hosted
- Hardcoded secret yok — `YARGI_MCP_URL` env üzerinden

### Verify (yeni)

```bash
# 4 regulator full seed
uv run python -m scripts.seed.regulators --regulator all --max-pages 5

# Beklenen: 1000-1500 karar / ~1500-2500 chunk
# (KVKK ~300, Rekabet ~300, Sayıştay ~500, GİB ~400)
```

---

## Önceki Plan (2026-05-25, deprecated — JSONL approach)



## Değişiklikler

### 1. `scripts/seed/regulators.py` — yeni dosya

Manuel hazırlanmış `data/seed_state/regulator_<kurum>.jsonl` dosyalarından regulator kararlarını okur, chunk_decision ile parçalar, Qdrant'a payload `regulator` field'ı ile yazar.

5 regulator destek: kvkk, rekabet, spk, bddk, sayistay.

Kullanım:
```bash
uv run python -m scripts.seed.regulators              # tümü
uv run python -m scripts.seed.regulators --regulator kvkk
```

### 2. `data/seed_state/regulator_README.md` — yeni dosya

Veri hazırlama rehberi:
- JSONL schema
- Hedef hacim (KVKK 200, Rekabet 150, SPK 100, BDDK 80, Sayıştay 170)
- Sanitization kuralları (anonimleştirme, PII koruması)
- Veri hazırlama süreci (kaynak → filter → sanitize → JSONL)

### 3. `data/seed_state/regulator_*.jsonl` — 5 stub dosya

Her regulator için 1-2 anonimleştirilmiş örnek karar:
- `regulator_kvkk.jsonl` — 2 karar (tüketici + iş hukuku)
- `regulator_rekabet.jsonl` — 1 karar (tüketici)
- `regulator_spk.jsonl` — 1 karar (yatırımcı koruması)
- `regulator_bddk.jsonl` — 1 karar (banka tüketicisi)
- `regulator_sayistay.jsonl` — 2 karar (idari + vergi)

Toplam: 7 örnek karar — Sprint-5 sonuna kadar 700+ karara çıkarılacak.

### 4. Payload Field Eklemeleri

Qdrant payload (`retrieval/vector_store.py` schema değişikliği gerektirmez, dict[str, Any] generic):

| Field | Değerler | Niye |
|---|---|---|
| `regulator` | yargi / kvkk / rekabet / spk / bddk / sayistay | Hangi kurum kararı |
| `decision_type` | yargi / regulator | Genel kategori (Yargıtay vs düzenleyici) |
| `section` | olay / gerekce / sonuc | W14'ten geliyor — chunk_decision |

Eski chunks (Sprint-4 öncesi) bu field'lara sahip değil — geri uyumlu (filter `must` yerine `should` kullanılırsa). 

### 5. `agents/config.py` — REGULATOR_TO_DOMAINS (W12'de hazırlandı)

Sprint-5 W15'te aktif olarak kullanılır:
```python
REGULATOR_TO_DOMAINS = {
    "kvkk":     ("tuketici", "isHukuku"),
    "rekabet":  ("tuketici",),
    "spk":      ("tuketici",),
    "bddk":     ("tuketici",),
    "sayistay": ("idari", "vergi"),
}
```

`scripts/seed/regulators.py` JSONL'da domain belirtilmemişse bu mapping'in ilk elementini kullanır.

## Beklenen Sonuç

**Smoke sorgu:**
```python
"Bankam izinsiz veri paylaştı"
```

**Beklenen top-5 dağılım:**
1. KVKK 2024/X kararı (regulator=kvkk, domain=tuketici)
2. 6698 sayılı KVKK m.7 madde (kanun_kodu=6698, doc_type=law)
3. BDDK 2024/Y kararı (regulator=bddk)
4. Yargıtay 13.HD ilgili karar (court=yargitay, domain=tuketici)
5. TBK m.49 haksız fiil (kanun_kodu=6098)

→ **Çok-kaynaklı atıf**: kanun + Yargıtay + KVKK + BDDK — sistemin "gerçek hukuk uygulaması" hissini verir.

## Sonraki Adımlar

W16 — Otomatik tazeleme cron:
- `scripts/refresh_resmi_gazete.py` — günlük poll
- `scripts/refresh_yargitay_recent.py` — haftalık delta
- `core/scheduler.py` — APScheduler factory
- `backend/Dockerfile` — scheduler container'da çalışır

## Verify

```bash
# Stub veri ile smoke seed
uv run python -m scripts.seed.regulators

# Qdrant'ta regulator chunk sayısı
uv run python -c "
from retrieval.vector_store import get_client, COLLECTION_NAME
import asyncio
async def main():
    client = get_client()
    try:
        total = (await client.count(COLLECTION_NAME)).count
        print(f'Total: {total}')
        for reg in ('kvkk', 'rekabet', 'spk', 'bddk', 'sayistay'):
            from qdrant_client import models
            f = models.Filter(must=[models.FieldCondition(key='regulator', match=models.MatchValue(value=reg))])
            n = (await client.count(COLLECTION_NAME, count_filter=f)).count
            print(f'{reg}: {n}')
    finally:
        await client.close()
asyncio.run(main())
"

# Multi-source retrieval smoke
uv run python -c "
from retrieval.hybrid_search import search
import asyncio
hits = asyncio.run(search('bankam izinsiz veri paylaştı', top_k=10))
for h in hits[:5]:
    print(h.metadata.get('regulator'), h.metadata.get('court'), h.score)
"
```
