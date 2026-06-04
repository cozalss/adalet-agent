"""Akış-içi <think> süzgeci — Qwen3.5 boş/dolu <think></think> bloğunu UI'a sızdırmamalı.

Token'lar parça parça gelir + etiket token sınırına bölünebilir → state machine + kısmi-etiket
koruması test edilir. (Birim/mantık; GPU/LLM yok.)
"""

from __future__ import annotations

from agents.llm import _StreamThinkFilter, _strip_think


def _run(deltas: list[str]) -> str:
    out: list[str] = []
    f = _StreamThinkFilter(out.append)
    for d in deltas:
        f.feed(d)
    f.flush()
    return "".join(out)


def test_empty_think_block_suppressed():
    # Qwen3.5'in tipik çıktısı: boş <think></think> + sonra cevap.
    assert _run(["<think>", "\n\n", "</think>", "\n\nKısa cevap: ev sahibi..."]) == "\n\nKısa cevap: ev sahibi..."


def test_think_with_content_suppressed():
    assert _run(["Merhaba ", "<think>", "akıl yürütme", "</think>", " dünya"]) == "Merhaba  dünya"


def test_tag_split_across_tokens():
    # <think> ve </think> token sınırına bölünmüş.
    assert _run(["<th", "ink>giz", "li</thi", "nk>görünür"]) == "görünür"


def test_no_think_passthrough():
    assert _run(["düz ", "metin ", "akışı"]) == "düz metin akışı"


def test_partial_open_held_then_resolved():
    # "<thi" tutulur (emit edilmez), kapanınca think içeriği atılır.
    assert _run(["abc<thi", "nk>x</think>son"]) == "abcson"


def test_unclosed_think_in_strip():
    # _strip_think: kapanışsız <think> → o noktadan sonrası atılır (backstop).
    assert _strip_think("cevap<think>yarım reasoning") == "cevap"
    assert _strip_think("<think>\n\n</think>\n\ngerçek cevap") == "gerçek cevap"
