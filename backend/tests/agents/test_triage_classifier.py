"""agents/triage_classifier.py + triaj DistilBERT kademesi — fallback + model-path.

Model checkpoint'i YOKKEN (CI/test) classify_domain None döner → mevcut LLM triaj
yolu KORUNUR (graceful, bağımlılıksız). Model EMİNKEN keyword→model→LLM kademesinde
LLM atlanır.
"""

from __future__ import annotations

import pytest

from agents.triage_classifier import TRIAGE_LABELS, classify_domain


def test_labels_are_eight_civil_domains():
    assert len(TRIAGE_LABELS) == 8
    assert set(TRIAGE_LABELS) == {
        "tuketici", "isHukuku", "kira", "icra", "trafik", "vergi", "tapu", "idari",
    }


def test_returns_none_when_disabled(monkeypatch):
    """TRIAGE_USE_MODEL=0 → torch import edilmeden None (graceful, hızlı)."""
    monkeypatch.setenv("TRIAGE_USE_MODEL", "0")
    assert classify_domain("İnternetten aldığım ürün ayıplı çıktı.") is None


def test_returns_none_when_no_checkpoint(monkeypatch):
    """Varsayılan checkpoint dizini yok → None → mevcut LLM yolu aynen korunur."""
    monkeypatch.setenv("TRIAGE_USE_MODEL", "1")
    assert classify_domain("Kira sözleşmem bitti, ne yapmalıyım?") is None


@pytest.mark.asyncio
async def test_triaj_uses_model_when_confident(monkeypatch):
    """Keyword belirsiz + model EMİN → DistilBERT kademesi domain'i verir (LLM atlanır)."""
    from agents.nodes import triaj as triaj_mod

    monkeypatch.setattr(triaj_mod, "classify_domain", lambda _q: ("kira", 0.92))
    state = {
        "question": "Komşumla aramızda bir anlaşmazlık var, hakkımı nasıl ararım?",
        "chat_history": [],
    }
    result = await triaj_mod.triaj_node(state)
    assert result["domain"] == "kira"
    assert result["domain_confidence"] == 0.92
    assert result["triage_reasoning"] == "DistilBERT-TR domain sınıflandırması."
    assert result["response_intent"] == "legal_answer"


@pytest.mark.asyncio
async def test_triaj_model_path_skipped_with_history(monkeypatch):
    """Geçmiş varsa (multi-turn) model-path ATLANIR → LLM bağlamı kullanır."""
    from agents.nodes import triaj as triaj_mod

    # Model emin dönse bile history varsa kademe çalışmamalı (guard: not history).
    monkeypatch.setattr(triaj_mod, "classify_domain", lambda _q: ("kira", 0.99))
    monkeypatch.setenv("LLM_MODE", "mock")
    state = {
        "question": "Peki bu durumda ne yapmalıyım?",
        "chat_history": [{"role": "user", "content": "Kira sorum var", "domain": "kira"}],
    }
    result = await triaj_mod.triaj_node(state)
    assert result["triage_reasoning"] != "DistilBERT-TR domain sınıflandırması."
