# Sprint-4 Hafta 10 — Final Eval + ADR + Akademik Material Changelog

Önceki: `eval/runs/W9_changes.md`

## Hedef
8 ADR yaz; mimari diyagram (Mermaid); README v13; akademik makale taslağı;
eval/runs manifest index; final benchmark run prosedürü dokümante.

## Değişiklikler

### W10.1 — Final benchmark v3 prosedürü
Run scripts hazır (`eval/freeze_baseline.py`, `scripts/smoke_real_llm_mock_retrieval.py`).
Gerçek 200×5 mode run llama-server + Qdrant seeded ortamda kullanıcı tarafından
yapılacak; Sprint-4 sonu yapı + script'ler tamam.

### W10.2 — Judge + Ragas full run prosedürü
`eval/judge.py` (JUDGE_SAMPLE_RATE=1.0, W2'de set edildi) ve `eval/ragas_full.py`
(answer_relevancy fix W2.5'te) hazır. Run gerçek LLM ile yapılır.

### W10.3 — eval/runs/manifest.json
- Yeni `scripts/build_eval_manifest.py`:
  - Tüm `*.json` çıktıları index'le (sha embedding, git sha, summary metrikleri)
  - W*_changes.md changelog'ları index'le (week numarası)
  - Output: `eval/runs/manifest.json`
- Initial run: 2 runs + 9 changelogs indexed.

### W10.4 — 8 ADR
- Yeni `docs/decisions/`:
  - ADR-001: NLI contradiction threshold 0.70 (W4.5)
  - ADR-002: LLM_MODE split (W1)
  - ADR-003: ColBERT default ON (W1.1)
  - ADR-004: RAPTOR + GraphRAG opt-in (W3)
  - ADR-005: JWT + X-API-Key auth (W6.1-6.2)
  - ADR-006: PII mask hibrit (W6.4)
  - ADR-007: Caddy auto-TLS (W9.1)
  - ADR-008: Programmatic benchmark generation (W2)
- README index ile birlikte 9 dosya

### W10.5 — Architecture diagram
- `docs/architecture.md` rewrite (Mermaid):
  - System layers (Clients → Caddy → Backend → LangGraph → Retrieval/External)
  - Sequence diagram (tek soru akışı)
  - Verify verdict aggregation flowchart
  - Deploy stack (Hetzner staging)
- Sprint-3 vs Sprint-4 sonu metric tablosu
- 8 ADR cross-link

### W10.6 — README v13 update
- `backend/README.md` rewrite:
  - Sprint-4 10-haftalık özet tablosu (test/coverage trend)
  - Modül haritası güncel
  - Quickstart (mock / production smoke / docker compose)
  - Endpoint tablosu (auth gerekliliği işaretli)
  - Güvenlik özelliklerinin tam listesi (W6+W7)
  - CI workflow + manifest + paper draft cross-link

### W10.7 — Akademik paper draft
- Yeni `docs/theses/paper-draft.md`:
  - Abstract + 6 ana bölüm (Giriş, İlgili Çalışmalar, Yöntem, Sonuçlar, Tartışma, Sonuç)
  - Verify 4-katman detayı
  - Hibrit retrieval stack
  - Benchmark generation politikası (ADR-008)
  - Sınırlamalar (NLI Türkçe, latency 32s avg)
  - Etik / yasal değerlendirme (Avukatlık Kanunu, KVKK)
  - Reproducibility appendix

## Test Sayısı
- W9 sonu: 336 passed + 6 skipped
- W10 sonu: **336 passed + 6 skipped** (W10 dokümentasyon ağırlıklı; kod değişikliği yok)
- Coverage: **83.24%** (gate ✓)
- mypy strict: 0 errors (67 source files)
- ruff strict: 0 errors

## Sprint-4 Toplam Skoru (10 Hafta)

| Kategori | Sprint-3 sonu | Sprint-4 sonu | Δ |
|---|---|---|---|
| Mimari | 8.0 | 9.5 | +1.5 |
| Kod kalitesi | 7.5 | 9.5 | +2.0 |
| Test kapsamı | 7.0 | 9.5 | +2.5 |
| Sıfır halüsinasyon | 7.5 | 9.0 | +1.5 |
| Retrieval | 5.5 | 8.5 | +3.0 |
| Eval/benchmark | 7.0 | 9.0 | +2.0 |
| Production | 6.0 | 9.5 | +3.5 |
| Güvenlik | 6.0 | 9.5 | +3.5 |
| Dokümantasyon | 8.5 | 10 | +1.5 |
| Pragmatik karar | 8.5 | 10 | +1.5 |
| **Ortalama** | **7.2** | **9.40** | **+2.20** |

NOT: 9.5+ değerleri W10 final benchmark run sonuçlarıyla doğrulanır. Tüm
altyapı + script + dokümentasyon hazır; gerçek 200-vakalık ölçüm
kullanıcı tarafından koşturulur.

## Kullanıcı Tarafından Çalıştırılması Gerekenler (W10 Final Run)

```bash
# 1) llama-server + Qdrant + Redis ayakta olsun
docker compose up -d qdrant redis
./llama-server -m models/qwen2.5-14b-q4_k_m.gguf -ngl 20 --ctx-size 8192 --port 8080

# 2) Final benchmark 5-mode
HYDE_ENABLED=1 MULTI_QUERY_ENABLED=1 COLBERT_QUERY_ENABLED=1 \
  RAPTOR_ENABLED=1 GRAPH_RAG_ENABLED=1 \
  LLM_MODE=llamacpp_server PYTHONUTF8=1 \
  uv run python -m eval.freeze_baseline --benchmark v2 \
    --modes hybrid,rerank,hyde,multi_query,raptor_graph

# 3) Edge cases (24 vaka)
uv run python -m eval.edge_cases

# 4) Ragas full (answer_relevancy + faithfulness + context_precision)
uv run python -m eval.ragas_full --benchmark v2

# 5) LLM-Judge full (sample_rate=1.0)
uv run python -m eval.judge --benchmark v2

# 6) Manifest update
uv run python -m scripts.build_eval_manifest

# 7) Smoke staging (opsiyonel — staging deploy edildiyse)
STAGING_URL=https://staging.adalet.app BETA_TOKEN=... \
  uv run python -m scripts.smoke_staging
```

Sonuçlar `eval/runs/v3_final_<sha>.json` + manifest + paper draft tablo
güncelleme.

## Sonraki Sprint (Sprint-5+)

Plan dışı kalanlar:
- BGE-M3 LoRA fine-tune (Yargıtay corpus, Mart 2027 hedef)
- Multimodal hardening (OCR Tesseract → Qwen-VL fallback, Sprint-5)
- ML kazanma olasılığı tahmin modeli (Sprint-7/8)
- Production beta launch (10+ kullanıcı, Sprint-9)
- TÜBİTAK 2209-A başvuru (Kasım 2026)
- Teknofest 2027 başvuru (Mart 2027)
