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
from itertools import pairwise
from typing import Any

from langgraph.graph import END, START, StateGraph

from agents.config import MAX_RETRY
from agents.nodes.chat import chat_node
from agents.nodes.clarifier import clarifier_node
from agents.nodes.compose import compose_node
from agents.nodes.crag import crag_node
from agents.nodes.debate import debate_node
from agents.nodes.decompose import DECOMPOSE_ENABLED, decompose_node
from agents.nodes.dilekce import dilekce_node
from agents.nodes.draft import draft_node
from agents.nodes.eligibility import eligibility_node
from agents.nodes.emsal import emsal_node
from agents.nodes.finalize import finalize_node
from agents.nodes.mevzuat import mevzuat_node
from agents.nodes.self_rag import self_rag_node
from agents.nodes.tahmin import tahmin_node
from agents.nodes.triaj import triaj_node
from agents.nodes.verify import verify_node
from agents.policy import decide_path
from agents.state import AgentState


def _predictive_enabled() -> bool:
    """ENV ile etkin: PREDICTIVE_ENABLED=1 (default kapalı — 8. ajan opt-in)."""
    return os.environ.get("PREDICTIVE_ENABLED", "0").lower() in {"1", "true", "yes"}


def _dilekce_enabled() -> bool:
    """DILEKCE_ENABLED config flag wrapper — graph build-time karar.

    Tek doğru kaynak: `agents.config.DILEKCE_ENABLED` (DRY). Node graph'a
    EKLİ olsa bile `state.want_dilekce=False` olduğunda no-op'tur; bu fonksiyon
    yalnız topology kararı içindir (regression toggle).
    """
    # Lazy import — config modül-seviyesinde ENV okuyor; testlerin
    # monkeypatch.setenv ile sonradan değiştirebilmesi için her çağrıda re-eval.
    return os.environ.get("DILEKCE_ENABLED", "1") not in {"0", "false", "False"}


def _sink() -> str:
    """Finalize'dan ÖNCEKİ son durak.

    Sıralama: debate → [tahmin?] → [dilekce?] → compose → finalize.
    `compose` hukuki cevaplarda no-op, yönlendirme gibi özel niyetlerde doğal dil
    üreticidir. Bayraklar kapalıysa sink doğrudan compose olur.

    INVARIANT (code-review notu): `_sink()` ve build_graph()'taki `sink`
    değişkeni AYNI ENV bayraklarını okur (PREDICTIVE/DILEKCE_ENABLED). Bu
    bayraklar process-start'ta sabittir (runtime değişmez) → ikisi DAİMA
    eşittir; conditional-edge target listesi ile router dönüşü desync olmaz.
    Bu yüzden router'lar `_sink()` çağırır ama edge listesi `sink` kullanır —
    güvenli. ENV runtime-mutable yapılırsa bu invariant bozulur (yapmayın).
    """
    if _predictive_enabled():
        return "tahmin"
    if _dilekce_enabled():
        return "dilekce"
    return "compose"


def _route_after_triaj(state: AgentState) -> list[str] | str:
    """Triaj sonrası fan-out — KARAR merkezi policy engine'de (deterministik).

    `decide_path` (agents.policy) cevap-yolunu seçer:
    - clarify  → clarifier (retrieval/draft YOK; takip soruları döner, finalize basar)
    - answer   → mevzuat + emsal paralel (baseline hukuki akış)
    - aksi      → _sink() (redirect/reject_sensitive/smalltalk → finalize)

    Bu, önceden buraya gömülü olan `domain==unknown` kontrolünü policy'ye taşır;
    karar tek yerde toplanır (triaj yalnız sınıflandırır).
    """
    decision = decide_path(state)
    if decision == "clarify":
        return "clarifier"
    if decision == "chat":
        return "chat"
    if decision == "answer":
        # Query decomposition (DECOMPOSE_ENABLED): çok-parçalı soru için önce decompose
        # (alt-soru üret) → sonra [mevzuat, emsal] fan-out. Kapalıysa doğrudan fan-out.
        return ["decompose"] if DECOMPOSE_ENABLED else ["mevzuat", "emsal"]
    return _sink()


def _route_after_debate(state: AgentState) -> list[str] | str:
    """Debate (veya self_rag override) verdict'ine göre yönlendir.

    - pass    → finalize
    - retry   → mevzuat + emsal RE-RETRIEVE (sonra draft) — retry_count artırıldı
    - reject  → finalize (reddedilmiş cevap)

    Retry artık YENİDEN RETRIEVE eder (architect A1 fix): önceden yalnız draft'a
    dönüyordu, aynı (yetersiz) kaynaklarla → verify garantili tekrar reject ederdi.
    HyDE/multi-query stokastik olduğundan re-retrieve farklı/daha alakalı kaynak
    getirebilir; merge_citations reducer dedup ile ref birikmesini önler.
    """
    verdict = state.get("debate_verdict", "pass")
    retry_count = state.get("retry_count", 0)

    # `<=` KASITLI (code-review notu): debate_node retry_count'u >= MAX_RETRY'de
    # "reject"e çevirir (debate.py). retry_count==MAX_RETRY ile buraya "retry"
    # verdict'iyle gelinir; `<=` ile bir tur daha re-retrieve → draft → debate'e
    # döner, debate bu kez >= MAX_RETRY görüp "reject" üretir ve döngü kapanır.
    # `<` yapılırsa finalize "retry" verdict'iyle biter (çözülmemiş) — YANLIŞ.
    # test_graph_retry_limit_terminates bu invariant'ı doğrular.
    if verdict == "retry" and retry_count <= MAX_RETRY:
        # fast_retry (latency): HyDE/MQ KAPALIYKEN retrieval DETERMİNİSTİK → re-retrieve
        # birebir AYNI ref'i döndürür (israf: ~1-2s retrieval + re-prefill). Retry'nın amacı
        # yalnız re-DRAFT (GPU-FP draft non-determinism telafisi), yeni kaynak değil → ref'ler
        # state'de varken doğrudan draft'a git. HyDE/MQ AÇIKsa (stokastik retrieval yardımcı
        # olabilir) eski re-retrieve yolu korunur. Verify/debate AYNEN çalışır (red-line nötr).
        if _fast_retry_ok(state):
            return "draft"
        return ["mevzuat", "emsal"]
    # pass veya reject veya retry-limit-doldu → finalize (veya tahmin → finalize)
    return _sink()


def _fast_retry_ok(state: AgentState) -> bool:
    """Retry'da retrieval atlanabilir mi? HyDE/MQ kapalı (deterministik retrieval) + ref'ler
    zaten state'de → re-retrieve israf, doğrudan re-draft yeterli."""
    hyde = os.environ.get("HYDE_ENABLED", "0").lower() in {"1", "true", "yes"}
    mq = os.environ.get("MULTI_QUERY_ENABLED", "0").lower() in {"1", "true", "yes"}
    has_refs = bool(state.get("mevzuat_refs") or state.get("emsal_refs"))
    return has_refs and not hyde and not mq


def _crag_enabled() -> bool:
    """ENV ile etkin: CRAG_ENABLED=1 (default kapalı)."""
    return os.environ.get("CRAG_ENABLED", "0").lower() in {"1", "true", "yes"}


def _self_rag_enabled() -> bool:
    """ENV ile etkin: SELF_RAG_ENABLED=1 (default kapalı)."""
    return os.environ.get("SELF_RAG_ENABLED", "0").lower() in {"1", "true", "yes"}


def _eligibility_enabled() -> bool:
    """ENV ile etkin: ELIGIBILITY_ENABLED (default OFF; derin modda açılır)."""
    return os.environ.get("ELIGIBILITY_ENABLED", "0") not in {"0", "false", "False"}


def build_graph() -> Any:
    """Compiled LangGraph — `await graph.ainvoke({"question": ...})` ile çağrılır.

    ENV-gated optional nodes:
      - CRAG_ENABLED=1     : [mevzuat, emsal] → crag → draft
      - SELF_RAG_ENABLED=1 : debate → self_rag → router

    Default (env=0): Sprint-3 baseline topology — 124/124 test regression-free.
    """
    g = StateGraph(AgentState)

    g.add_node("triaj", triaj_node)
    # Clarifier: policy "clarify" derse buraya gelinir; retrieval/draft'a
    # dokunmadan finalize'a akar (takip soruları döner). Baseline'da (policy=answer)
    # bu node hiç ziyaret edilmez → topoloji davranışı korunur.
    g.add_node("clarifier", clarifier_node)
    # Genel sohbet: policy "chat" derse (hukuki-olmayan/selam/genel) → Qwen ile doğal
    # akan cevap, retrieval/verify YOK → finalize basar. Hukuki yol etkilenmez.
    g.add_node("chat", chat_node)
    # HyDE/multi-query mevzuat_node içinde env-toggle (HYDE_ENABLED,
    # MULTI_QUERY_ENABLED) ile ele alınır; iç asyncio.wait_for + plain-hybrid
    # fallback ile latency güvende.
    g.add_node("mevzuat", mevzuat_node)
    g.add_node("emsal", emsal_node)
    g.add_node("draft", draft_node)
    g.add_node("verify", verify_node)
    g.add_node("debate", debate_node)
    g.add_node("compose", compose_node)
    g.add_node("finalize", finalize_node)

    # Opsiyonel SOTA node'lar
    crag_on = _crag_enabled()
    self_rag_on = _self_rag_enabled()
    predictive_on = _predictive_enabled()
    dilekce_on = _dilekce_enabled()
    eligibility_on = _eligibility_enabled()
    if eligibility_on:
        g.add_node("eligibility", eligibility_node)
    if DECOMPOSE_ENABLED:
        # Query decomposition: triaj → decompose → [mevzuat, emsal]. decompose çok-parçalı
        # soruyu alt-sorulara böler; mevzuat node her birine retrieve edip birleştirir.
        g.add_node("decompose", decompose_node)
        g.add_edge("decompose", "mevzuat")
        g.add_edge("decompose", "emsal")
    if crag_on:
        g.add_node("crag", crag_node)
    if self_rag_on:
        g.add_node("self_rag", self_rag_node)
    # Finalize-öncesi zinciri: debate → [tahmin?] → [dilekce?] → compose → finalize
    # Node iç-guard'lar (want_dilekce, verdict, refs) gereksiz çağrıyı no-op
    # yapar; conditional edge yerine in-node guard tercih edildi → graph
    # topolojisi statik, runtime branching sade.
    if predictive_on:
        g.add_node("tahmin", tahmin_node)
    if dilekce_on:
        g.add_node("dilekce", dilekce_node)
    if predictive_on and dilekce_on:
        g.add_edge("tahmin", "dilekce")
        g.add_edge("dilekce", "compose")
    elif predictive_on:
        g.add_edge("tahmin", "compose")
    elif dilekce_on:
        g.add_edge("dilekce", "compose")
    else:
        # Opsiyonel pre-final node yoksa da compose final kontrolünden önce çalışır.
        # Legal cevaplarda no-op olduğu için baseline davranışı korunur.
        pass
    g.add_edge("compose", "finalize")
    # Clarifier dur-ve-sor dalı: tek tur, doğrudan finalize'a.
    g.add_edge("clarifier", "finalize")
    # Genel sohbet: chat → finalize (chat_response doğrudan basılır, disclaimer yok).
    g.add_edge("chat", "finalize")

    # Finalize öncesi son durak — sıralama: tahmin → dilekce → compose → finalize.
    sink = (
        "tahmin" if predictive_on
        else ("dilekce" if dilekce_on else "compose")
    )

    g.add_edge(START, "triaj")

    # Triaj sonrası fan-out / kapsam-dışı reject
    _triaj_targets = ["mevzuat", "emsal", "clarifier", "chat", sink]
    if DECOMPOSE_ENABLED:
        _triaj_targets.append("decompose")
    g.add_conditional_edges("triaj", _route_after_triaj, _triaj_targets)

    # Fan-in: mevzuat ve emsal bittiğinde → retrieve-sonrası zincir → draft.
    # Zincir: [crag?] → [eligibility?] → draft. Bayraklar kapalıysa doğrudan draft
    # (baseline topoloji korunur). eligibility, kaynaklar hazırken eşik-uygunluk
    # kararı üretir; draft bunu prose'a çevirir.
    post_chain: list[str] = []
    if crag_on:
        post_chain.append("crag")
    if eligibility_on:
        post_chain.append("eligibility")
    post_chain.append("draft")

    fan_in_target = post_chain[0]
    g.add_edge("mevzuat", fan_in_target)
    g.add_edge("emsal", fan_in_target)
    for src, dst in pairwise(post_chain):
        g.add_edge(src, dst)

    # Draft → verify → debate
    g.add_edge("draft", "verify")
    g.add_edge("verify", "debate")

    # Debate sonrası: (self_rag ek katmanı varsa) → router.
    # retry → mevzuat+emsal re-retrieve (sonra post_chain → draft → verify → debate);
    # MAX_RETRY guard döngüyü sınırlar. pass/reject → sink.
    _retry_targets = ["mevzuat", "emsal", "draft", sink]  # "draft": fast_retry (re-retrieve atla)
    if self_rag_on:
        g.add_edge("debate", "self_rag")
        g.add_conditional_edges(
            "self_rag",
            _route_after_debate,
            _retry_targets,
        )
    else:
        g.add_conditional_edges(
            "debate",
            _route_after_debate,
            _retry_targets,
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
        response_intent="legal_answer",
        clarifying_questions=[],
        clarify_response="",
        clarification_round=0,
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
