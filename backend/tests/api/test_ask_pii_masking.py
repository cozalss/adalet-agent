"""api PII maskeleme — OCR/case_facts session'a + STT yanıtına PII sızıntısı (denetim 2026-06-04).

Bulgu 1 (CRITICAL): LLM'in çıkardığı serbest-metin case_facts'leri session store'a HAM
yazılıyordu (TCKN/telefon/IBAN sızıntısı). Bulgu 3: STT yanıtı OCR ile asimetrik (PII bayrağı yok).
"""

from __future__ import annotations

from api.routes.ask import _persist_turn
from api.schemas import STTUploadResponse
from api.session_store import get_store, reset_store


async def test_persist_turn_masks_pii_in_case_facts():
    """case_facts içindeki telefon/TCKN session store'a maskelenerek yazılır; süre KORUNUR."""
    reset_store()  # in-memory singleton
    await _persist_turn(
        "conv-pii-1", "user", "Kıdem tazminatı sorum var",
        domain="isHukuku",
        case_facts={
            "taraf": "Ayşe Yılmaz, telefon 0555 123 45 67",
            "sure": "2 yıl",
        },
    )
    history = await get_store().get_history("conv-pii-1")
    cf = history[0].get("case_facts", {})  # type: ignore[union-attr]
    assert "0555" not in str(cf), "telefon HAM kaldı (PII sızıntısı)"
    assert "[PII_MASKED]" in str(cf)
    assert cf.get("sure") == "2 yıl", "süre bozulmamalı (fact çıkarımı korunur)"


def test_stt_response_has_pii_fields_symmetric_with_ocr():
    """STTUploadResponse OCR ile SİMETRİK pii bayrakları taşır (default güvenli)."""
    r = STTUploadResponse(text="merhaba", language="tr", duration_s=1.0, elapsed_ms=10)
    assert r.pii_detected is False
    assert r.pii_counts == {}
    flagged = STTUploadResponse(
        text="TC 12345678901", language="tr", duration_s=1.0, elapsed_ms=10,
        pii_detected=True, pii_counts={"tckn": 1},
    )
    assert flagged.pii_detected and flagged.pii_counts["tckn"] == 1
