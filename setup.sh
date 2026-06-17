#!/usr/bin/env bash
# ADALET-AGENT — tek-komut geliştirme kurulumu (arkadaş/yeni-geliştirici için).
# Kullanım:  git clone ... && cd adalet-agent && bash setup.sh
#
# Otomatik yapar: önkoşul kontrolü → Docker dev servisleri (Qdrant+Redis) →
# backend bağımlılıkları (uv) → frontend bağımlılıkları (pnpm) → .env dosyaları.
# YAPMAZ (manuel — büyük/lisanslı): korpus verisi + GPU model indirme (aşağıda anlatılır).
set -euo pipefail
cd "$(dirname "$0")"

ok(){ printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn(){ printf '  \033[33m⚠\033[0m %s\n' "$1"; }
die(){ printf '  \033[31m✖ %s\033[0m\n' "$1"; exit 1; }

echo "▶ 1/5  Önkoşul kontrolü"
command -v docker >/dev/null || die "Docker gerekli — https://docker.com"
docker info >/dev/null 2>&1 || die "Docker daemon kapalı — Docker Desktop'ı aç"
command -v uv >/dev/null || die "uv gerekli — https://docs.astral.sh/uv/ (pip install uv)"
HAVE_PNPM=1; command -v pnpm >/dev/null || { HAVE_PNPM=0; warn "pnpm yok (frontend için): npm i -g pnpm"; }
ok "docker + uv hazır"

echo "▶ 2/5  Dev servisleri (Qdrant + Redis)"
docker compose -f docker-compose.dev.yml up -d
ok "Qdrant :6333 · Redis :6379 ayakta"

echo "▶ 3/5  Backend bağımlılıkları (uv sync)"
( cd backend && uv sync --extra dev >/dev/null ) && ok "backend deps kuruldu"

echo "▶ 4/5  .env dosyaları"
[ -f backend/.env ]  || cp backend/.env.example  backend/.env  2>/dev/null && ok "backend/.env hazır"
[ -f frontend/.env ] || cp frontend/.env.example frontend/.env 2>/dev/null || true

echo "▶ 5/5  Frontend bağımlılıkları"
if [ "$HAVE_PNPM" = 1 ]; then ( cd frontend && pnpm install --silent ) && ok "frontend deps kuruldu"; else warn "pnpm yok → frontend atlandı"; fi

cat <<'EOF'

────────────────────────────────────────────────────────────────────
✅ KURULUM TAMAM. Sırada (manuel) 2 adım var:

1) KORPUS  ⚠️ ZORUNLU — boş Qdrant'ta her cevap "doğrulayamadım" diye REDDEDİLİR.
   • HIZLI (önerilen): proje sahibinden Qdrant snapshot dosyasını al, içe aktar:
       docker cp adalet_mursit_hybrid.snapshot adalet-qdrant:/qdrant/snapshots/
       curl -X PUT "http://localhost:6333/collections/adalet_mursit_hybrid/snapshots/recover" \
         -H 'Content-Type: application/json' \
         -d '{"location":"file:///qdrant/snapshots/adalet_mursit_hybrid.snapshot"}'
   • YA DA sıfırdan seed et (yavaş, ~saatler, internet + HF gerekir):
       cd backend
       uv run python -m scripts.seed_mevzuat
       uv run python -m scripts.seed_hf_yargitay --shards 0 --cap-per-domain 500

2) ÇALIŞTIR
   • Backend (mock LLM — GPU GEREKMEZ, denemek için ideal):
       cd backend && LLM_MODE=mock uv run uvicorn main:app --reload --port 8000
   • Frontend:
       cd frontend && pnpm dev          →  http://localhost:5173
   • Testler:  cd backend && uv run --extra dev pytest tests/ -q

GERÇEK LLM (GPU, lokal Qwen): docs/runbooks/llm-production-setup.md
────────────────────────────────────────────────────────────────────
EOF
