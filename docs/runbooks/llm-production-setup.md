# Production LLM Setup — Qwen3.5-9B-UD-Q4_K_XL on RTX 4070 12GB

> **Güncel durum (2026-06-21):** Üretim model string'i
> `Qwen3.5-9B-UD-Q4_K_XL.gguf` olarak tekilleştirildi. `docker-compose.yml`,
> `.env.example`, `backend/.env.example`, README ve bu runbook aynı dosya adını
> kullanır. 2026-05 tarihli Qwen 2.5 14B karşılaştırması aşağıda yalnız tarihsel
> karar bağlamı olarak kalır.

> Tarih: 2026-06-21
> Hedef: Mock LLM → gerçek model geçişi (ADALET-AGENT prod).
> Donanım: Bulut yol GPU gerektirmez; lokal yol RTX 4070 12GB VRAM.

## İki Yol: Bulut (önerilen) vs Lokal

v2.3 (CLAUDE.md) ile "en iyi teknoloji serbest" → ana LLM **OpenAI bulut** olabilir.
Embedding/retrieval/rerank her iki yolda da **lokal** kalır (sadece cevabı yazan model değişir).

| | Bulut (OpenAI) | Lokal (Qwen GGUF) |
|---|---|---|
| Kurulum | `LLM_MODE=openai` + `OPENAI_API_KEY` | model indir + llama-server (GPU) |
| Donanım | GPU YOK (ucuz CPU VPS) | RTX 4070+ / 12GB VRAM |
| Kalite (TR hukuk) | gpt-4o-mini > 9B-Q4 | iyi ama daha zayıf |
| Maliyet | token başına (~kuruş/soru) | $0 API (elektrik/GPU) |
| Gizlilik | soru OpenAI'a gider (PII maskelenir) | tam-lokal |

### Bulut Yol (önerilen — en az operasyon)

```bash
# backend/.env (veya container env):
LLM_MODE=openai
OPENAI_API_KEY=sk-proj-...           # SECRET — .env (gitignore) / secret manager
OPENAI_LLM_MODEL=gpt-4o-mini         # max kalite: gpt-4o
```

Docker stack (GPU YOK, llama-server başlamaz):
```bash
# docker-compose backend env'i OPENAI_API_KEY/OPENAI_LLM_MODEL'i .env'den geçirir.
# llama-server artık 'local-llm' profilinde → bulut moddayken başlamaz.
docker compose --profile production up -d
```
> ⚠️ `OPENAI_API_KEY` container'a geçmezse `get_llm()` **sessizce MockLLM'e** düşer
> (stub cevap). `docker compose config` ile env'in backend'e geçtiğini doğrula.

Aşağıdaki bölümler **lokal Qwen** yolu içindir (opt-in).

## Güncel Karar: Qwen3.5-9B UD-Q4_K_XL (Lokal Yol)

| Kriter | Güncel değer |
|---|---|
| Model dosyası | `Qwen3.5-9B-UD-Q4_K_XL.gguf` |
| Beklenen dosya konumu | `backend/models/Qwen3.5-9B-UD-Q4_K_XL.gguf` |
| Compose env | `LLAMA_MODEL_FILE=Qwen3.5-9B-UD-Q4_K_XL.gguf` |
| Backend in-process env | `LLM_MODEL_PATH=./models/Qwen3.5-9B-UD-Q4_K_XL.gguf` |
| Neden | 12GB GPU'ya daha rahat sığar; head-to-head yerel değerlendirmede daha az uydurma/sahte-grounding verdi |

## Tarihsel Not: Qwen 2.5 14B Q5_K_M (NOT 32B-Q3)

| Kriter | 14B Q5_K_M | 32B Q3_K_M | 32B Q4_K_M |
|---|---|---|---|
| Disk | ~10.5 GB | ~16 GB | ~20 GB |
| VRAM (8K ctx) | ~11.5 GB ✅ | ~13 GB ❌ | ~22 GB ❌ |
| Throughput | 30-50 tok/s | 6-10 tok/s | 3-8 tok/s |
| Perplexity loss | ~1% | 8-12% | ~4% |
| Hukuk doğruluğu | Yüksek | Orta-Düşük | Yüksek |
| RTX 4070 fit | Tam GPU | Partial offload | Çoğunlukla CPU |

**Neden 14B-Q5 > 32B-Q3:**
- 14B-Q5 tamamen VRAM'a sığar → 5-10x daha hızlı
- Q5 perplexity loss ~%1, Q3 %8-12 → sayı/madde halüsinasyonu kritik düşüş
- ADALET'in Verifier ajanı zaten halüsinasyonu yakalar → 14B-Q5 ile çift güvence

32B üst hedef olursa: RTX 3090 24GB ikinci el (~700€) veya cloud A100 spot.

## Kurulum

### 1. Model İndirme

```powershell
# Proje sahibinin doğruladığı GGUF dosyasını backend/models altına koy.
# Dosya adı compose/env ile birebir aynı olmalıdır:
Test-Path .\backend\models\Qwen3.5-9B-UD-Q4_K_XL.gguf
```

Eksikse model dosyasını indirdikten/aldıktan sonra şu yola yerleştir:
`backend/models/Qwen3.5-9B-UD-Q4_K_XL.gguf`.

### 2. llama-server (Windows)

`llama.cpp` Windows binary indir → https://github.com/ggerganov/llama.cpp/releases (CUDA build).

```powershell
.\llama-server.exe `
  -m .\models\Qwen3.5-9B-UD-Q4_K_XL.gguf `
  --n-gpu-layers 99 `
  --ctx-size 8192 `
  --batch-size 512 `
  --ubatch-size 512 `
  --flash-attn `
  -ctk q8_0 -ctv q8_0 `
  --parallel 2 `
  --host 0.0.0.0 --port 8080 `
  --mlock
```

Flag açıklamaları:
- `-ngl 99` — tüm layer'lar GPU'da (Q5 14B tamamen sığar)
- `--flash-attn` — 8K context'te ~1.2GB VRAM tasarrufu (Ada Lovelace optimize)
- `-ctk/-ctv q8_0` — KV cache 8-bit, %0 kalite kaybı, VRAM yarıya iner
- `--parallel 2` — ADALET'in 7 ajan paralel çağrılarına slot
- `--batch-size 512` — RTX 4070 CUDA cores doyurur
- `--lookup-ngram-min 2` — yalnız destekleyen yeni llama.cpp build'lerinde opsiyonel;
  mevcut Windows binary bu bayrağı reddediyorsa kullanma.

### 3. Backend .env Aktifleştirme

```bash
# adalet-agent/backend/.env
LLM_MODE=llamacpp_server
LLM_SERVER_URL=http://127.0.0.1:8080
LLM_MODEL_PATH=./models/Qwen3.5-9B-UD-Q4_K_XL.gguf
```

### 4. Smoke Test

```powershell
# llama-server hala çalışıyor olmalı, ayrı terminal:
cd adalet-agent\backend
$env:LLM_MODE="llamacpp_server"
uv run python -m scripts.smoke_qwen
```

Beklenen: 5-10 saniyede Türkçe cevap döner.

### 5. E2E Benchmark Run

```powershell
$env:LLM_MODE="llamacpp_server"
$env:HYDE_ENABLED="0"
$env:MULTI_QUERY_ENABLED="0"
$env:ELIGIBILITY_ENABLED="0"
$env:DEBATE_LLM_ON_RETRY="0"
$env:COLBERT_QUERY_ENABLED="1"
$env:RAPTOR_ENABLED="1"
$env:GRAPH_RAG_ENABLED="1"
uv run python -m eval.freeze_baseline --modes hybrid,rerank,hyde,multi_query
```

Beklenen sonuç: 50 vaka × 4 mode → ~30 dakika. p95 < 30s, faithfulness ≥ 0.80.

## Troubleshooting

| Problem | Çözüm |
|---|---|
| OOM (VRAM dolu) | `--n-gpu-layers 60` yap (kısmi offload, hız düşer ama çalışır) |
| Yavaş (< 10 tok/s) | `--flash-attn` flag eksik veya CUDA build değil — release binary doğru mu? |
| 8K context yetmiyor | `--ctx-size 16384`, ama VRAM 13GB'a çıkar — riskli |
| Encoding hatası (cp1254) | `chcp 65001 && set PYTHONUTF8=1` |
| LLM çıktısında halüsinasyon | Verifier zaten yakalar — `NLI_CONTRADICTION_THRESHOLD=0.65` daha sıkı yapılabilir |

## Sprint-6 İçin Alternatif (32B Hedefliyorsan)

```yaml
# A: Donanım yükseltme
gpu: RTX 3090 24GB ikinci el (~700€)
model: Qwen2.5-32B-Q4_K_M (20GB disk, ~22GB VRAM)
beklenen_throughput: 25-40 tok/s

# B: Cloud spot
provider: RunPod A100 80GB spot ($1.50/saat)
model: Qwen2.5-32B-Q5_K_M (full quality)
maliyet: Beta launch'a kadar ~$200
```

## Maliyet Tahmini (Lokal vs Cloud)

| Senaryo | 1 Ay Maliyet |
|---|---|
| Lokal 14B-Q5 (RTX 4070 var) | ~50€ elektrik |
| Cloud A100 spot (7gün/hafta) | ~$1000 |
| Cloud A100 sadece prod (8h/gün) | ~$360 |

Bitirme tezi ve beta launch için **Lokal 14B-Q5** kazanır.
