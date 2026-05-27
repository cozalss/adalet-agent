"""verifier/nli.py — tokenization sözleşmesi (W20).

Gerçek mDeBERTa modeli testte yüklenmez (ağır). Fake tokenizer/model enjekte
edip NLI'nın `truncation="only_first"` ile çağrıldığını doğrularız: premise
kesilebilir ama claim (hypothesis) HER ZAMAN tam kalmalı.
"""

from __future__ import annotations

from verifier.nli import NLIVerifier

# NOT: torch'u MODÜL seviyesinde import ETME / tensor OLUŞTURMA. Windows'ta
# collection anında torch init başka torch-kullanan testlerle çakışıp native
# access-violation (segfault) tetikliyor (kod tabanı PRELOAD_MODELS notları).
# torch yalnız çağrı anında (_FakeModel.__call__) yüklenir.


class _FakeInputs(dict):
    def to(self, _device):
        return self


class _FakeTokenizer:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return _FakeInputs()


class _FakeModel:
    def __call__(self, **_inputs):
        import torch

        class _O:
            # entailment yüksek → label "entailment"
            logits = torch.tensor([[3.0, 0.2, 0.1]])

        return _O()


def _verifier_with_fakes() -> tuple[NLIVerifier, _FakeTokenizer]:
    v = NLIVerifier()
    tok = _FakeTokenizer()
    # cached_property'yi bypass et — instance __dict__'e komponentleri koy.
    v.__dict__["_components"] = (tok, _FakeModel(), "cpu")
    return v, tok


def test_verify_uses_only_first_truncation():
    v, tok = _verifier_with_fakes()
    result = v.verify(claim="kısa bir iddia", evidence="uzun premise metni " * 50)
    assert result.label == "entailment"
    assert tok.calls, "tokenizer çağrılmadı"
    assert tok.calls[0]["kwargs"]["truncation"] == "only_first"
    # premise önce, claim sonra (NLI pair sırası)
    assert tok.calls[0]["args"] == ("uzun premise metni " * 50, "kısa bir iddia")


def test_verify_batch_uses_only_first_truncation():
    v, tok = _verifier_with_fakes()
    v.verify_batch([("iddia 1", "premise 1"), ("iddia 2", "premise 2")])
    # premise listesi önce, hypothesis listesi sonra + only_first
    assert tok.calls[0]["kwargs"]["truncation"] == "only_first"
    assert tok.calls[0]["args"] == (["premise 1", "premise 2"], ["iddia 1", "iddia 2"])


def test_verify_empty_inputs_short_circuit():
    """Boş claim/evidence → tokenizer çağrılmadan neutral döner."""
    v, tok = _verifier_with_fakes()
    result = v.verify(claim="", evidence="premise")
    assert result.label == "neutral"
    assert not tok.calls  # erken çıkış
