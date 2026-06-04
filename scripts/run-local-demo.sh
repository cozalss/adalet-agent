#!/usr/bin/env bash
# =============================================================================
# ADALET — Tek-GPU Lokal Demo Başlatıcı
# =============================================================================
# 2026-06-03'te RTX 4070 12GB'da DOĞRULANDI (gerçek Qwen cevabı + tahmin + 16 kaynak).
#
# Strateji (bkz. docs/runbooks/lokal-tek-gpu-demo.md):
#   - Qwen 14B Q5_K_M GPU'da (~11GB), yardımcı modeller (embedding/reranker) CPU'da.
#   - LLM_SPECULATIVE=0  → KRİTİK: in-process llamacpp'te prompt-lookup speculative
#     decoding UZUN prompt'ta (retrieval 16 kaynak) logits broadcast çökmesi yapar
#     ("could not broadcast input array ..."). 0 = kapalı = draft çalışır.
#   - python -m uvicorn → Windows "Uygulama Denetimi" uvicorn.exe console script'ini
#     engeller (os error 4551); modül olarak çalıştırınca sorun yok.
#   - node vite.js   → aynı sebeple pnpm/vite.cmd yerine doğrudan node.
#   - SPARSE/RAPTOR/GRAPH kapalı → VRAM tasarrufu (Qwen'e yer aç).
#   - PREDICTIVE_ENABLED=1 + DEVICE=cpu → tahmin paneli açık, GPU yemez.
#   - AUTH_ENABLED=0 + ENV=development → token'sız soru-sorma (ENV=production olsaydı
#     AUTH=0 ile fail-fast çökerdi). NOT: /me geçmiş uçları 401 döner (beklenen).
#
# Ön-koşul: docker'da qdrant (adalet_mursit_hybrid dolu) + redis UP; backend/.venv;
#           frontend/node_modules; backend/models/Qwen2.5-14B-Instruct-Q5_K_M.gguf.
# Kullanım (Git Bash):  bash scripts/run-local-demo.sh
# Durdur:               bash scripts/run-local-demo.sh stop
# =============================================================================

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN="$ROOT/.run"
mkdir -p "$RUN"

stop_demo() {
  for svc in backend-demo frontend-demo; do
    if [ -f "$RUN/$svc.pid" ]; then
      pid="$(cat "$RUN/$svc.pid")"
      echo "[demo] $svc durduruluyor (PID $pid)"
      taskkill //F //PID "$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
      rm -f "$RUN/$svc.pid"
    fi
  done
  # Port'ta kalan dinleyiciyi de temizle (PID dosyası eskiyse)
  for port in 8000 5173; do
    lp="$(netstat -ano 2>/dev/null | grep ":$port" | grep LISTENING | awk '{print $5}' | head -1)"
    [ -n "$lp" ] && taskkill //F //PID "$lp" 2>/dev/null || true
  done
  echo "[demo] durduruldu."
}

if [ "$1" = "stop" ]; then stop_demo; exit 0; fi

# --- Backend (FastAPI + in-process Qwen) -------------------------------------
cd "$ROOT/backend"
set -a; source .env 2>/dev/null; set +a   # kullanıcı .env tabanı (collection, model yolu, ...)
# --- demo override'ları (.env üstüne; Plan A: Qwen GPU / gerisi CPU-kapalı) ---
export LLM_MODE=llamacpp LLM_N_GPU_LAYERS=-1 LLM_N_BATCH=512 LLM_SPECULATIVE=0
# HIZ: HyDE/Multi-Query in-process Qwen çağrıları tek-executor'da serialize → retrieval
# ~53s; kapat → ~5s (ablation: trafik/vergi'de zaten zarar veriyorlardı). DRAFT 768→512.
export HYDE_ENABLED=0 MULTI_QUERY_ENABLED=0 DRAFT_MAX_TOKENS=512
export SPARSE_EMBEDDER_MODEL=
export RAPTOR_ENABLED=0 GRAPH_RAG_ENABLED=0 COLBERT_QUERY_ENABLED=0
export EMBEDDING_DEVICE=cpu EMBEDDING_FP16=0 RERANKER_DEVICE=cpu RERANKER_FP16=0
export PREDICTIVE_ENABLED=1 PREDICTIVE_USE_MODEL=1 PREDICTIVE_DEVICE=cpu
# Verify sertleştirme — E2E ölçülmüş-güvenli (2026-06-04, over-reject yok): yüksek-riskli
# uygunluk iddialarında + cited iddialarda POZİTİF NLI grounding şart (çıkarım/misgrounded
# halüsinasyon kapısı). Yalnız NLI yüklüyken anlamlı; bu demo NLI yüklü.
export CLATTER_GATE_ENABLED=1 CITE_GROUNDING_CHECK=1
export AUTH_ENABLED=0 ENV=development PRELOAD_MODELS=1
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8

echo "[demo] backend → :8000 (log: .run/backend-demo.out.log)  LLM_MODE=$LLM_MODE SPECULATIVE=$LLM_SPECULATIVE"
nohup uv run python -m uvicorn main:app --host 127.0.0.1 --port 8000 > "$RUN/backend-demo.out.log" 2>&1 &
echo $! > "$RUN/backend-demo.pid"

# --- Frontend (Vite dev) -----------------------------------------------------
cd "$ROOT/frontend"
echo "[demo] frontend → :5173 (log: .run/frontend-demo.out.log)"
nohup node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 > "$RUN/frontend-demo.out.log" 2>&1 &
echo $! > "$RUN/frontend-demo.pid"

echo ""
echo "[demo] Başlatıldı. Backend ilk health ~30-60s (PRELOAD), ilk soru ~80s (Qwen yüklenir)."
echo "[demo]   Backend health : curl http://127.0.0.1:8000/health"
echo "[demo]   Tarayıcı       : http://localhost:5173  (kayıt/giriş → olgu-zengin soru)"
echo "[demo]   Durdur         : bash scripts/run-local-demo.sh stop"
