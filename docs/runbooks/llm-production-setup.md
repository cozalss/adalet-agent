# Production LLM Setup — Qwen 14B-Q5_K_M on RTX 4070 12GB

> Tarih: 2026-05-26
> Hedef: Mock LLM → Gerçek model geçişi (ADALET-AGENT prod).
> Donanım: RTX 4070 12GB VRAM.

## Karar: Qwen 2.5 14B Q5_K_M (NOT 32B-Q3)

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
# huggingface-cli ile
huggingface-cli download bartowski/Qwen2.5-14B-Instruct-GGUF `
  Qwen2.5-14B-Instruct-Q5_K_M.gguf `
  --local-dir .\models --local-dir-use-symlinks False
```

Alternatif: tarayıcıdan https://huggingface.co/bartowski/Qwen2.5-14B-Instruct-GGUF

### 2. llama-server (Windows)

`llama.cpp` Windows binary indir → https://github.com/ggerganov/llama.cpp/releases (CUDA build).

```powershell
.\llama-server.exe `
  -m .\models\Qwen2.5-14B-Instruct-Q5_K_M.gguf `
  --n-gpu-layers 99 `
  --ctx-size 8192 `
  --batch-size 512 `
  --ubatch-size 512 `
  --flash-attn `
  -ctk q8_0 -ctv q8_0 `
  --parallel 2 `
  --lookup-ngram-min 2 `
  --host 0.0.0.0 --port 8080 `
  --mlock
```

Flag açıklamaları:
- `-ngl 99` — tüm layer'lar GPU'da (Q5 14B tamamen sığar)
- `--flash-attn` — 8K context'te ~1.2GB VRAM tasarrufu (Ada Lovelace optimize)
- `-ctk/-ctv q8_0` — KV cache 8-bit, %0 kalite kaybı, VRAM yarıya iner
- `--parallel 2` — ADALET'in 7 ajan paralel çağrılarına slot
- `--batch-size 512` — RTX 4070 CUDA cores doyurur

### 3. Backend .env Aktifleştirme

```bash
# adalet-agent/backend/.env
LLM_MODE=llamacpp_server
LLM_SERVER_URL=http://127.0.0.1:8080
LLM_MODEL_PATH=./models/Qwen2.5-14B-Instruct-Q5_K_M.gguf
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
