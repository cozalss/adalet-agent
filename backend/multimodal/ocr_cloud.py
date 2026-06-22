"""Bulut OCR — OpenAI vision (gpt-4o-mini) ile görüntü/taranmış sayfadan metin.

Lokal RapidOCR/Tesseract'a EK seçenek (v2.3 bulut serbest): görüntülerde ve taranmış
PDF sayfalarında belirgin daha yüksek Türkçe doğruluğu (diakritik + el yazısı + tablo).
`ocr.py` auto-routing yapar: OPENAI_API_KEY varsa bulut, yoksa/çağrı patlarsa lokal.
Dijital PDF (PyMuPDF) ve Word (.docx, python-docx) zaten kusursuz metin verir → buluta GİTMEZ.

stt_cloud.py ile aynı desen (raw httpx; openai SDK bağımlılığı yok).

ENV:
    OPENAI_API_KEY=sk-...                  (zorunlu — yoksa RuntimeError → lokal fallback)
    OPENAI_OCR_MODEL=gpt-4o-mini           (default; gpt-4o = daha güçlü/pahalı)
    OPENAI_OCR_MAX_TOKENS=4096             (uzun sayfa metni için tavan)
    OPENAI_BASE_URL=https://api.openai.com/v1  (Azure/proxy override)
"""

from __future__ import annotations

import asyncio
import base64
import io
import os

import httpx
import structlog

from core.openai_compat import cloud_enabled, require_api_key, send_with_retry
from core.openai_compat import validated_base_url as _validated_base_url

log = structlog.get_logger()

_TRANSCRIBE_PATH = "/chat/completions"

# Büyük görüntü guard: base64 data URI + PIL dönüşümü belleği şişirir (20MB görüntü → ~160MB
# anlık). En uzun kenar bu pikseli aşarsa downscale → bellek + OpenAI maliyeti + latency düşer.
_MAX_IMAGE_DIM = int(os.getenv("OPENAI_OCR_MAX_DIM", "2200"))
# Decompression-bomb guard (ocr.py ile aynı değer): dev piksel sayılı görüntü decode'da OOM yapmasın.
_MAX_IMAGE_PIXELS = 50_000_000

# OpenAI vision'ın doğrudan kabul ettiği MIME'ler; diğerleri (tiff vb.) PNG'ye çevrilir.
_DIRECT_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

# Çıkarım istemi: belgedeki metni HARFİYEN, açıklama eklemeden, Türkçe diakritikli ver.
_OCR_PROMPT = (
    "Bu görüntüdeki TÜM metni harfiyen çıkar. Satır/paragraf düzenini koru. "
    "Türkçe karakterleri (ç, ş, ğ, ı, İ, ö, ü) doğru yaz. SADECE belgedeki metni döndür; "
    "yorum, başlık veya açıklama EKLEME. Görüntüde okunur metin yoksa boş bırak."
)


def cloud_ocr_enabled() -> bool:
    """OpenAI anahtarı set mi? (auto-routing kararı için — ortak helper)."""
    return cloud_enabled()


def _detect_image_mime(data: bytes) -> str:
    """İlk byte'lardan görüntü MIME'ı (data URI için). Bilinmeyen → 'application/octet-stream'."""
    if len(data) >= 3 and data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 6 and data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "application/octet-stream"


def _to_supported_image(data: bytes) -> tuple[bytes, str]:
    """OpenAI'nin kabul ettiği bir görüntü+MIME döndür (SENKRON — to_thread'den çağrılır).

    - Küçük + desteklenen (jpeg/png/webp/gif) → dokunma (orijinal bytes).
    - Çok büyük (en uzun kenar > _MAX_IMAGE_DIM) → downscale (bellek/maliyet sınırı).
    - tiff/bilinmeyen → PNG'ye çevir (vision uyumu).
    """
    mime = _detect_image_mime(data)
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = _MAX_IMAGE_PIXELS  # decompression-bomb guard (decode'da raise)
    with Image.open(io.BytesIO(data)) as img:
        w, h = img.size  # lazy — header'dan, pikseller decode edilmeden
        too_big = max(w, h) > _MAX_IMAGE_DIM
        if mime in _DIRECT_MIMES and not too_big:
            return data, mime  # küçük + desteklenen → re-encode gereksiz
        work = img
        if too_big:
            scale = _MAX_IMAGE_DIM / max(w, h)
            work = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        buf = io.BytesIO()
        work.convert("RGB").save(buf, format="PNG")
    return buf.getvalue(), "image/png"


async def ocr_image_openai(
    image_bytes: bytes,
    *,
    timeout_s: float,
    model: str | None = None,
) -> str:
    """OpenAI vision ile görüntü → metin. Başarısızlıkta exception (çağıran lokal'e düşer).

    Anahtar `.env`'den okunur — ASLA hardcode edilmez.
    """
    api_key = require_api_key("bulut OCR")

    model = (model or os.getenv("OPENAI_OCR_MODEL", "gpt-4o-mini")).strip()
    base = _validated_base_url()
    try:
        max_tokens = int(os.getenv("OPENAI_OCR_MAX_TOKENS", "4096"))
    except ValueError:
        max_tokens = 4096
    max_tokens = max(256, min(max_tokens, 16384))  # geçersiz/aşırı değere karşı kıskaç

    # PIL dönüşümü/downscale CPU-bloklayıcı → event loop'u bekletme (to_thread).
    norm_bytes, mime = await asyncio.to_thread(_to_supported_image, image_bytes)
    b64 = base64.b64encode(norm_bytes).decode("ascii")
    data_uri = f"data:{mime};base64,{b64}"

    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _OCR_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_uri, "detail": "high"}},
                ],
            },
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False) as client:
        async def _post() -> httpx.Response:
            return await client.post(f"{base}{_TRANSCRIBE_PATH}", headers=headers, json=payload)

        resp = await send_with_retry(_post)
        payload_json = resp.json()
    choices = payload_json.get("choices") or []
    if not choices:
        return ""
    # Uzun belge max_tokens'a takılırsa OpenAI metni SESSİZCE keser (finish_reason=length).
    # Görünür kıl: çağıran/operatör eksik OCR'ı fark etsin (OPENAI_OCR_MAX_TOKENS artırılabilir).
    if choices[0].get("finish_reason") == "length":
        log.warning("ocr_openai_truncated", max_tokens=max_tokens,
                    note="OCR çıktısı token sınırına takıldı; OPENAI_OCR_MAX_TOKENS artırılabilir")
    return (choices[0].get("message", {}).get("content") or "").strip()


__all__ = ("cloud_ocr_enabled", "ocr_image_openai")
