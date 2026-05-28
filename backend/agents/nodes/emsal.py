"""Emsal ajanı — Yargıtay/Danıştay/Anayasa kararları.

Hybrid + Reranker pipeline (en yüksek kalite). doc_type='case' filter.
Sprint-4 W3.4: GRAPH_RAG_ENABLED ise emsal sonuçlarının citation'larından
k-hop graph expand ile yakın madde/konsept node'ları toplanır; bu node id'leri
debate/finalize aşamasında transparency için state.emsal_graph_neighbors'a
yazılır. Yeni retrieval yapmaz; sadece referans zenginleştirir.
Çıkış: state.emsal_refs (fan-in, operator.add)
"""

from __future__ import annotations

import asyncio
import os

import structlog

from agents.config import DOMAIN_PREFERRED_COURTS, RERANK_CANDIDATES, TOP_K_CASE
from agents.state import AgentState, Citation
from core.observability import observe_node
from retrieval.hybrid_search import search, search_with_rerank
from retrieval.reranker import get_reranker

log = structlog.get_logger()

# Sprint-4 W3.4: GraphRAG traversal env-toggle. Default OFF — bayrak kapalıyken
# eski davranış birebir korunur (test'ler regression-free).
GRAPH_NEIGHBORS_TOP_K = int(os.getenv("GRAPH_NEIGHBORS_TOP_K", "3"))


@observe_node(name="emsal")
async def emsal_node(state: AgentState) -> dict:
    question = state["question"]
    domain = state.get("domain", "unknown")
    if domain == "unknown":
        return {"emsal_refs": []}

    # Ana yol: mevcut search_with_rerank (hibrit + rerank). Anayasa hacmi (~9:1)
    # dense'i boğduğunda preferred (DOMAIN_PREFERRED_COURTS) mahkemelerin
    # adaylarını ayrı source-scoped search ile garanti et → tier-sort'a
    # sıralayacak Yargıtay/UYAP malzemesi kalır. Mevzuat'taki kanun_kodu-scoped
    # supplementary pattern'in emsal karşılığı.
    rerank_results = await search_with_rerank(
        question=question,
        top_k=TOP_K_CASE * 2,
        candidates_n=RERANK_CANDIDATES,
        domain=domain,
    )

    preferred = DOMAIN_PREFERRED_COURTS.get(domain) or ()
    n_scoped = 0
    if preferred:
        try:
            scoped_search = await search(
                question=question, top_k=RERANK_CANDIDATES,
                prefetch_limit=RERANK_CANDIDATES, domain=domain,
                source=list(preferred),
            )
            if scoped_search:
                scoped_rerank = await asyncio.to_thread(
                    get_reranker().rerank, question, scoped_search, TOP_K_CASE * 2,
                )
                rerank_results = _merge_dedup_rerank(rerank_results, scoped_rerank)
                n_scoped = len(scoped_rerank)
        except Exception as exc:
            log.warning("emsal_scoped_search_failed", error=str(exc) or type(exc).__name__)

    # case adaylarını ayıkla (doc_type=='case' VEYA source ∈ mahkeme kümesi —
    # seed'lerde doc_type her zaman yazılmıyor, source field her zaman var).
    case_results = [
        rr for rr in rerank_results
        if rr.metadata.get("doc_type") == "case"
        or rr.source in {"anayasa", "yargitay", "danistay", "bedesten", "uyap", "gib_ozelge"}
    ]

    # Mahkeme-öncelikli tier-sort — Anayasa bireysel başvuru hacmi (corpus'ta
    # ~9:1) cross-encoder'ı domine ediyor; vatandaş-yardım domain'lerinde esaslı
    # emsal Yargıtay/Danıştay'dır. Tercih edilen mahkeme öne alınır (stable →
    # cross-encoder sırası tier içinde korunur), sonra TOP_K_CASE'e kesilir.
    case_results, n_preferred = _court_priority_sort(case_results, domain)

    cases: list[Citation] = [
        Citation(
            source_id=rr.chunk_id,
            doc_type="case",
            title=_format_case_title(rr),
            snippet=rr.text[:500],
            url=rr.source_url,
            score=rr.score,
        )
        for rr in case_results[:TOP_K_CASE]
    ]

    # Sprint-4 W3.4: GraphRAG expand — bayrak açık ve graph yüklü ise
    # citation title'larından seed'ler çıkar, k-hop neighbor node id'leri al.
    graph_neighbors: list[str] = []
    try:
        from retrieval.graph_rag import GRAPH_RAG_ENABLED, extract_seed_ids, get_graph
        if GRAPH_RAG_ENABLED and cases:
            seed_ids = extract_seed_ids([c["title"] for c in cases])
            if seed_ids:
                graph = get_graph()
                if graph.is_available and graph.n_nodes > 0:
                    hits = graph.expand(seed_ids, hops=2,
                                        max_nodes=GRAPH_NEIGHBORS_TOP_K * 2)
                    # Seed'in kendi node'larını filtrele (dist=0)
                    graph_neighbors = [
                        h.node.node_id for h in hits if h.distance > 0
                    ][:GRAPH_NEIGHBORS_TOP_K]
    except ImportError as exc:
        log.debug("graph_rag_unavailable", error=str(exc))
    except Exception as exc:
        # GraphRAG sadece referans zenginleştirme (best-effort, yeni retrieval
        # yapmaz). Bozuk graf / beklenmedik hata emsal node'unu ÇÖKERTMEMELİ —
        # emsal_refs zaten hesaplandı, onu döndür. (Eski bare-except yalnız
        # ImportError yakalıyordu; AttributeError/KeyError propagate ediyordu.)
        log.warning("graph_rag_expand_failed", error=str(exc))

    log.info(
        "emsal_done",
        domain=domain, n=len(cases), graph_neighbors=len(graph_neighbors),
        preferred=n_preferred, scoped=n_scoped,
    )
    out: dict = {"emsal_refs": cases}
    if graph_neighbors:
        out["emsal_graph_neighbors"] = graph_neighbors
    return out


def _merge_dedup_rerank(primary: list, secondary: list) -> list:
    """İki rerank/SearchResult listesini chunk_id'ye göre tekilleştir.

    Sıra: önce primary'dekiler, sonra secondary'den NEW olanlar. Tier-sort
    sonradan kararı verir; bu adım sadece havuz çeşitliliği sağlar.
    """
    seen: dict[str, object] = {}
    for r in [*primary, *secondary]:
        cid = r.chunk_id
        if cid not in seen:
            seen[cid] = r
    return list(seen.values())


def _court_priority_sort(cases: list, domain: str) -> tuple[list, int]:
    """Cross-encoder sırasını mahkeme-önceliğiyle birleştir (stable tier sort).

    Anayasa bireysel başvuru kararları corpus'ta hacimce baskın olduğundan
    cross-encoder onları öne koyuyor; oysa vatandaş-yardım domain'lerinde esaslı
    emsal Yargıtay/Danıştay içtihadıdır. DOMAIN_PREFERRED_COURTS'taki mahkeme(ler)
    tier-0'a, diğer non-anayasa tier-1'e, anayasa tier-2'ye iner. `sorted` stable
    olduğundan tier İÇİNDE cross-encoder sırası korunur.

    Returns:
        (re-sıralı liste, tercih-edilen-mahkeme aday sayısı).
    """
    preferred = DOMAIN_PREFERRED_COURTS.get(domain)
    if not preferred:
        return cases, 0
    preferred_set = set(preferred)

    def _tier(rr) -> int:
        src = str(rr.source or "").lower()
        if src in preferred_set:
            return 0
        if src == "anayasa":
            return 2
        return 1

    ordered = sorted(cases, key=_tier)  # stable → tier içinde cross-encoder sırası
    n_preferred = sum(1 for rr in cases if str(rr.source or "").lower() in preferred_set)
    return ordered, n_preferred


def _format_case_title(sr) -> str:
    court = sr.metadata.get("court", "")
    esas = sr.metadata.get("esas_no", "")
    karar = sr.metadata.get("karar_no", "")
    if court and esas and karar:
        return f"{court} {esas}/{karar}"
    if court:
        return f"{court} {sr.chunk_id[:8]}"
    return sr.metadata.get("title") or sr.chunk_id
