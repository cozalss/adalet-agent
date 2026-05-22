# Veri Alma Pipeline'ı

Üç katmanlı veri akışı: **bulk indexleme** (bir kere) + **live retrieval** (her soruda) + **citation verification** (her iddiada).

---

## 1. Kaynaklar

| Kaynak | URL | Erişim Yöntemi | Veri Türü |
|--------|-----|----------------|-----------|
| Yargıtay | yargitay.gov.tr | [yargi-mcp](https://github.com/saidsurucu/yargi-mcp) | Mahkeme kararları |
| Danıştay | danistay.gov.tr | yargi-mcp | İdari kararlar |
| Mevzuat | mevzuat.gov.tr | HTTP scrape + parse | Yasa maddeleri |
| Resmi Gazete | resmigazete.gov.tr | RSS / scrape | Güncel mevzuat |
| UYAP | mevzuat.adalet.gov.tr | scrape | Çapraz doğrulama |

Hepsi **kamuya açık** → KVKK / etik kurul sorunu yok.

---

## 2. yargi-mcp Kurulumu

Açık kaynak MCP sunucusu, lokal olarak çalıştırılır.

```bash
# Repoyu klonla
git clone https://github.com/saidsurucu/yargi-mcp.git ../yargi-mcp
cd ../yargi-mcp

# Bağımlılıklar + sunucuyu başlat
uv sync
uv run python -m yargi_mcp.server --port 5001
```

`docker-compose.yml`'a eklemek istersen (önerilen):

```yaml
yargi-mcp:
  build: ../yargi-mcp
  ports:
    - "5001:5001"
  restart: unless-stopped
```

`.env`'de: `YARGI_MCP_URL=http://localhost:5001`.

---

## 3. Katman A — Bulk Indexleme (offline, bir kere)

**Ne zaman:** Sprint 1 sonunda, sonra ayda bir refresh.

**Akış:**

```
yargi-mcp ──┐
            ├──> backend/scripts/seed.py ──> BGE-M3 embed ──> Qdrant
mevzuat ────┘
```

**Adımlar:**

1. yargi-mcp'den toplu kararları çek (kategori bazlı: tüketici, iş, kira)
2. mevzuat.gov.tr'den ilgili kanunları çek (TBK, İK, TKHK)
3. Her dokümanı **chunk'la** (1000 token + 200 overlap)
4. BGE-M3 ile **embed** et
5. Qdrant collection'a **upsert** et

Hedef: ~50.000 karar + ~5.000 madde = ~250.000 chunk. Bir defalık 3-6 saat çalışır.

**Çalıştırma:**

```bash
cd backend
uv run python scripts/seed.py --domain tuketici --limit 10000
uv run python scripts/seed.py --domain isHukuku --limit 10000
uv run python scripts/seed.py --domain kira --limit 5000
```

---

## 4. Katman B — Live Retrieval (her soruda)

**Ne zaman:** Kullanıcı soru sorduğunda, milisaniye içinde.

**Akış:**

```
Soru ──> BGE-M3 embed ──> Qdrant hybrid search (BM25 + dense)
                              │
                              v
                         İlk 50 sonuç
                              │
                              v
                         Reranker (BGE)
                              │
                              v
                         İlk 5 ──> Ajanlara verilir
```

Bu pipeline `backend/retrieval/hybrid_search.py` içinde.

**Cache:** Redis'te 1 saatlik soru → sonuç cache'i (aynı soruyu tekrar embed etme).

---

## 5. Katman C — Citation Verification (her iddiada)

**Ne zaman:** Doğrulama ajanı her hukuki referansı kontrol ederken.

**Akış:**

```
Ajan iddiası: "TKHK Madde 11"
                │
                v
        yargi-mcp / mevzuat.gov.tr ──> gerçek madde metni fetch
                │
                v
        fuzzy match (Levenshtein ≥ 0.85)
                │
        ┌───────┴───────┐
        v               v
   [GEÇERLİ]       [REDDET, yeniden dene]
```

**Önemli:**
- Verifier **canlı kaynaktan** fetch eder, cache'ten değil (en güncel veri için)
- Bağlantı hatasında ajana "doğrulanamadı" sinyali → cevap **reddedilir**
- Max 3 iter sonra başarısız → kullanıcıya: *"Bu konuda emin değilim, avukata danışın."*

---

## 6. Veri Politikası

### KVKK
- Yargıtay kararlarındaki **kişisel veriler** (isim, TC, telefon) anonimleştirilir
- Her chunk'a metadata: `{"source_url": "...", "fetched_at": "...", "anonymized": true}`
- Kullanıcı sorularını **gerekmedikçe loglama**; loglarsan **maskele**

### Lisans
- Yargıtay/Danıştay kararları → kamuya açık, atıf gereklidir
- mevzuat.gov.tr → kamu malı
- Eğitim verisi olarak ticari kullanım için → ekstra danış (akademik OK)

### Yedekleme
- Qdrant snapshot haftada bir → `data/backup/qdrant-YYYY-MM-DD.tar.zst`
- Raw veri `data/training/raw/` altında, git LFS

---

## 7. Performans Bütçesi

| Operasyon | Hedef Latency |
|-----------|---------------|
| Embed (1 soru) | < 50 ms |
| Qdrant hybrid search | < 100 ms |
| Reranker (5 sonuç) | < 200 ms |
| Citation verify (1 iddia) | < 500 ms |
| **Toplam retrieval** | **< 1 sn** |

Eğer aşılıyorsa: ilk önce embedding cache, sonra reranker batch.

---

## 8. Test Veri Seti

`data/benchmark/v1.jsonl` — ekibin manuel etiketlediği 500 vaka. Format için `data/README.md`'ye bak.

Bu seti pipeline kalitesini ölçmek için kullanırız (Ragas faithfulness, citation precision).
