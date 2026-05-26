# multimodal — OCR + STT + TTS

> **Durum (2026-05-26 — Sprint-6 real integration):**
> - **TTS**: ✅ Piper TR DFKI voice çalışıyor (61MB ONNX, 22050 Hz)
> - **STT**: ✅ faster-whisper-small çalışıyor (462MB, INT8 CPU)
> - **OCR**: ✅ Tesseract 5.4 + Turkish (winget install + project-local tessdata)

## Smoke Test Sonuçları

```
TTS  "Kıdem tazminatı..." → 222KB WAV (5s ses) @ 1.7s latency
STT  WAV → "Kıdam tazminatı..." @ 1.15s (warm) / 14s (cold)
TTS+STT round-trip → "tazminat" keyword preserved
OCR  "Madde 11 - Tüketici hakları çiğnenemez." → ÇĞİŞÜ karakter doğru
```

**5/5 `multimodal_integration` test passed** (8.8s). Çalıştırmak için:

```bash
cd backend
uv run pytest tests/multimodal/test_real_integration.py -v -m multimodal_integration
```

## Modüller

### `tts.py` — Piper (Default)

**Default**: Piper `tr_TR-dfki-medium` — 61 MB ONNX, CPU real-time 8x.

**Path**: `backend/models/piper/tr/tr_TR/dfki/medium/tr_TR-dfki-medium.onnx`

```python
from multimodal.tts import synthesize_speech

result = await synthesize_speech(
    "Kıdem tazminatı...",
    strip_disclaimer=True,  # "Bu cevap hukuki tavsiye değildir..." kesilir
)
# result.audio_bytes, result.sample_rate, result.duration_s, result.elapsed_ms
```

### `stt.py` — faster-whisper

**Default**: `Systran/faster-whisper-small` — 462 MB, INT8 CPU.

**Path**: `backend/models/whisper/` (HuggingFace download)

```python
from multimodal.stt import transcribe_audio

result = await transcribe_audio(audio_bytes, ext="wav")
# result.text, result.language, result.segments, result.duration_s
```

**Daha doğru model**: `STT_MODEL=large-v3` (3 GB, %15 daha doğru)
**GPU 5x hız**: `STT_DEVICE=cuda STT_COMPUTE_TYPE=float16`

### `ocr.py` — Tesseract 5 (+ Qwen2-VL Opsiyonel Fallback)

**Python paketi**: ✅ `pytesseract` kurulu
**Binary**: ✅ Tesseract 5.4 (winget install) — `C:\Program Files\Tesseract-OCR\`
**Türkçe lang**: ✅ `backend/models/tessdata/tur.traineddata` (proje-lokal, admin gerekmez)

#### Otomatik wire-up

`ocr.py` import edildiğinde:
1. `_LOCAL_TESSDATA = backend/models/tessdata/` varsa → `TESSDATA_PREFIX` env'i set edilir
2. Windows'ta `pytesseract.tesseract_cmd = C:\Program Files\Tesseract-OCR\tesseract.exe`

Yani kullanıcı/CI tarafında ekstra config gerekmez.

#### Tesseract Binary Kurulumu (Windows, ilk kurulum)

```powershell
# Yöntem A — winget (önerilen)
winget install --id UB-Mannheim.TesseractOCR --accept-source-agreements

# Yöntem B — manuel installer
# https://github.com/UB-Mannheim/tesseract/wiki
```

Türkçe `tur.traineddata` (18.7 MB) — proje-lokal:
```powershell
mkdir backend\models\tessdata
curl -L -o backend\models\tessdata\tur.traineddata `
  https://github.com/tesseract-ocr/tessdata/raw/main/tur.traineddata
```

Doğrulama:
```powershell
tesseract --version       # 5.4+ görmeli
# Hangi tessdata kullanıldığı ocr.py'da TESSDATA_PREFIX ile pin edilir
```

```python
from multimodal.ocr import extract_text
result = await extract_text(image_bytes, lang="tur")
```

## API Endpoints

| Endpoint | Body | Response |
|---|---|---|
| `POST /multimodal/ocr` | multipart `image` | `{text, engine, elapsed_ms}` |
| `POST /multimodal/stt` | multipart `audio` | `{text, language, segments}` |
| `POST /multimodal/tts` | `{text}` | binary WAV stream |

## ENV (.env)

```bash
# OCR
OCR_ENGINE=tesseract              # veya qwen-vl
OCR_LANG=tur                      # veya tur+eng
OCR_TIMEOUT_S=30

# STT
STT_ENGINE=faster-whisper
STT_MODEL=                        # boş → backend/models/whisper local path
STT_DEVICE=cpu                    # cuda
STT_COMPUTE_TYPE=int8             # float16 (cuda)
STT_LANG=tr

# TTS
TTS_ENGINE=piper
TTS_MODEL=tr_TR-dfki-medium
TTS_VOICE_DIR=                    # boş → backend/models/piper local
TTS_MAX_CHARS=2000
```

## Model İndirme Komutları

```bash
cd backend

# Piper TR voice (61 MB)
mkdir -p models/piper
hf download rhasspy/piper-voices \
  tr/tr_TR/dfki/medium/tr_TR-dfki-medium.onnx \
  tr/tr_TR/dfki/medium/tr_TR-dfki-medium.onnx.json \
  --local-dir models/piper

# faster-whisper-small (462 MB) — Sprint-6 default
mkdir -p models/whisper
hf download Systran/faster-whisper-small --local-dir models/whisper

# (Opsiyonel) Whisper large-v3 daha doğru (3 GB)
hf download Systran/faster-whisper-large-v3 --local-dir models/whisper-large-v3
```

## Latency Benchmarks (Sprint-6 reference)

| Pipeline | İlk Çağrı (cold) | Sonraki (warm) |
|---|---|---|
| TTS Piper (50 char) | ~1.7s | ~0.3s |
| STT Whisper-small CPU (5s ses) | ~14s | ~3s |
| STT Whisper-small CUDA fp16 | (henüz test yok) | ~1s tahmini |
| OCR Tesseract (A4 belge) | ~2s | ~1.5s |

## Bilinen Sınırlar

1. **Whisper-small TR "Kıdem" → "Kıdam"** (yumuşatma) — `large-v3` ile düzelir
2. **Piper DFKI tek voice** (male, monotone) — Coqui XTTS-v2 ile multi-voice (Sprint-7)
3. **Tesseract elyazısı çözmez** — Qwen2-VL fallback `OCR_QWEN_VL_ENABLED=1`
4. **OCR binary'sini Docker/Linux dışında otomatik kurmak zor** — runbook'a güveniyoruz

## Sprint-7+ Öneriler

- [ ] Whisper-large-v3 CUDA smoke (5x hız hedef)
- [ ] Coqui XTTS-v2 voice cloning
- [ ] OCR + LLM hibrit: Tesseract çıktı + Qwen rehabilitasyon
- [ ] WebSocket streaming STT (chunk-by-chunk)
