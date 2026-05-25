# ADR-004 — RAPTOR + GraphRAG: opt-in, offline-built

**Durum:** Accepted
**Tarih:** 2026-05-21
**Sprint:** 4 / W3

## Bağlam
İki SOTA retrieval tekniği değerlendirildi:

- **RAPTOR** (Sarthi et al. 2024) — hiyerarşik özet ağacı. Uzun Yargıtay
  kararlarında "üst düzey konsept aramak" + "ilgili paragrafa inmek" sorununu
  çözüyor. Yapım maliyeti: LLM özetleme (k=3 hops, ~30dk Qwen 14B 800 chunk).
- **GraphRAG** (Edge et al. 2024) — bilgi grafı. "TKHK m.11 → m.12 referansı"
  gibi cross-citation expansion sağlıyor. Yapım maliyeti: ucuz (regex extract
  + edge build, LLM gerek yok).

İkisi de **tabletop'tan production'a geçişte risk barındırıyor**:
- RAPTOR: process startup'ta 50-200MB pickle load
- GraphRAG: NetworkX 167+ node graph in-memory
- Test order bağımlılığı (W3.5 bug yakalandı: pickle class identity)

## Karar
**İkisi de opt-in env-gated:**
- `RAPTOR_ENABLED=1` + `data/raptor/tree.pkl` mevcut → emsal traversal sırasında merge
- `GRAPH_RAG_ENABLED=1` + `data/graph/legal_graph.json` mevcut → emsal_node neighbor expand

**Offline build:**
- `scripts/build_raptor.py` — Qdrant scroll → semantic cluster → tree
- `scripts/build_graph.py` — Qdrant scroll → citation regex → edge

Production runtime SADECE pickle/JSON load yapar (LLM gerek yok). Yeniden
build haftada bir crontab veya yeni karar batch'i alındığında.

## Sonuç
- Default OFF: graph topology W2 ile aynı, regression riski sıfır
- ENV=1 ile kademeli rollout mümkün
- Build script'leri test edildi (8 + 3 unit test geçti)
- Test order bug çözümü: dict-based pickle (v2) + `force_enabled` flag

## Alternatifler
- **Always-on RAPTOR**: build edilmemişse boş index — sessiz fallback,
  ama developer için confusing. Tercih: explicit ENV.
- **GraphRAG online build**: her startup'ta scroll + extract — 30s ek
  startup latency. Offline build tercih.

## İlgili
- [retrieval/raptor.py](../../adalet-agent/backend/retrieval/raptor.py)
- [retrieval/raptor_runtime.py](../../adalet-agent/backend/retrieval/raptor_runtime.py)
- [retrieval/graph_rag.py](../../adalet-agent/backend/retrieval/graph_rag.py)
- [agents/nodes/emsal.py](../../adalet-agent/backend/agents/nodes/emsal.py)
- eval/runs/W3_changes.md
