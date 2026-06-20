"""AskRequest şema validasyon testleri — özellikle user_meta DoS guard."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.routes.ask import _state_to_response
from api.schemas import AskRequest, AskResponse


def test_minimal_valid_request():
    req = AskRequest(question="Kıdem tazminatı nasıl hesaplanır?")
    assert req.user_meta is None
    assert req.want_dilekce is False


def test_user_meta_small_dict_ok():
    req = AskRequest(question="soru?", user_meta={"sehir": "Ankara", "taraf": "isci"})
    assert req.user_meta == {"sehir": "Ankara", "taraf": "isci"}


def test_user_meta_too_many_keys_rejected():
    big = {f"k{i}": "v" for i in range(25)}  # 25 > 20
    with pytest.raises(ValidationError, match="anahtar"):
        AskRequest(question="soru?", user_meta=big)


def test_user_meta_too_large_rejected():
    huge = {"blob": "x" * 5000}  # serileştirilmiş > 4096 bayt
    with pytest.raises(ValidationError, match="büyük"):
        AskRequest(question="soru?", user_meta=huge)


def test_ask_response_clarifying_questions_defaults_empty():
    # Yapısal clarify alanı additive — varsayılan boş liste (cevap clarify değil).
    resp = AskResponse(
        answer="x", domain="kira", domain_confidence=0.9, confidence=0.8, verdict="pass",
    )
    assert resp.clarifying_questions == []


def test_state_to_response_surfaces_clarifying_questions():
    # needs_clarification state'i → yapısal clarifying_questions API'ye yansır
    # (frontend markdown regex'ine bağımlı kalmaz).
    state = {
        "response": "Daha doğru yardımcı olabilmem için ...",
        "domain": "kira",
        "response_intent": "needs_clarification",
        "clarifying_questions": ["Kiracıyı hangi sebeple çıkarmak istiyorsunuz?", "Sözleşme yazılı mı?"],
    }
    resp = _state_to_response(state, elapsed_ms=10, conv_id="c1")
    assert resp.response_intent == "needs_clarification"
    assert resp.clarifying_questions == [
        "Kiracıyı hangi sebeple çıkarmak istiyorsunuz?",
        "Sözleşme yazılı mı?",
    ]


def test_state_to_response_clarifying_questions_empty_for_normal_answer():
    state = {"response": "Kıdem tazminatı ...", "domain": "isHukuku", "response_intent": "legal_answer"}
    resp = _state_to_response(state, elapsed_ms=5)
    assert resp.clarifying_questions == []
    assert resp.clarify_options == []


def test_state_to_response_surfaces_clarify_options():
    # Tıklanabilir sebep-şıkları (round-1) API'ye yansır.
    state = {
        "response": "...",
        "domain": "kira",
        "response_intent": "needs_clarification",
        "clarifying_questions": ["Kiracıyı hangi sebeple çıkarmak istiyorsunuz?"],
        "clarify_options": ["İhtiyaç nedeniyle", "Kira ödenmiyor (temerrüt)"],
    }
    resp = _state_to_response(state, elapsed_ms=10)
    assert resp.clarify_options == ["İhtiyaç nedeniyle", "Kira ödenmiyor (temerrüt)"]


def test_question_min_length_enforced():
    with pytest.raises(ValidationError):
        AskRequest(question="ab")  # < 3


def test_question_max_length_enforced():
    with pytest.raises(ValidationError):
        AskRequest(question="x" * 2001)  # > 2000


# --- conversation_id güvenlik (denetim 2026-06-04: Redis key injection guard) ---

def test_conversation_id_valid_hex_accepted():
    """Gerçek backend formatı (uuid4().hex, 32 hane) kabul edilmeli."""
    req = AskRequest(question="soru?", conversation_id="10e73f7d562a4f0b8ba00c4aaa7cddf0")
    assert req.conversation_id == "10e73f7d562a4f0b8ba00c4aaa7cddf0"


@pytest.mark.parametrize("bad", ["abc:owner", "star*", "a/b", "sp ace", "id;drop", "x" * 129])
def test_conversation_id_injection_chars_rejected(bad):
    """':'/'*'/'/'/boşluk gibi Redis özel/path karakterleri reddedilir (422)."""
    with pytest.raises(ValidationError):
        AskRequest(question="soru?", conversation_id=bad)


# --- OCR belge ekleri (image_attachments) ---

def test_attachment_accepted():
    from api.schemas import AskRequest
    req = AskRequest(question="soru?", image_attachments=[
        {"filename": "kira.jpg", "ocr_engine": "tesseract", "text": "metin", "n_chars": 5},
    ])
    assert req.image_attachments[0].text == "metin"


def test_attachment_text_length_capped():
    import pytest
    from pydantic import ValidationError

    from api.schemas import AskRequest
    with pytest.raises(ValidationError):
        AskRequest(question="soru?", image_attachments=[
            {"filename": "x", "ocr_engine": "t", "text": "a" * 10001, "n_chars": 10001},
        ])


def test_too_many_attachments_rejected():
    import pytest
    from pydantic import ValidationError

    from api.schemas import AskRequest
    atts = [{"filename": "x", "ocr_engine": "t", "text": "m", "n_chars": 1} for _ in range(6)]
    with pytest.raises(ValidationError):
        AskRequest(question="soru?", image_attachments=atts)


# --- belge-meta sanitizasyonu (security scan 2026-06-18: path-traversal + log-injection) ---

def test_attachment_filename_path_traversal_sanitized():
    """'../../etc/passwd' → yalnız basename + güvenli charset (path-traversal savunması)."""
    from api.schemas import AskRequest
    req = AskRequest(question="soru?", image_attachments=[
        {"filename": "../../../etc/passwd", "ocr_engine": "tesseract", "text": "m", "n_chars": 1},
    ])
    fn = req.image_attachments[0].filename
    assert "/" not in fn and "\\" not in fn and ".." not in fn
    assert fn == "passwd"


def test_attachment_filename_control_chars_stripped():
    """Newline/null (log-injection) → '_' ile temizlenir; Türkçe ad KORUNUR."""
    from api.schemas import AskRequest
    req = AskRequest(question="soru?", image_attachments=[
        {"filename": "kira\nsözleşmesi\x00.jpg", "ocr_engine": "x", "text": "m", "n_chars": 1},
    ])
    fn = req.image_attachments[0].filename
    assert "\n" not in fn and "\x00" not in fn
    assert "sözleşmesi" in fn  # Türkçe karakter bozulmadı


def test_attachment_ocr_engine_valid_values_preserved():
    """Gerçek motor adları ('qwen2-vl', 'none', 'auto') REDDEDİLMEZ (whitelist kırardı)."""
    from api.schemas import AskRequest
    for eng in ("tesseract", "qwen2-vl", "qwen-vl", "auto", "none"):
        req = AskRequest(question="soru?", image_attachments=[
            {"filename": "b", "ocr_engine": eng, "text": "m", "n_chars": 1},
        ])
        assert req.image_attachments[0].ocr_engine == eng


def test_attachment_ocr_engine_injection_stripped():
    """Kontrol karakteri / log-injection ocr_engine'de temizlenir."""
    from api.schemas import AskRequest
    req = AskRequest(question="soru?", image_attachments=[
        {"filename": "b", "ocr_engine": "tess\nrm -rf", "text": "m", "n_chars": 1},
    ])
    assert "\n" not in req.image_attachments[0].ocr_engine
