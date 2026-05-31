"""AskRequest şema validasyon testleri — özellikle user_meta DoS guard."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.schemas import AskRequest


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


def test_question_min_length_enforced():
    with pytest.raises(ValidationError):
        AskRequest(question="ab")  # < 3


def test_question_max_length_enforced():
    with pytest.raises(ValidationError):
        AskRequest(question="x" * 2001)  # > 2000


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
