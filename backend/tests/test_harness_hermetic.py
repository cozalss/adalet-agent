"""Harness hermetiklik kalkanı — `.env` sızıntısına karşı regresyon kilidi.

KÖK OLAY (2026-06-17): test komutu `source .env` yapınca prod değerleri
(LLM_MODE=llamacpp_server, AUTH_PROVIDER=supabase, SUPABASE_URL=...) pytest'ten
ÖNCE ortama yazılıyordu. conftest.py `os.environ.setdefault(...)` kullandığı için
no-op oluyor → 38 test canlı llama-server'a / Supabase JWKS'e gidip çöküyordu
(`All connection attempts failed`, `kid=None` → 401). conftest artık bu üç
değişkeni FORCE override eder. Bu testler o invariant'ı kalıcı kilitler —
biri yanlışlıkla `setdefault`'a geri çevirirse CI yakalar.
"""

from __future__ import annotations

import os

from agents.llm import MockLLM, get_llm


def test_llm_mode_is_forced_mock():
    """Unit suite ASLA gerçek LLM'e gitmez — .env sourced olsa bile mock."""
    assert os.environ["LLM_MODE"] == "mock"
    assert isinstance(get_llm(), MockLLM)


def test_auth_provider_is_forced_internal():
    """decode_token internal HS256 yolunu kullanır (Supabase JWKS'e düşmez)."""
    assert os.environ.get("AUTH_PROVIDER") == "internal"
    assert os.environ.get("SUPABASE_URL", "") == ""


def test_hyde_disabled_no_network():
    """HyDE kapalı — testler retrieval'da network'e gitmez."""
    assert os.environ["HYDE_ENABLED"] == "0"
