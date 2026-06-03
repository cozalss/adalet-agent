"""CRAG — Corrective RAG: retrieval confidence düşükse ek kaynak çek.

Referans: Yan et al. ICLR 2024 — "Corrective Retrieval Augmented Generation"
(arxiv:2401.15884).

Sorun: BGE-M3 + reranker bazen top-5'te gerçekten alakalı kaynak getiremez
(domain confusion, alt-kategori karışıklığı). Klasik retrieval bu durumda
"en iyi 5"i döner, draft yanlış kaynağa dayanır → halüsinasyon riski.

Çözüm: Retrieval confidence düşükse (top-1 score < threshold):
  1. Multi-query expansion ile tekrar dene
  2. GraphRAG ile bilgi grafı expand
  3. (Sprint-9) Web search (yargi-mcp ek sorgu)

CRAG node DRAFT'tan ÖNCE çalışır (verify'dan sonra değil):
  triaj → [mevzuat, emsal] → CRAG (confidence check) →
    {good} → draft
    {weak} → multi_query re-retrieve + graph_expand → draft

Default-safe: ENV `CRAG_ENABLED=0` → node no-op, akış değişmez.
"""

from __future__ import annotations

import os

import structlog

from agents.state import AgentState, Citation

log = structlog.get_logger()

CRAG_ENABLED = os.getenv("CRAG_ENABLED", "0").lower() in {"1", "true", "yes"}
CRAG_CONFIDENCE_THRESHOLD = float(os.getenv("CRAG_THRESHOLD", "0.35"))
CRAG_MIN_REFS = int(os.getenv("CRAG_MIN_REFS", "3"))
CRAG_TOP_K = int(os.getenv("CRAG_TOP_K", "5"))


async def crag_node(state: AgentState) -> dict:
    """Retrieval kalitesini değerlendir, gerekirse multi-query + graph expand.

    Karar mantığı:
      - top-1 retrieval score >= THRESHOLD VE refs >= MIN_REFS → no-op
      - aksi → multi-query expansion ile re-retrieve, sonuçları append et
      - hala zayıfsa → graph_rag expand ile ek node'lar
    """
    if not CRAG_ENABLED:
        return {}

    mevzuat = list(state.get("mevzuat_refs", []))
    emsal = list(state.get("emsal_refs", []))
    all_refs = mevzuat + emsal

    if not all_refs:
        log.info("crag_no_refs_skip")
        return {}

    top_score = max((r["score"] for r in all_refs), default=0.0)
    needs_correction = (
        top_score < CRAG_CONFIDENCE_THRESHOLD or len(all_refs) < CRAG_MIN_REFS
    )

    if not needs_correction:
        log.info("crag_confident", top_score=top_score, n_refs=len(all_refs))
        return {}

    log.info(
        "crag_correcting",
        top_score=top_score, n_refs=len(all_refs),
        threshold=CRAG_CONFIDENCE_THRESHOLD,
    )

    # --- Correction 1: multi-query expansion ---
    extra_law, extra_case = await _multi_query_correct(state)

    # --- Correction 2: graph-rag expand ---
    extra_graph = await _graph_expand_correct(state, all_refs)

    # Append-only (operator.add reducer destekler ama biz tek dönüşle)
    new_mevzuat = _dedupe_by_id(mevzuat + extra_law + extra_graph["law"])
    new_emsal = _dedupe_by_id(emsal + extra_case + extra_graph["case"])

    n_added_law = len(new_mevzuat) - len(mevzuat)
    n_added_case = len(new_emsal) - len(emsal)
    log.info("crag_done", added_law=n_added_law, added_case=n_added_case)

    # Sadece eklenenleri döndür (Annotated reducer eskileri korur)
    delta: dict = {}
    if n_added_law > 0:
        delta["mevzuat_refs"] = new_mevzuat[len(mevzuat):]
    if n_added_case > 0:
        delta["emsal_refs"] = new_emsal[len(emsal):]
    return delta


# --------------------------------------------------------------------------
#  Correction 1: multi-query expansion → re-retrieve
# --------------------------------------------------------------------------

async def _multi_query_correct(
    state: AgentState,
) -> tuple[list[Citation], list[Citation]]:
    """Multi-query ile re-retrieve, doc_type post-filter."""
    try:
        from retrieval.multi_query import search_multi_query
    except Exception as exc:
        log.warning("crag_mq_unavailable", error=str(exc))
        return [], []

    question = state.get("question", "")
    domain = state.get("domain", "unknown")
    if not question or domain == "unknown":
        return [], []

    try:
        results = await search_multi_query(
            question, top_k=CRAG_TOP_K, n_queries=4, per_query_k=20,
            domain=None, sparse_domain=domain,
        )
    except Exception as exc:
        log.warning("crag_mq_search_failed", error=str(exc))
        return [], []

    laws: list[Citation] = []
    cases: list[Citation] = []
    for r in results:
        is_law = r.metadata.get("doc_type") == "law" or r.source == "mevzuat"
        is_case = (
            r.metadata.get("doc_type") == "case"
            or r.source in {"anayasa", "yargitay", "danistay", "bedesten"}
        )
        cite = Citation(
            source_id=r.chunk_id,
            doc_type="law" if is_law else "case",
            title=_format_title(r),
            snippet=r.text[:500],
            url=r.source_url,
            score=r.score,
        )
        if is_law:
            laws.append(cite)
        elif is_case:
            cases.append(cite)
    return laws, cases


# --------------------------------------------------------------------------
#  Correction 2: GraphRAG expand → ek node'lardan citation
# --------------------------------------------------------------------------

async def _graph_expand_correct(
    state: AgentState, current_refs: list[Citation],
) -> dict[str, list[Citation]]:
    """Graph traversal ile ek law/case node'larını çek.

    Şu an placeholder: gerçek Qdrant lookup için graph_node_id → chunk_id
    eşlemesi gerekli (Sprint-9). Şimdilik sadece graph node'larını CITATION'a
    çevirip URL'siz/snippet'siz placeholder döner — verify reddedecektir,
    ama akış kırılmaz.
    """
    # DEVRE DIŞI (denetim 2026-06-04, #18): URL/snippet'siz placeholder citation'lar verify
    # tarafından ZATEN reddedilir → recall katkısı 0; sadece draft prompt'una + NLI verify'a
    # gürültü + token + latency ekler (net-negatif). Graph transparency emsal_node'da ayrıca
    # toplanıyor (emsal_graph_neighbors). Gerçek graph_node_id→chunk_id→Qdrant snippet lookup
    # (Sprint-9) tamamlanınca aşağıdaki gövde yeniden etkinleşir.
    return {"law": [], "case": []}

    try:
        from retrieval.graph_rag import GRAPH_RAG_ENABLED, extract_seed_ids, get_graph
    except Exception:
        return {"law": [], "case": []}

    if not GRAPH_RAG_ENABLED:
        return {"law": [], "case": []}

    graph = get_graph()
    if not graph.is_available or graph.n_nodes == 0:
        return {"law": [], "case": []}

    seeds = extract_seed_ids([r["title"] for r in current_refs])
    if not seeds:
        return {"law": [], "case": []}

    hits = graph.expand(seeds, hops=2, max_nodes=10)
    laws: list[Citation] = []
    cases: list[Citation] = []
    existing_ids = {r["source_id"] for r in current_refs}

    for hit in hits:
        node = hit.node
        if node.node_id in existing_ids:
            continue
        if node.node_type == "law":
            laws.append(Citation(
                source_id=node.node_id,
                doc_type="law",
                title=node.label,
                snippet="(graph-derived, snippet için Qdrant lookup gerek)",
                url="",
                score=hit.score * 0.5,  # graph-derived skoru düşür
            ))
        elif node.node_type == "case":
            cases.append(Citation(
                source_id=node.node_id,
                doc_type="case",
                title=node.label,
                snippet="(graph-derived)",
                url="",
                score=hit.score * 0.5,
            ))

    return {"law": laws[:3], "case": cases[:3]}


def _dedupe_by_id(refs: list[Citation]) -> list[Citation]:
    """source_id bazında dedupe — ilk görünen kalır."""
    seen: set[str] = set()
    out: list[Citation] = []
    for r in refs:
        if r["source_id"] in seen:
            continue
        seen.add(r["source_id"])
        out.append(r)
    return out


def _format_title(r) -> str:
    """SearchResult → kompakt başlık."""
    kod = r.metadata.get("kanun_kodu", "")
    madde = r.metadata.get("madde_no", "")
    if kod and madde:
        return f"{kod} Madde {madde}"
    court = r.metadata.get("court", "")
    esas = r.metadata.get("esas_no", "")
    karar = r.metadata.get("karar_no", "")
    if court and esas and karar:
        return f"{court} {esas}/{karar}"
    return r.metadata.get("title") or r.chunk_id


__all__ = ("CRAG_ENABLED", "crag_node")
