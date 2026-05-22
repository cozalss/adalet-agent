# Backend Scripts

CLI script'leri — bir kerelik veya periyodik işlemler için.

## Script'ler

| Dosya | Görev |
|-------|-------|
| `seed.py` | (TODO) Tam bulk indexleme — production için, henüz update bekliyor |
| `mini_seed.py` | Mini end-to-end seed (6 karar, ~24 chunk) — pipeline doğrulama |
| `smoke_test_yargi.py` | yargi-mcp bağlantı testi (3 sorgu) |
| `test_search.py` | Hybrid search test (Qdrant'taki seed verisinde) |
| `list_tools.py` | yargi-mcp tool şemalarını listele (debug için referans) |

## Çalıştırma

```bash
cd backend

# Tek domain
uv run python scripts/seed.py --domain tuketici --limit 1000

# Tüm domainler
uv run python scripts/seed.py --domain all --limit 10000
```

## Önkoşullar

```bash
# 1. Qdrant + Redis ayakta olmalı
docker compose up -d

# 2. yargi-mcp ayakta olmalı (ayrı repo)
cd ../yargi-mcp && uv run python -m yargi_mcp.server --port 5001

# 3. Backend bağımlılıkları kurulu olmalı
cd backend && uv sync
```

## İlk Yükleme Hedefi

- ~50.000 Yargıtay kararı (tüketici + iş + kira)
- ~5.000 mevzuat maddesi (TBK, İK, TKHK, SGK)
- Chunk boyutu: 1000 token + 200 overlap
- Toplam: ~250.000 vektör
- Beklenen süre: 3-6 saat (CPU embedding ile)
