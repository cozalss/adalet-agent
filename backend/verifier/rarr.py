"""RARR-lite — Retrofit Attribution + Revision (Sprint-4 W4.2).

Referans: Gao et al. 2022 "RARR: Researching and Revising What Language Models
Say" (arxiv:2210.08726). Tam RARR çift-LLM pipeline'ı; bu modül RARR-LITE:
sadece 'attribution check + evidence augmentation' kısmı, revision yok.

Sorun: verify katmanları (fuzzy, NLI, LettuceDetect) cevap-ile-snippet
uyumunu ölçer. Ancak retrieval EKSİK kanıt getirmişse (örn. ilgili kanun
maddesi top-K'da yok), claim hatalı-reject edilir. RARR-lite bu durumu
ÖZEL ek arama ile zenginleştirir:

    1. Verify-edilemeyen claim (l1=ok ama l2<threshold) için claim metnini
       arama sorgusu olarak kullan
    2. Hibrit retrieval ile 3 ek snippet çek (sadece bu claim için)
    3. State'in mevzuat/emsal refs'ine ekle — verify_node bir sonraki
       iterasyonda yeni snippet'lerle daha doğru ölçer

Default-safe: ENV `RARR_ENABLED=0` → augment_evidence_batch no-op.

Mevcut RARR'dan farklar:
- LLM 'attribution query generator' yok (claim metni direkt query)
- Revision adımı yok (claim'i değiştirmiyoruz, sadece evidence ekliyoruz)
- Verify-loop ile değil, verify_node içinde tek seferlik augment
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal

import structlog

if TYPE_CHECKING:
    from agents.state import Citation, Claim

log = structlog.get_logger()

RARR_ENABLED = os.getenv("RARR_ENABLED", "0").lower() in {"1", "true", "yes"}
RARR_TOP_K = int(os.getenv("RARR_TOP_K", "3"))
RARR_MAX_CLAIMS = int(os.getenv("RARR_MAX_CLAIMS", "5"))


async def augment_evidence_batch(
    claims: list[Claim], refs: list[Citation],
) -> int:
    """Verify-edilemeyen claim'ler için ek snippet çek + refs'e ekle.

    Args:
        claims: state['claims'] — verify edilecek liste
        refs: state['mevzuat_refs'] + state['emsal_refs'] (mutate edilir)

    Returns:
        Eklenen snippet sayısı (0 ise no-op).

    Strateji:
        - claim'in cite_ids'i varsa zaten kanıt mevcut, atla
        - cite_ids YOK olan ilk N (RARR_MAX_CLAIMS) claim için hibrit search
        - Sonuçları Citation formatına çevir, dedup (source_id) ile refs'e ekle
    """
    if not RARR_ENABLED or not claims:
        return 0

    # Sprint-4 W4.2: lazy import — hybrid_search modülünü import edip
    # circular gerekmez (verify_node bunu çağırır, hybrid_search bağımsız).
    try:
        from retrieval.hybrid_search import search
    except ImportError as exc:
        log.warning("rarr_hybrid_search_unavailable", error=str(exc))
        return 0

    existing_ids = {r["source_id"] for r in refs}
    n_added = 0
    n_processed = 0

    for claim in claims:
        if n_processed >= RARR_MAX_CLAIMS:
            break
        cite_ids = claim.get("cite_ids", []) or []
        # cite_ids dolu ise zaten kanıt var; atla
        if cite_ids:
            continue
        claim_text = claim.get("text", "").strip()
        if len(claim_text) < 30:
            continue

        n_processed += 1
        try:
            results = await search(question=claim_text, top_k=RARR_TOP_K)
        except Exception as exc:
            log.warning("rarr_search_failed", error=str(exc), claim=claim_text[:80])
            continue

        for r in results:
            if r.chunk_id in existing_ids:
                continue
            existing_ids.add(r.chunk_id)
            # Citation TypedDict formatına çevir
            doc_type: Literal["law", "case"] = "law" if (
                r.metadata.get("doc_type") == "law" or r.source == "mevzuat"
            ) else "case"
            new_cite: Citation = {
                "source_id": r.chunk_id,
                "doc_type": doc_type,
                "title": _format_title(r),
                "snippet": r.text[:500],
                "url": r.source_url,
                "score": float(r.score),
            }
            refs.append(new_cite)
            n_added += 1

    if n_added:
        log.info("rarr_augmented", n_added=n_added, n_processed=n_processed)
    return n_added


def _format_title(sr: object) -> str:
    """SearchResult'tan kompakt başlık."""
    meta = getattr(sr, "metadata", None) or {}
    kod = meta.get("kanun_kodu") or meta.get("court", "")
    madde = meta.get("madde_no") or meta.get("esas_no", "")
    if kod and madde:
        return f"{kod} {madde}"
    title = meta.get("title")
    if title:
        return str(title)
    source = getattr(sr, "source", None)
    if source:
        return str(source)
    chunk_id = getattr(sr, "chunk_id", "")
    return str(chunk_id)


__all__ = ("RARR_ENABLED", "RARR_TOP_K", "augment_evidence_batch")
