"""LangGraph topology — Sprint-7/8 pipeline (verify+debate + opsiyonel Self-RAG/CRAG).

Akış (varsayılan — ENV bayrakları kapalı, Sprint-3 baseline):

    START
      │
      ▼
    triaj ─┬─ unknown ─────────────────────────────────→ finalize → END
           │
           └─ ok ──→ [mevzuat, emsal] (paralel) ──→ draft
                                                     │
                                                     ▼
                                                  verify
                                                     │
                                                     ▼
                                                  debate
                                                     │
                                       ┌─────────────┼──────────────┐
                                       │             │              │
                                       ▼             ▼              ▼
                                     retry        pass/reject
                                       │             │
                                       └─→ draft ←───┘
                                                     │
                                                     ▼
                                                  finalize → END

Sprint-7/8 opsiyonel eklemeler (default OFF):

- `CRAG_ENABLED=1`     → [mevzuat, emsal] fan-in sonrası `crag` node
                          retrieval confidence düşükse multi-query + graph expand
                          ile ek kaynak çeker → draft
- `SELF_RAG_ENABLED=1` → debate sonrası `self_rag` node
                          reflection tokens (retrieve/supported/utility)
                          → verdict'i override edebilir (retry/reject)

Notlar:
- mevzuat node'u HyDE-aware: HYDE_ENABLED ortam değişkeniyle anahtarlanır.
- retry loop hard-bounded: debate/self_rag retry_count'u artırır; MAX_RETRY
  aşılırsa hard-reject döner → finalize.
- verify_node NLI yüklenemezse contradiction filter atlar (smoke test güvenli).
- Her opsiyonel node ENV=0 ile no-op (state'i değiştirmez), graph topolojisi
  bayrak kapalıyken Sprint-3 baseline ile birebir aynı.
"""

from __future__ import annotations

import os
from typing import Any

from langgraph.graph import END, START, StateGraph

from agents.config import MAX_RETRY
from agents.nodes.crag import crag_node
from agents.nodes.debate import debate_node
from agents.nodes.draft import draft_node
from agents.nodes.emsal import emsal_node
from agents.nodes.finalize import finalize_node
from agents.nodes.mevzuat import mevzuat_node
from agents.nodes.self_rag import self_rag_node
from agents.nodes.triaj import triaj_node
from agents.nodes.verify import verify_node
from agents.state import AgentState


def _route_after_triaj(state: AgentState) -> list[str] | str:
    """Triaj sonrası fan-out:

    - domain=unknown        → finalize (reject)
    - aksi                  → mevzuat + emsal paralel
    """
    if state.get("domain", "unknown") == "unknown":
        return "finalize"
    return ["mevzuat", "emsal"]


def _route_after_debate(state: AgentState) -> str:
    """Debate (veya self_rag override) verdict'ine göre yönlendir.

    - pass    → finalize
    - retry   → draft (retry_count zaten artırıldı; MAX_RETRY guard burada)
    - reject  → finalize (reddedilmiş cevap)
    """
    verdict = state.get("debate_verdict", "pass")
    retry_count = state.get("retry_count", 0)

    if verdict == "retry" and retry_count <= MAX_RETRY:
        return "draft"
    # pass veya reject veya retry-limit-doldu → finalize
    return "finalize"


def _crag_enabled() -> bool:
    """ENV ile etkin: CRAG_ENABLED=1 (default kapalı)."""
    return os.environ.get("CRAG_ENABLED", "0").lower() in {"1", "true", "yes"}


def _self_rag_enabled() -> bool:
    """ENV ile etkin: SELF_RAG_ENABLED=1 (default kapalı)."""
    return os.environ.get("SELF_RAG_ENABLED", "0").lower() in {"1", "true", "yes"}


def build_graph() -> Any:
    """Compiled LangGraph — `await graph.ainvoke({"question": ...})` ile çağrılır.

    ENV-gated optional nodes:
      - CRAG_ENABLED=1     : [mevzuat, emsal] → crag → draft
      - SELF_RAG_ENABLED=1 : debate → self_rag → router

    Default (env=0): Sprint-3 baseline topology — 124/124 test regression-free.
    """
    g = StateGraph(AgentState)

    g.add_node("triaj", triaj_node)
    # HyDE/multi-query mevzuat_node içinde env-toggle (HYDE_ENABLED,
    # MULTI_QUERY_ENABLED) ile ele alınır; iç asyncio.wait_for + plain-hybrid
    # fallback ile latency güvende.
    g.add_node("mevzuat", mevzuat_node)
    g.add_node("emsal", emsal_node)
    g.add_node("draft", draft_node)
    g.add_node("verify", verify_node)
    g.add_node("debate", debate_node)
    g.add_node("finalize", finalize_node)

    # Opsiyonel SOTA node'lar
    crag_on = _crag_enabled()
    self_rag_on = _self_rag_enabled()
    if crag_on:
        g.add_node("crag", crag_node)
    if self_rag_on:
        g.add_node("self_rag", self_rag_node)

    g.add_edge(START, "triaj")

    # Triaj sonrası fan-out / kapsam-dışı reject
    g.add_conditional_edges(
        "triaj",
        _route_after_triaj,
        ["mevzuat", "emsal", "finalize"],
    )

    # Fan-in: mevzuat ve emsal bittiğinde → (crag veya draft)
    if crag_on:
        g.add_edge("mevzuat", "crag")
        g.add_edge("emsal", "crag")
        g.add_edge("crag", "draft")
    else:
        g.add_edge("mevzuat", "draft")
        g.add_edge("emsal", "draft")

    # Draft → verify → debate
    g.add_edge("draft", "verify")
    g.add_edge("verify", "debate")

    # Debate sonrası: (self_rag ek katmanı varsa) → router
    if self_rag_on:
        g.add_edge("debate", "self_rag")
        g.add_conditional_edges(
            "self_rag",
            _route_after_debate,
            ["draft", "finalize"],
        )
    else:
        g.add_conditional_edges(
            "debate",
            _route_after_debate,
            ["draft", "finalize"],
        )

    g.add_edge("finalize", END)

    return g.compile()


def make_initial_state(
    question: str,
    *,
    want_dilekce: bool = False,
    user_meta: dict | None = None,
) -> AgentState:
    """Boş AgentState — tüm alanları başlat ki TypedDict hatası çıkmasın."""
    return AgentState(
        question=question,
        want_dilekce=want_dilekce,
        user_meta=user_meta or {},
        domain="unknown",
        domain_confidence=0.0,
        triage_reasoning="",
        mevzuat_refs=[],
        emsal_refs=[],
        draft_response="",
        claims=[],
        verified_claims=[],
        debate_verdict="pass",
        debate_notes="",
        retry_count=0,
        response="",
        confidence=0.0,
        disclaimers=[],
        errors=[],
    )
