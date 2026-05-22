"""Retrieval modülü — RAG pipeline'ı.

Public API:
    search(question, top_k=5, domain=None) → list[SearchResult]
    verify_claim(claim) → VerifyResult
"""

from .citation import (
    CitationClaim,
    VerifyResult,
    VerifyStatus,
    parse_citation,
    verify_claim,
)
from .hybrid_search import SearchResult, search

__all__ = [
    "search",
    "SearchResult",
    "verify_claim",
    "parse_citation",
    "CitationClaim",
    "VerifyResult",
    "VerifyStatus",
]
