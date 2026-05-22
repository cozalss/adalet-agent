# multimodal

OCR + STT + TTS pipeline'ları.

## Bileşenler

- `ocr.py` — Tesseract 5 (TR) + Qwen2-VL hibrit
- `stt.py` — Whisper large-v3 (TR) lokal
- `tts.py` — Coqui XTTS-v2 (TR)
- `normalize.py` — Türkçe metin temizleme

## OCR Stratejisi

1. Tesseract 5 ile hızlı OCR (yapılandırılmış belgeler)
2. Düşük güven skorlu satırlar Qwen2-VL'ye yollanır (el yazısı, karmaşık)
3. Metin Türkçe karakter normalize

## Yapılacaklar

- [ ] Tesseract wrapper + TR dil paketi
- [ ] Qwen2-VL HTTP client
- [ ] Whisper-TR endpoint
- [ ] Coqui TTS endpoint
- [ ] OCR doğruluk testleri (mock belge seti)
