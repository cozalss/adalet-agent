"""Offline ETL: Qdrant'taki tüm mevzuat + emsal chunk'larından LegalGraph üret.

Akış:
  1. Qdrant'tan tüm chunk payload'larını scroll et
  2. doc_type=='law' → LawNode (kanun_kodu + madde_no payload'tan)
  3. doc_type=='case' → CaseNode (court + esas_no + karar_no payload'tan)
     + chunk metninden _LAW_ID_RE ile geçen madde referanslarını çıkar
     → CITES edge (case → law)
  4. Domain alanı → ConceptNode + GOVERNS/DISCUSSES edge
  5. data/graph/legal_graph.json olarak yaz

Çalıştır:
    uv run python -m scripts.build_graph

ENV:
    GRAPH_PATH=data/graph/legal_graph.json
    SCROLL_LIMIT=10000
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys

import structlog

# Windows: pyarrow'u torch'tan önce yükle — build_graph lazy import'la
# graph_rag/embedder'ı çekiyor, torch sonrası segfault yapar.
from core import native_preload  # noqa: F401

# UTF-8 zorla (Windows cp1254)
with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

log = structlog.get_logger()

SCROLL_LIMIT = int(os.getenv("SCROLL_LIMIT", "10000"))
SCROLL_BATCH = 256


async def build_graph_from_qdrant() -> None:

    from retrieval.graph_rag import LegalGraph, extract_seed_ids
    from retrieval.vector_store import COLLECTION_NAME, get_client

    print("=" * 70)
    print(" GRAPHRAG OFFLINE BUILDER")
    print("=" * 70)

    graph = LegalGraph()
    if not graph.is_available:
        print("[XX] networkx yok — `uv add networkx`")
        return

    client = get_client()
    try:
        # Collection var mı?
        cols = await client.get_collections()
        if not any(c.name == COLLECTION_NAME for c in cols.collections):
            print(f"[XX] Collection yok: {COLLECTION_NAME}")
            return

        total = (await client.count(collection_name=COLLECTION_NAME, exact=True)).count
        print(f"[OK] Collection: {COLLECTION_NAME} ({total} chunk)")

        n_law = n_case = n_cites = 0
        n_concept = 0
        seen_concepts: set[str] = set()

        offset = None
        scanned = 0
        while scanned < SCROLL_LIMIT:
            points, offset = await client.scroll(
                collection_name=COLLECTION_NAME,
                limit=SCROLL_BATCH,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                break

            for p in points:
                payload = p.payload or {}
                doc_type = payload.get("doc_type")
                domain = payload.get("domain", "")
                text = payload.get("text", "")

                # Law node
                if doc_type == "law" or payload.get("source") == "mevzuat":
                    kanun = payload.get("kanun_kodu")
                    madde = payload.get("madde_no")
                    if kanun and madde:
                        law_id = graph.add_law(str(kanun), int(madde))
                        n_law += 1
                        if domain:
                            concept_id = graph.add_concept(domain)
                            if domain not in seen_concepts:
                                seen_concepts.add(domain)
                                n_concept += 1
                            graph.link(law_id, concept_id, "governs", weight=1.0)

                # Case node
                elif doc_type == "case" or payload.get("source") in {
                    "anayasa", "yargitay", "danistay", "bedesten",
                }:
                    court = payload.get("court") or payload.get("source") or "Yargıtay"
                    esas = payload.get("esas_no")
                    karar = payload.get("karar_no")
                    # Eski seed: esas/karar yok, doc_id var ("am-2022/64129" gibi).
                    # doc_id'yi parse et: "am-YYYY/NUM" → esas=YYYY, karar=NUM
                    if not (esas and karar):
                        doc_id = payload.get("doc_id", "")
                        if isinstance(doc_id, str) and "/" in doc_id:
                            left, _, karar_part = doc_id.rpartition("/")
                            # "am-2022" → "2022"; "y-9HD-2019" → "2019"
                            esas_part = left.split("-")[-1] if "-" in left else left
                            if esas_part and karar_part:
                                esas, karar = esas_part, karar_part
                    if esas and karar:
                        case_id = graph.add_case(str(court), str(esas), str(karar))
                        n_case += 1
                        # Karar metninde geçen madde referanslarını çıkar
                        seeds = extract_seed_ids([text[:3000]])
                        for sid in seeds:
                            if sid.startswith("law:"):
                                # law node yoksa otomatik ekle
                                parts = sid.split(":")
                                if len(parts) == 3:
                                    graph.add_law(parts[1], int(parts[2]))
                                    graph.link(case_id, sid, "cites", weight=1.0)
                                    n_cites += 1
                        if domain:
                            concept_id = graph.add_concept(domain)
                            if domain not in seen_concepts:
                                seen_concepts.add(domain)
                                n_concept += 1
                            graph.link(case_id, concept_id, "discusses", weight=1.0)

            scanned += len(points)
            print(f"  scanned={scanned} laws={n_law} cases={n_case} cites={n_cites}")
            if offset is None:
                break

        print(
            f"[OK] Graph: {graph.n_nodes} node, {graph.n_edges} edge "
            f"(law={n_law} case={n_case} cites={n_cites} concept={n_concept})",
        )
        graph.save()
        print(f"[OK] Yazildi: {os.getenv('GRAPH_PATH', 'data/graph/legal_graph.json')}")
    finally:
        await client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(build_graph_from_qdrant()) or 0)
