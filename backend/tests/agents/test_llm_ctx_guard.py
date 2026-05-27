"""LlamaCppClient context-taşma guard — _fit_max_tokens.

prompt + max_tokens n_ctx'i aşarsa llama_decode -1 ile çöker; guard max_tokens'ı
clamp eder. Gerçek model yüklenmez — fake tokenizer ile sınanır.
"""

from __future__ import annotations

from agents.llm import ChatMessage, LlamaCppClient


class _FakeModel:
    """tokenize(text_bytes) → token başına ~3 bayt (deterministik sayım)."""

    def __init__(self, chars_per_token: int = 3) -> None:
        self._cpt = chars_per_token

    def tokenize(self, data: bytes, add_bos: bool = False, special: bool = False):
        return [0] * (max(len(data), 1) // self._cpt)


def _client(n_ctx: int = 8192) -> LlamaCppClient:
    c = LlamaCppClient(model_path="x", n_ctx=n_ctx)
    c._model = _FakeModel()
    return c


def test_no_clamp_when_prompt_small():
    c = _client()
    msgs = [ChatMessage(role="user", content="kısa soru")]
    assert c._fit_max_tokens(msgs, 1536) == 1536


def test_clamps_when_prompt_large():
    c = _client(n_ctx=2048)
    # ~3000 char → ~1000 token prompt; n_ctx 2048 → available ~ 2048-1000-64 < 1536
    msgs = [ChatMessage(role="user", content="x" * 3000)]
    out = c._fit_max_tokens(msgs, 1536)
    assert out < 1536
    assert out >= c._MIN_OUTPUT_TOKENS


def test_clamp_floor_respected_when_prompt_huge():
    c = _client(n_ctx=2048)
    msgs = [ChatMessage(role="user", content="x" * 12000)]  # prompt > n_ctx
    out = c._fit_max_tokens(msgs, 1536)
    assert out == c._MIN_OUTPUT_TOKENS  # tabana iner, negatif/0 dönmez


def test_fallback_estimate_when_tokenizer_raises():
    c = _client()

    class _BadModel:
        def tokenize(self, *a, **k):
            raise RuntimeError("tokenizer yok")

    c._model = _BadModel()
    msgs = [ChatMessage(role="user", content="x" * 3000)]
    # Fallback tahmin yolu çökmemeli, makul bir sayı dönmeli
    out = c._fit_max_tokens(msgs, 1536)
    assert isinstance(out, int)
    assert out >= c._MIN_OUTPUT_TOKENS
