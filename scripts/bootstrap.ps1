# ============================================================================
#  ADALET-AGENT — bootstrap (Windows PowerShell)
#
#  Sıfırdan klon → MockLLM mode'da dev çalıştırma.
#  Tahmini süre: 5-10 dk (Python+uv kuruluysa); 15-20 dk (sıfırdan).
#
#  Çalıştır (repo root'unda):
#    .\scripts\bootstrap.ps1
#
#  Atlatma opsiyonu:
#    .\scripts\bootstrap.ps1 -SkipModels   # 11 GB model indirimini atla
#    .\scripts\bootstrap.ps1 -SkipDocker   # Docker servisleri başlatmayı atla
# ============================================================================

[CmdletBinding()]
param(
    [switch]$SkipModels,
    [switch]$SkipDocker
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $RepoRoot

function Write-Step {
    param([string]$Message)
    Write-Host "`n>>> $Message" -ForegroundColor Cyan
}

function Test-Command {
    param([string]$Name)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    return ($null -ne $cmd)
}

# -----------------------------------------------------------------------------
# 1. Ön kontroller
# -----------------------------------------------------------------------------
Write-Step "Ön kontrol: Python 3.11+, uv, Docker"

if (-not (Test-Command "python")) {
    Write-Host "HATA: Python yok. https://www.python.org/downloads/ → 3.11+ indir." -ForegroundColor Red
    exit 1
}

$pyVer = (python --version 2>&1).ToString()
Write-Host "  Python: $pyVer"

if (-not (Test-Command "uv")) {
    Write-Step "uv kurulumu (pip ile)"
    python -m pip install --user uv
    if (-not (Test-Command "uv")) {
        Write-Host "HATA: uv kurulumu başarısız." -ForegroundColor Red
        exit 1
    }
}
Write-Host "  uv: $(uv --version)"

if (-not $SkipDocker -and -not (Test-Command "docker")) {
    Write-Host "UYARI: Docker yok. -SkipDocker ile devam et veya Docker Desktop kur." -ForegroundColor Yellow
}

# -----------------------------------------------------------------------------
# 2. .env oluştur
# -----------------------------------------------------------------------------
Write-Step ".env dosyası kontrolü"
$envPath = "backend\.env"
if (-not (Test-Path $envPath)) {
    Copy-Item "backend\.env.example" $envPath
    Write-Host "  Yeni .env oluşturuldu (LLM_MODE=mock dev default)"
    # Dev mode: mock LLM + local Qdrant/Redis (auth disable)
    $content = Get-Content $envPath -Raw
    $content = $content -replace "LLM_MODE=.*", "LLM_MODE=mock"
    $content += @"


# ============================================================================
# Dev override (bootstrap.ps1 tarafından eklendi)
# ============================================================================
AUTH_ENABLED=0
SANITIZE_ENABLED=1
PII_ENABLED=1
QDRANT_URL=http://127.0.0.1:6333
REDIS_URL=redis://127.0.0.1:6379/0
"@
    Set-Content -Path $envPath -Value $content -Encoding utf8
} else {
    Write-Host "  .env mevcut, atlanıyor"
}

# -----------------------------------------------------------------------------
# 3. Python bağımlılıkları
# -----------------------------------------------------------------------------
Write-Step "Python bağımlılıkları (uv sync, ~3 dk ilk seferinde)"
Set-Location "$RepoRoot\backend"
uv sync
if ($LASTEXITCODE -ne 0) {
    Write-Host "HATA: uv sync başarısız." -ForegroundColor Red
    exit 1
}
Set-Location $RepoRoot

# -----------------------------------------------------------------------------
# 4. Docker servisleri (Qdrant + Redis)
# -----------------------------------------------------------------------------
if (-not $SkipDocker) {
    if (Test-Command "docker") {
        Write-Step "Docker servisleri (Qdrant + Redis)"
        docker compose -f docker-compose.dev.yml up -d
        Start-Sleep -Seconds 5
        docker compose -f docker-compose.dev.yml ps
    } else {
        Write-Host "  Docker yok, atlanıyor (manuel başlat veya -SkipDocker)" -ForegroundColor Yellow
    }
}

# -----------------------------------------------------------------------------
# 5. Models (opsiyonel — 11 GB)
# -----------------------------------------------------------------------------
if (-not $SkipModels) {
    Write-Step "Modeller (Piper TR 61MB + Whisper-small 462MB + tessdata 18MB)"
    Write-Host "  Qwen 14B GGUF (9.8 GB) için ayrıca docs/runbooks/llm-production-setup.md oku" -ForegroundColor Yellow

    if (-not (Test-Command "hf")) {
        Write-Host "  hf CLI kurulumu (huggingface_hub)"
        Set-Location "$RepoRoot\backend"
        uv pip install huggingface_hub
        Set-Location $RepoRoot
    }

    $modelsDir = "$RepoRoot\backend\models"
    New-Item -ItemType Directory -Force -Path "$modelsDir\piper", "$modelsDir\whisper", "$modelsDir\tessdata" | Out-Null

    if (-not (Test-Path "$modelsDir\piper\tr\tr_TR\dfki\medium\tr_TR-dfki-medium.onnx")) {
        Write-Host "  Piper TR DFKI voice indiriliyor (61 MB)..."
        Set-Location "$modelsDir"
        hf download rhasspy/piper-voices `
            tr/tr_TR/dfki/medium/tr_TR-dfki-medium.onnx `
            tr/tr_TR/dfki/medium/tr_TR-dfki-medium.onnx.json `
            --local-dir piper
        Set-Location $RepoRoot
    } else {
        Write-Host "  Piper voice mevcut, atlanıyor"
    }

    if (-not (Test-Path "$modelsDir\whisper\model.bin")) {
        Write-Host "  faster-whisper-small indiriliyor (462 MB)..."
        Set-Location "$modelsDir"
        hf download Systran/faster-whisper-small --local-dir whisper
        Set-Location $RepoRoot
    } else {
        Write-Host "  Whisper model mevcut, atlanıyor"
    }

    if (-not (Test-Path "$modelsDir\tessdata\tur.traineddata")) {
        Write-Host "  Tesseract tessdata (tur+eng) indiriliyor (~22 MB)..."
        $tessUrl = "https://github.com/tesseract-ocr/tessdata/raw/main"
        Invoke-WebRequest -Uri "$tessUrl/tur.traineddata" -OutFile "$modelsDir\tessdata\tur.traineddata"
        Invoke-WebRequest -Uri "$tessUrl/eng.traineddata" -OutFile "$modelsDir\tessdata\eng.traineddata"
        Invoke-WebRequest -Uri "$tessUrl/osd.traineddata" -OutFile "$modelsDir\tessdata\osd.traineddata"
    } else {
        Write-Host "  tessdata mevcut, atlanıyor"
    }

    # Tesseract binary kontrol
    if (-not (Test-Path "C:\Program Files\Tesseract-OCR\tesseract.exe")) {
        Write-Host "  UYARI: Tesseract binary yok. Kurmak için:" -ForegroundColor Yellow
        Write-Host "    winget install --id UB-Mannheim.TesseractOCR --accept-source-agreements" -ForegroundColor Yellow
    }
} else {
    Write-Host "  -SkipModels: modeller atlandı" -ForegroundColor Yellow
}

# -----------------------------------------------------------------------------
# 6. Smoke test
# -----------------------------------------------------------------------------
Write-Step "Smoke test (base, MockLLM mode)"
Set-Location "$RepoRoot\backend"
uv run pytest tests/ -m "not gpu and not llm_integration and not integration and not multimodal_integration" --no-cov -q --tb=no
Set-Location $RepoRoot

# -----------------------------------------------------------------------------
# Bitiş
# -----------------------------------------------------------------------------
Write-Host "`n=============================================================" -ForegroundColor Green
Write-Host " Bootstrap TAMAM. Çalıştırmak için:" -ForegroundColor Green
Write-Host "=============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "   cd backend"
Write-Host "   uv run uvicorn main:app --reload"
Write-Host ""
Write-Host " Sonra http://127.0.0.1:8000/docs (Swagger UI)"
Write-Host ""
Write-Host " Notlar:"
Write-Host "   - MockLLM mode'da gerçek LLM cevabı YOK; graph akışı test edilir"
Write-Host "   - Gerçek Qwen 14B için: docs/runbooks/llm-production-setup.md"
Write-Host "   - Qdrant seed (62k chunk) yok; retrieval boş döner"
Write-Host "   - Seed: cd backend && uv run python -m scripts.seed_mevzuat"
Write-Host ""
