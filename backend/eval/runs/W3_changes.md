# Sprint-4 Hafta 3 — RAPTOR + GraphRAG Changelog

Önceki: `eval/runs/W2_changes.md`

## Hedef
RAPTOR offline build + lifespan preload; GraphRAG citation extraction + emsal_node traversal entegrasyonu.

## Değişiklikler

### W3.1 — RAPTOR offline build + persistence
- `retrieval/raptor.py`:
  - `RaptorIndex.save(path)` — pickle, **dict-based** (class identity safe)
  - `RaptorIndex.load(path)` classmethod — v1/v2 dual format
  - `build()` → `force_enabled: bool` parametresi (test order bağımlılığı çözümü)
- Yeni `scripts/build_raptor.py`:
  - Qdrant scroll API ile chunk fetch
  - source filter: `case` | `law` | `all`
  - `--max-chunks` VRAM kontrolü
  - `--out` pickle path

### W3.2 — RAPTOR lifespan preload + runtime singleton
- Yeni `retrieval/raptor_runtime.py`:
  - `get_raptor_index()` process-singleton
  - `RAPTOR_ENABLED=0` → None (no-op)
  - Pickle yok → boş index
  - Pickle bozuk → graceful fallback
- `main.py` lifespan'a preload eklendi
- Tests: 8/8 (`test_raptor_persistence.py`)

### W3.3 — GraphRAG citation + build script (zaten mevcut)
- `retrieval/graph_rag.py` zaten W3 öncesi olgun:
  - `LegalGraph` + NetworkX MultiDiGraph
  - 3 node tipi (law/case/concept), 4 edge tipi
  - `expand()` BFS k-hop
  - JSON save/load (singleton lazy)
  - `extract_seed_ids()` "TKHK m.11", "Yargıtay 2019/1234" regex
- `scripts/build_graph.py` zaten Qdrant scroll → graph build implementasyonu mevcut

### W3.4 — emsal_node graph traversal entegrasyonu
- `agents/nodes/emsal.py`:
  - `GRAPH_RAG_ENABLED=1` + dolu graph → emsal citation title'larından
    `extract_seed_ids()` → 2-hop expand → top-3 neighbor node id
  - State'e yeni alan: `emsal_graph_neighbors: list[str]`
  - Bayrak kapalıysa eski davranış birebir
- `agents/state.py`:
  - `emsal_graph_neighbors: NotRequired[list[str]]` eklendi
- `GRAPH_NEIGHBORS_TOP_K` env-toggle (default 3)
- Tests: 3/3 (`test_emsal_graph.py`)

### W3.5 — Integration tests
- `tests/retrieval/test_raptor_persistence.py` — 8 test
  - save/load roundtrip
  - missing file FileNotFoundError
  - parent dir auto-create
  - runtime singleton (load, empty, disabled, cached)
- `tests/agents/test_emsal_graph.py` — 3 test
  - graph_neighbors populated when enabled
  - no graph when disabled
  - unknown domain early-exit

## Test Skoru
- **W2 sonu:** 225 / 225
- **W3 sonu:** **236 / 236 yeşil** (+11 yeni)
- Regression: 0

## Bonus: Test order bug yakalandı
- `tests/retrieval/test_raptor.py` `os.environ["RAPTOR_ENABLED"]="1"` import sonrası
  modül-level `RAPTOR_ENABLED` constant'ını değiştiremezdi (cache). Diğer
  test'ler önce import ederse bu test fail oluyordu.
- Fix: `build(force_enabled=True)` parametresi + runtime `os.getenv()` kontrol.
- Aynı PicklingError class-identity bağımlılığı dict-based serialize ile çözüldü.

## Kullanıcı Tarafından Çalıştırılması Gerekenler

### Graph + RAPTOR offline build (Qdrant + llama-server hazır)
```bash
# Graph build (hızlı, LLM gerek değil)
GRAPH_RAG_ENABLED=1 uv run python -m scripts.build_graph
# Çıktı: data/graph/legal_graph.json

# RAPTOR tree build (LLM gerek — pahalı, bir kez)
RAPTOR_ENABLED=1 LLM_MODE=llamacpp_server \
  uv run python -m scripts.build_raptor --max-chunks 800 --source case
# Çıktı: data/raptor/tree.pkl
```

### Runtime (production)
```bash
GRAPH_RAG_ENABLED=1 RAPTOR_ENABLED=1 \
  HYDE_ENABLED=1 MULTI_QUERY_ENABLED=1 COLBERT_QUERY_ENABLED=1 \
  MEVZUAT_DOMAIN_FILTER=1 \
  LLM_MODE=llamacpp_server PYTHONUTF8=1 \
  uv run uvicorn main:app --host 127.0.0.1 --port 8000
```
