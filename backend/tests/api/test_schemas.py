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
