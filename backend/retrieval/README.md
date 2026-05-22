# retrieval

RAG pipeline — hukuk verisine erişim ve hybrid search.

## Bileşenler

- `yargi_client.py` — [yargi-mcp](https://github.com/saidsurucu/yargi-mcp) HTTP client (Yargıtay + Danıştay)
- `mevzuat_client.py` — mevzuat.gov.tr scraper
- `embedding.py` — BGE-M3 ile metin → vektör
- `vector_store.py` — Qdrant collection yönetimi
- `hybrid_search.py` — BM25 + dense + reranker
- `citation.py` — Citation verification (metin eşleşmesi)

## Akış

```
Soru → embed → Qdrant hybrid search → ilk 50 → reranker → ilk 5 → citation check
```

## Yapılacaklar

- [ ] yargi-mcp client (retry/timeout)
- [ ] BGE-M3 embedding pipeline
- [ ] Qdrant collection schema
- [ ] Hybrid search (BM25 + dense)
- [ ] Reranker
- [ ] Citation verifier (fuzzy match ≥ 0.85)
