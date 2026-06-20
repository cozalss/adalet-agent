"""TTS — Türkçe metni sesli cevaba çevir.

Engine: **Piper** (onnxruntime backend, hızlı, küçük, lokal, ücretsiz).
  - Türkçe modeli: `tr_TR-fettah-medium` (Rhasspy/piper-voices HF)
  - Boyut: ~60 MB (.onnx + .json), CPU'da real-time 8x
  - INT8 onnx model — Pi 4'te bile çalışır

Alternatif: **Coqui XTTS-v2** — daha doğal ama 1.5 GB, GPU önerilir.
Default: Piper (production lokal CPU, mobil entegre).

Akış:
  1. Lazy load Piper voice (~60MB onnx)
  2. synthesize(text) → 16kHz WAV bytes
  3. Caller: SSE stream, mobil push, file download

Sınır:
  - Tek seferlik max 2000 char (TTS uzun cevaplarda anlamsız)
  - Disclaimer otomatik kesilir (her cevapta tekrarlanması yorucu)

ENV:
    TTS_ENGINE=piper|coqui|none           (default piper; "none" → kapalı)
    TTS_MODEL=tr_TR-fettah-medium
    TTS_VOICE_DIR=~/.cache/piper          (model cache)
    TTS_MAX_CHARS=2000
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import structlog

from multimodal.tts_cloud import cloud_tts_enabled, synthesize_openai

log = structlog.get_logger()

TTS_ENGINE = os.getenv("TTS_ENGINE", "piper").lower()
# 2026-05-26: rhasspy/piper-voices TR repo'sunda mevcut tek voice DFKI
# (eskiden fettah ismiyle planlanmıştı, gerçek upload DFKI). ENV ile override:
TTS_MODEL = os.getenv("TTS_MODEL", "tr_TR-dfki-medium")
# Sprint-6: backend/models/piper/ altındaki HF mirror path varsayılan
_DEFAULT_VOICE_DIR = Path(__file__).parent.parent / "models" / "piper" / "tr" / "tr_TR" / "dfki" / "medium"
TTS_VOICE_DIR = Path(
    os.getenv("TTS_VOICE_DIR", str(_DEFAULT_VOICE_DIR)),
)
TTS_MAX_CHARS = int(os.getenv("TTS_MAX_CHARS", "2000"))
TTS_TIMEOUT_S = float(os.getenv("TTS_TIMEOUT_S", "30"))
# Sağlayıcı (v2.3 — bulut serbest): auto = OPENAI_API_KEY varsa OpenAI TTS (doğal Türkçe),
# yoksa lokal Piper. openai = her zaman bulut dene. local = tam-lokal (Piper).
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "auto").lower()
TTS_CLOUD_FALLBACK = os.getenv("TTS_CLOUD_FALLBACK", "1").lower() in {"1", "true", "yes"}

# Hukuki disclaimer'ı TTS'e gönderirken kes — her cevapta tekrarlanması kötü UX
_DISCLAIMER_MARKERS = (
    "Bu cevap hukuki tavsiye değildir",
    "⚠️",
    "---\n**Kaynaklar",
)


@dataclass(slots=True)
class TTSResult:
    audio_bytes: bytes
    sample_rate: int
    duration_s: float
    elapsed_ms: int
    engine: str = TTS_ENGINE
    n_chars: int = 0
    error: str | None = None


# --------------------------------------------------------------------------
#  Piper engine
# --------------------------------------------------------------------------

class PiperEngine:
    """Piper voice singleton — lazy onnx load."""

    def __init__(self, voice_name: str = TTS_MODEL, voice_dir: Path = TTS_VOICE_DIR) -> None:
        self.voice_name = voice_name
        self.voice_dir = voice_dir
        self._voice_cache: object | None = None
        self._voice_lock = threading.Lock()

    @property
    def _voice(self):
        """Piper onnx lazy load — THREAD-SAFE (double-checked locking). synthesize_wav
        asyncio.to_thread içinde çağrılır; eş zamanlı ilk-istekler çift yüklemesin (OCR
        _vl_load_lock pattern, code-review 2026-06-18). Yüklü ise kilit ucuz."""
        if self._voice_cache is None:
            with self._voice_lock:
                if self._voice_cache is None:
                    from piper import PiperVoice

                    # piper-tts voice dosya konvansiyonu: <name>.onnx + .onnx.json
                    onnx_path = self.voice_dir / f"{self.voice_name}.onnx"
                    if not onnx_path.exists():
                        raise FileNotFoundError(
                            f"Piper voice bulunamadı: {onnx_path}. "
                            f"İndir: https://huggingface.co/rhasspy/piper-voices/tree/main/tr/tr_TR"
                        )
                    log.info("tts_loading_piper", voice=str(onnx_path))
                    self._voice_cache = PiperVoice.load(str(onnx_path))
        return self._voice_cache

    def synthesize_wav(self, text: str) -> tuple[bytes, int]:
        """Tek pass synthesize → (wav_bytes, sample_rate).

        piper-tts v1.4+: ``synthesize_wav(text, wav_file, set_wav_format=True)``
        otomatik header (channels, sample_rate, sample_width) yazar. Eskiden
        düz ``synthesize(text, wav)`` çalışıyordu, kaldırıldı.
        """
        import io
        import wave

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            self._voice.synthesize_wav(text, wav, set_wav_format=True)
        sample_rate = self._voice.config.sample_rate
        return buf.getvalue(), sample_rate


_engine_singleton: PiperEngine | None = None


def get_engine() -> PiperEngine:
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = PiperEngine()
    return _engine_singleton


def reset_engine() -> None:
    global _engine_singleton
    _engine_singleton = None


# --------------------------------------------------------------------------
#  Public API
# --------------------------------------------------------------------------

def _use_cloud_tts() -> bool:
    """TTS bulut'a mı gitsin? auto: anahtar varsa evet. openai: her zaman dene (anahtar
    yoksa synthesize_openai raise → fallback). local: asla (Piper)."""
    if TTS_PROVIDER == "local":
        return False
    if TTS_PROVIDER == "openai":
        return True
    return cloud_tts_enabled()  # auto


def _wav_sample_rate(wav: bytes, default: int = 24000) -> int:
    """WAV header'dan örnekleme hızı (OpenAI TTS ~24kHz). Parse edilemezse default."""
    if len(wav) >= 28 and wav[:4] == b"RIFF" and wav[8:12] == b"WAVE":
        return int.from_bytes(wav[24:28], "little") or default
    return default


async def synthesize_speech(
    text: str,
    *,
    strip_disclaimer: bool = True,
    max_chars: int = TTS_MAX_CHARS,
) -> TTSResult:
    """Metin → 16kHz WAV bytes.

    Args:
        text: cevap metni
        strip_disclaimer: True → "Bu cevap hukuki tavsiye değildir..." kısmı
                          ve sonrası kesilir
        max_chars: aşılırsa cümle sınırında kes
    """
    if TTS_ENGINE == "none":
        return TTSResult(
            audio_bytes=b"", sample_rate=0, duration_s=0.0,
            elapsed_ms=0, engine="none", n_chars=0,
            error="TTS disabled (TTS_ENGINE=none)",
        )
    if not text or not text.strip():
        return TTSResult(
            audio_bytes=b"", sample_rate=0, duration_s=0.0,
            elapsed_ms=0, n_chars=0, error="boş metin",
        )

    cleaned = _prepare_text(text, strip_disclaimer=strip_disclaimer, max_chars=max_chars)
    start = time.perf_counter()

    # Bulut TTS (OpenAI) — anahtar/seçim varsa öncelik; başarısızsa Piper'a graceful düş.
    if _use_cloud_tts():
        try:
            audio = await asyncio.wait_for(
                synthesize_openai(cleaned, timeout_s=TTS_TIMEOUT_S), timeout=TTS_TIMEOUT_S + 5,
            )
            sr = _wav_sample_rate(audio)
            return TTSResult(
                audio_bytes=audio, sample_rate=sr, duration_s=_wav_duration_s(audio, sr),
                elapsed_ms=int((time.perf_counter() - start) * 1000),
                engine="openai-tts", n_chars=len(cleaned),
            )
        except Exception as exc:  # ağ/anahtar/limit/timeout → Piper fallback (detay loglanmaz)
            log.warning("tts_cloud_failed", error=type(exc).__name__, fallback=TTS_CLOUD_FALLBACK)
            if not TTS_CLOUD_FALLBACK:
                return TTSResult(
                    audio_bytes=b"", sample_rate=0, duration_s=0.0,
                    elapsed_ms=int((time.perf_counter() - start) * 1000),
                    engine="openai-tts", n_chars=len(cleaned), error="bulut TTS başarısız",
                )
            # fallback açık → aşağıdaki Piper'a devam

    try:
        engine = get_engine()
        try:
            audio, sample_rate = await asyncio.wait_for(
                asyncio.to_thread(engine.synthesize_wav, cleaned),
                timeout=TTS_TIMEOUT_S,
            )
        except TimeoutError:
            return TTSResult(
                audio_bytes=b"", sample_rate=0, duration_s=0.0,
                elapsed_ms=int(TTS_TIMEOUT_S * 1000),
                n_chars=len(cleaned), error="tts timeout",
            )
    except ImportError as exc:
        log.warning("tts_import_failed", error=str(exc))
        return TTSResult(
            audio_bytes=b"", sample_rate=0, duration_s=0.0,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            n_chars=len(cleaned), error="TTS motoru kullanılamıyor",
        )
    except FileNotFoundError as exc:
        # str(exc) eksik model/binary dosya YOLUNU sızdırır → log'a, kullanıcıya generic.
        log.warning("tts_file_not_found", error=str(exc))
        return TTSResult(
            audio_bytes=b"", sample_rate=0, duration_s=0.0,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            n_chars=len(cleaned), error="TTS motoru kullanılamıyor",
        )
    except Exception as exc:
        log.exception("tts_failed", error=str(exc))
        return TTSResult(
            audio_bytes=b"", sample_rate=0, duration_s=0.0,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            n_chars=len(cleaned), error="TTS üretilemedi",
        )

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    duration_s = _wav_duration_s(audio, sample_rate)
    log.info(
        "tts_done", n_chars=len(cleaned), duration_s=duration_s,
        sample_rate=sample_rate, elapsed_ms=elapsed_ms,
    )
    return TTSResult(
        audio_bytes=audio,
        sample_rate=sample_rate,
        duration_s=duration_s,
        elapsed_ms=elapsed_ms,
        n_chars=len(cleaned),
    )


# --------------------------------------------------------------------------
#  Helpers
# --------------------------------------------------------------------------

# TTS okunuş normalizasyonu (#39): Piper/Coqui kısaltmaları harf-harf okur ("Md." → "em-de",
# "TKHK" → "te-ke-ha-ka", "5000 TL" → "...te-le"). Yalnız SESLİ çıktıya uygulanır — görünen
# cevabı/citation'ı/doğrulamayı ETKİLEMEZ (kırmızı çizgi güvenli; salt okuma yardımı).
# Kanun adları standart/doğrulanmış (uydurma değil); tam adın seslendirilmesi içeriği değiştirmez.
_TR_WC = r"A-Za-zÇĞIİÖŞÜçğıiöşü0-9"
_TTS_LAW_ABBREV = {
    "TKHK": "Tüketicinin Korunması Hakkında Kanun",
    "TBK": "Türk Borçlar Kanunu",
    "TMK": "Türk Medeni Kanunu",
    "TTK": "Türk Ticaret Kanunu",
    "İİK": "İcra ve İflas Kanunu",
    "VUK": "Vergi Usul Kanunu",
    "HMK": "Hukuk Muhakemeleri Kanunu",
    "İYUK": "İdari Yargılama Usulü Kanunu",
}
_MADDE_RE = re.compile(rf"(?<![{_TR_WC}])[Mm][Dd]\.\s*(?=\d)")
_TL_RE = re.compile(rf"(\d)\s*TL(?![{_TR_WC}])")
# Akronimleri uzunluk-azalan sırala (kısa olan uzunun prefiksiyse önce uzunu eşle).
_LAW_ABBREV_RE = re.compile(
    rf"(?<![{_TR_WC}])({'|'.join(sorted(map(re.escape, _TTS_LAW_ABBREV), key=len, reverse=True))})(?![{_TR_WC}])"
)


def _normalize_for_speech(text: str) -> str:
    """Kısaltmaları seslendirme için aç (yalnız TTS metni; kelime-sınırı korumalı)."""
    s = _MADDE_RE.sub("madde ", text)
    s = _TL_RE.sub(r"\1 lira", s)
    s = _LAW_ABBREV_RE.sub(lambda m: _TTS_LAW_ABBREV[m.group(1)], s)
    s = s.replace("₺", " lira ")
    return re.sub(r"[ \t]{2,}", " ", s).strip()


def _prepare_text(
    text: str,
    *,
    strip_disclaimer: bool,
    max_chars: int,
) -> str:
    """Disclaimer'ı kes + char limiti uygula (cümle sınırında) + okunuş normalize (#39)."""
    cleaned = text.strip()
    if strip_disclaimer:
        for marker in _DISCLAIMER_MARKERS:
            idx = cleaned.find(marker)
            if idx > 0:
                cleaned = cleaned[:idx].rstrip()
                break

    if len(cleaned) <= max_chars:
        return _normalize_for_speech(cleaned)

    # Cümle sınırında kes — son . ! ? işaretine kadar
    truncated = cleaned[:max_chars]
    last_period = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
    if last_period > max_chars * 0.6:
        truncated = truncated[: last_period + 1]
    return _normalize_for_speech(truncated.strip())


def _wav_duration_s(audio_bytes: bytes, sample_rate: int) -> float:
    """WAV bytes'tan duration tahmini — header 44 byte + 16-bit mono."""
    if sample_rate <= 0 or len(audio_bytes) < 44:
        return 0.0
    n_samples = (len(audio_bytes) - 44) / 2  # 16-bit = 2 byte
    return round(n_samples / sample_rate, 2)


__all__ = ("PiperEngine", "TTSResult", "get_engine", "reset_engine", "synthesize_speech")
