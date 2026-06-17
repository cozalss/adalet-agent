#!/usr/bin/env bash
# ADALET — KARARLI tek-GPU demo: Qwen (llama-cpp) GPU'da, TÜM torch (embedder/reranker/
# NLI/predictive) CPU'da. Gerekçe: aynı process'te torch-CUDA + llama-cpp-CUDA paylaşımı
# "illegal memory access"/"invalid argument" ile çöküyordu (yoğun churn sonrası). Torch'u
# CPU'ya alınca çatışma biter → kararlı (retrieval ~30-40s, üretim Qwen GPU'da hızlı).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN="$ROOT/.run"; mkdir -p "$RUN"
cd "$ROOT/backend"
set -a; source .env 2>/dev/null; set +a
export LLM_MODE=llamacpp LLM_N_GPU_LAYERS=-1 LLM_N_BATCH=1024 LLM_SPECULATIVE=0
export LLM_MODEL_PATH=./models/Qwen3.5-9B-UD-Q4_K_XL.gguf
export LLM_NO_THINK=1
export HYDE_ENABLED=0 MULTI_QUERY_ENABLED=0 DRAFT_MAX_TOKENS=896 DRAFT_MIN_TOKENS=384
export SPARSE_EMBEDDER_MODEL=
export RAPTOR_ENABLED=0 GRAPH_RAG_ENABLED=0 COLBERT_QUERY_ENABLED=0
# TÜM torch CPU'da (CUDA çatışması yok)
export EMBEDDING_DEVICE=cpu EMBEDDING_FP16=0 RERANKER_DEVICE=cpu RERANKER_FP16=0
export RERANKER_MODEL=BAAI/bge-reranker-v2-m3
export RERANK_PROVIDER=bgem3 COLBERT_RERANK_DEVICE=cpu COLBERT_RERANK_WEIGHTS=0.4,0.2,0.4
export COLBERT_FUSE_HYBRID=1 COLBERT_FUSE_WEIGHT=0.6
export PREDICTIVE_ENABLED=1 PREDICTIVE_USE_MODEL=1 PREDICTIVE_DEVICE=cpu
export NLI_DEVICE=cpu
export CLATTER_GATE_ENABLED=1 CITE_GROUNDING_CHECK=1 GUIDED_CITE_ENABLED=1
export EMSAL_LIVE_FALLBACK_ENABLED=1 PARTIAL_ANSWER_NOTE=1 CONV_DECONTEXT_ENABLED=1
export AUTH_ENABLED=0 ENV=development PRELOAD_MODELS=1
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
echo "[stable] backend → :8000  (Qwen GPU, tüm torch CPU)"
nohup uv run python -m uvicorn main:app --host 127.0.0.1 --port 8000 > "$RUN/stable-backend.out.log" 2>&1 &
echo $! > "$RUN/backend-demo.pid"
cd "$ROOT/frontend"
nohup node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 > "$RUN/frontend-demo.out.log" 2>&1 &
echo $! > "$RUN/frontend-demo.pid"
echo "[stable] başlatıldı."
