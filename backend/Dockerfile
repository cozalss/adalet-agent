# syntax=docker/dockerfile:1.6
# ============================================================================
#  ADALET-AGENT backend — multi-stage production image
#
#  Hedef: ~500MB tasarruf (build araçları runtime'a sızmıyor),
#         non-root user, HEALTHCHECK, .dockerignore ile temiz bağlam.
#
#  NOT: ML modelleri (BGE-M3, reranker, NLI) ilk run'da indirilir; production
#  deploy'da volume-mount edilmiş `/models` ve `HF_HOME=/models` önerilir.
# ============================================================================

# ----------------------------- BUILD stage ----------------------------------
FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/root/.cache/uv

# Build için gerekli araçlar (sadece bu stage'de kalır)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

# Bağımlılık katmanı — pyproject + uv.lock değişmezse cache hit
COPY pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Asıl kaynak kodu — bu katman daha sık değişir
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# ---------------------------- RUNTIME stage ---------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUTF8=1 \
    PYTHONIOENCODING=utf-8 \
    PATH="/app/.venv/bin:$PATH" \
    HF_HUB_OFFLINE=0 \
    HF_HOME=/models

# Runtime deps:
#  - curl: HEALTHCHECK
#  - libgomp1: torch (OpenMP)
#  - tesseract-ocr + -tur: OCR (pytesseract binary + Türkçe dil verisi ŞART;
#    backend/models/tessdata .dockerignore'da → apt paketi gerekir)
#  - ffmpeg: STT (faster-whisper mp3/m4a/ogg/webm decode güvencesi)
# NOT: STT/TTS uçtan-uca (Piper espeak-ng-data wheel'de bundle) CONTAINER
# SMOKE ile doğrulanmalı — henüz koşulmadı.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libgomp1 \
        tesseract-ocr \
        tesseract-ocr-tur \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /models \
    && chown -R app:app /models

# Güvenlik (#38 Trivy): base image'ın SİSTEM Python paketleme araçlarını yamalıya yükselt.
# Uygulama /app/.venv'den koşar (venv'de setuptools 81 → jaraco.context 6.1.0 + wheel 0.46.3
# ZATEN yamalı). Ama python:3.11-slim sistem site-packages'ında ESKİ setuptools (vendored
# jaraco.context 5.3.0) + wheel 0.45.1 var → Trivy bunları fixable-HIGH sayıp CI'ı kırıyor.
#   CVE-2026-23949 (jaraco.context: malicious tar path traversal) → fix 6.1.0
#   CVE-2026-24049 (wheel: malicious wheel ile kod yürütme/yetki yükseltme) → fix 0.46.2
RUN pip install --no-cache-dir --upgrade \
        "pip" "setuptools>=81.0.0" "wheel>=0.46.2" "jaraco.context>=6.1.0"

WORKDIR /app

# Build stage'den .venv + uygulama kodunu kopyala (owner: app)
COPY --from=builder --chown=app:app /app /app

USER app

EXPOSE 8000

# Liveness probe — 30s arayla, ilk model yüklemesi için 60s grace
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl --fail --silent --output /dev/null http://127.0.0.1:8000/health || exit 1

# Production default: low-latency profile; deep retrieval compose/env ile açılır.
# Sprint-5 W16: SCHEDULER_ENABLED=1 default (APScheduler RG + Yargıtay cron).
# Test/CI'da SCHEDULER_ENABLED=0 ile devre dışı bırakılabilir.
ENV HYDE_ENABLED=0 \
    MULTI_QUERY_ENABLED=0 \
    ELIGIBILITY_ENABLED=0 \
    DEBATE_LLM_ON_RETRY=0 \
    LLM_MODE=mock \
    SCHEDULER_ENABLED=1 \
    SCHEDULER_TIMEZONE=Europe/Istanbul

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
