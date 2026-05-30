"""Iter 13 — /ask + /ask/stream uçtan uca graph timeout testleri.

Hung bir graph (LLM/MCP takılı) isteği süresiz tutmamalı: ASK_GRAPH_TIMEOUT_S
aşılırsa /ask 504, /ask/stream `stream_timeout` event döner. ASK_GRAPH_TIMEOUT_S=0
ile tamamen kapatılabilir (baseline davranış).
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient


class _SlowGraph:
    """ainvoke/astream yapay olarak yavaş — timeout yolunu tetikler."""

    async def ainvoke(self, _initial):
        await asyncio.sleep(5)
        return {}

    async def astream(self, _initial, stream_mode="values"):
        await asyncio.sleep(5)
        yield {}


@pytest.fixture
def slow_client(monkeypatch):
    monkeypatch.setenv("ASK_GRAPH_TIMEOUT_S", "0.15")
    from api.routes import ask as ask_mod

    monkeypatch.setattr(ask_mod, "_get_graph", lambda: _SlowGraph())
    from main import app

    return TestClient(app)


def test_ask_times_out_returns_504(slow_client):
    resp = slow_client.post("/ask", json={"question": "Ayıplı malda haklarım nedir?"})
    assert resp.status_code == 504, resp.text
    detail = resp.json()["detail"]
    # Generic, sızıntısız mesaj
    assert "zaman aşımı" in detail.lower()


def test_ask_stream_times_out_emits_timeout_event(slow_client):
    resp = slow_client.post(
        "/ask/stream", json={"question": "İşten çıkarıldım, tazminat alır mıyım?"},
    )
    assert resp.status_code == 200  # SSE bağlantısı açılır, hata event ile gelir
    assert "event: error" in resp.text
    payload = _first_event_payload(resp.text, "error")
    assert payload["v"] == 1
    assert payload["code"] == "stream_timeout"
    assert "zaman aşımı" in payload["detail"].lower()


def test_ask_timeout_disabled_does_not_trip(monkeypatch):
    """ASK_GRAPH_TIMEOUT_S=0 → wait_for sarmalanmaz; hızlı graph normal döner."""
    monkeypatch.setenv("ASK_GRAPH_TIMEOUT_S", "0")
    from api.routes import ask as ask_mod

    class _FastGraph:
        async def ainvoke(self, _initial):
            return {
                "response": "Mock cevap",
                "confidence": 0.9,
                "domain": "tuketici",
                "debate_verdict": "pass",
                "verified_claims": [],
                "disclaimers": [],
                "errors": [],
            }

    monkeypatch.setattr(ask_mod, "_get_graph", lambda: _FastGraph())
    from main import app

    client = TestClient(app)
    resp = client.post("/ask", json={"question": "Kira sözleşmem bitti, ne yapmalıyım?"})
    assert resp.status_code == 200, resp.text


def _first_event_payload(text: str, event: str) -> dict:
    marker = f"event: {event}\n"
    start = text.index(marker) + len(marker)
    data_line = next(
        line for line in text[start:].splitlines() if line.startswith("data: ")
    )
    return json.loads(data_line.removeprefix("data: "))
