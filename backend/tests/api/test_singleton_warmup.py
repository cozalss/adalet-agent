"""Iter 11 — lifespan request-path singleton warm-up testleri.

Startup'ta graph/llm/store singleton'ları eager init edilmeli: ilk istek soğuk
başlamasın, config hataları boot'ta yüzeye çıksın. Warm-up torch yüklemez
(PRELOAD_MODELS=0 test ortamında bile çalışır), her biri izole — biri patlasa
diğerleri ve startup devam eder.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_lifespan_warms_request_path_singletons(monkeypatch):
    """`with TestClient(app):` lifespan startup'ı tetikler → 3 singleton dolu."""
    import agents.llm as llm_mod
    from api import session_store as ss_mod
    from api.routes import ask as ask_mod

    # Temiz başlangıç: üç singleton da None — warm-up gerçekten kurmalı.
    monkeypatch.setattr(llm_mod, "_singleton", None)
    monkeypatch.setattr(ss_mod, "_store_singleton", None)
    monkeypatch.setattr(ask_mod, "_graph_singleton", None)

    from main import app

    with TestClient(app):
        # Lifespan startup tamamlandı — singleton'lar warm.
        assert llm_mod._singleton is not None, "LLM singleton warm-up edilmedi"
        assert ss_mod._store_singleton is not None, "store singleton warm-up edilmedi"
        assert ask_mod._graph_singleton is not None, "graph singleton warm-up edilmedi"


def test_warmup_failure_does_not_block_startup(monkeypatch):
    """Bir warm-up patlarsa startup yine de tamamlanır (lazy yol fallback).

    get_llm()'i fırlatır yapıyoruz; store + graph yine warm olmalı ve app
    /health'e cevap verebilmeli (startup bloke olmadı).
    """
    import agents.llm as llm_mod
    from api import session_store as ss_mod
    from api.routes import ask as ask_mod

    monkeypatch.setattr(llm_mod, "_singleton", None)
    monkeypatch.setattr(ss_mod, "_store_singleton", None)
    monkeypatch.setattr(ask_mod, "_graph_singleton", None)

    def _boom() -> object:
        raise RuntimeError("warm-up patladı (kasıtlı)")

    monkeypatch.setattr(llm_mod, "get_llm", _boom)

    from main import app

    with TestClient(app) as client:
        # Startup bloke olmadı → endpoint cevap veriyor.
        resp = client.get("/health")
        assert resp.status_code in {200, 503}
        # Patlamayan warm-up'lar yine de kuruldu.
        assert ss_mod._store_singleton is not None
        assert ask_mod._graph_singleton is not None
