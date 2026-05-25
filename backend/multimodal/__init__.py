"""Multimodal modülü — OCR (belge fotoğrafı), STT (sesli giriş), TTS (sesli cevap).

Tüm modeller LOKAL ÇALIŞIR (CLAUDE.md §3 — production cloud LLM API yasak).
Modeller lazy-load: ilk çağrıda HF cache'inden indirilir, sonra in-memory.
"""

from .ocr import OCRResult, extract_text
from .stt import STTResult, transcribe_audio
from .tts import TTSResult, synthesize_speech

__all__ = (
    "OCRResult",
    "STTResult",
    "TTSResult",
    "extract_text",
    "synthesize_speech",
    "transcribe_audio",
)
