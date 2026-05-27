"""HyDE (Hypothetical Document Embeddings) — query expansion.

Klasik dense retrieval problemi: kullanıcı sorusu kısa ve soru formatında,
ama dokümanlar uzun ve cevap formatında. Embedding uzayı arasında boşluk var.

HyDE fikri (Gao et al. 2022, https://arxiv.org/abs/2212.10496):
  1. LLM'e "bu sorunun cevabı 2-3 cümle olarak nasıl yazılırdı?" diye sor
  2. Bu HİPOTETİK cevabı embed et
  3. Hipotetik cevap dokümanlara daha yakın → daha iyi retrieval

Türkçe hukuk için ek değer: vatandaş "depozitomu vermiyor" gibi yazıyor,
kanun "kiracının verdiği güvence bedeli" diye yazılı — HyDE bu boşluğu kapatır.

Türkçe hukuk uyarlaması:
  - HyDE prompt'una `domain` ipucu ver (domain'i bilen LLM doğru jargon kullansın)
  - Hipotetik cevapta uydurma madde no yazma — sadece kavramsal cevap
  - Mevcut hybrid_search'ün dense kolu HyDE embedding ile değiştirilir,
    sparse (BM25) kolu orijinal soruda kalır (anahtar kelime önemli)
"""

from __future__ import annotations

import structlog
from qdrant_client import models

from agents.llm import ChatMessage, get_llm
from retrieval.hybrid_search import SearchResult, _get_embedder, _to_result
from retrieval.vector_store import COLLECTION_NAME, get_client

log = structlog.get_logger()

HYDE_SYSTEM = (
    "Sen Türk hukuku bilen bir asistansın. Vatandaşın sorusuna 2-3 cümle "
    "olarak kavramsal, jargon-doğru hipotetik bir cevap yaz. AMACIN bilgi "
    "vermek değil, bir 'arama tohum'u üretmek — bu metin embedding'i için "
    "kullanılacak. Madde numarası veya karar referansı UYDURMA. Sadece "
    "ilgili hukuk dilini kullan (örn. 'kefalet', 'cayma hakkı', 'kıdem')."
)

HYDE_USER_TEMPLATE = (
    "Hukuk alanı: {domain}\n"
    "Soru: {question}\n\n"
    "Yukarıdaki soruya 2-3 cümle hipotetik bir hukuki cevap yaz (numara verme):"
)


async def generate_hypothetical(
    question: str, domain: str | None = None, max_tokens: int = 200,
) -> str:
    """Soru → hipotetik 2-3 cümlelik cevap (HyDE tohum metni)."""
    llm = get_llm()
    user_msg = HYDE_USER_TEMPLATE.format(
        domain=domain or "genel hukuk", question=question,
    )
    response = await llm.chat(
        messages=[
            ChatMessage(role="system", content=HYDE_SYSTEM),
            ChatMessage(role="user", content=user_msg),
        ],
        temperature=0.3,         # biraz yaratıcılık iyi (daha geniş ara)
        max_tokens=max_tokens,
        json_mode=False,
    )
    text = response.content.strip()
    log.info("hyde_generated", domain=domain, hypo_len=len(text))
    return text


async def search_with_hyde(
    question: str,
    *,
    top_k: int = 10,
    prefetch_limit: int = 50,
    domain: str | None = None,
    qdrant_domain: str | None = None,
) -> list[SearchResult]:
    """Hybrid search ama dense kolu HyDE hipotetik metnine göre embed edilir.

    Sparse (BM25) kolu orijinal soruda — anahtar kelimeler kritik.
    Reranker bunun üstüne eklenebilir (search_with_rerank pattern ile).

    Args:
        question: vatandaşın orijinal sorusu
        domain: HyDE prompt'una verilecek hukuk alanı ipucu (LLM jargon için)
        qdrant_domain: Qdrant payload filter (None = tüm domainler)
    """
    if not question.strip():
        return []

    # 1) HyDE hipotetik metin üret (LLM)
    hypo = await generate_hypothetical(question, domain=domain)
    if not hypo:
        # Fallback: mevcut hybrid_search
        from retrieval.hybrid_search import search
        return await search(question=question, top_k=top_k, domain=qdrant_domain)

    # 2) Tek batch encoding (iki ayrı forward yerine bir forward + to_thread):
    #    - dense: hipotetik metnin embedding'i (HyDE tohumu) → out[0]
    #    - sparse: orijinal sorunun BM25 (keyword için orijinal şart) → out[1]
    embedder = _get_embedder()
    out = await embedder.aencode([hypo, question])
    hypo_dense = out.dense[0]
    sparse_idx, sparse_val = out.sparse[1]

    query_filter = None
    if qdrant_domain:
        query_filter = models.Filter(must=[
            models.FieldCondition(key="domain",
                                  match=models.MatchValue(value=qdrant_domain))
        ])

    # 3) Qdrant hybrid query (RRF fusion)
    client = get_client()
    try:
        result = await client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=[
                models.Prefetch(query=hypo_dense, using="dense",
                                limit=prefetch_limit, filter=query_filter),
                models.Prefetch(query=models.SparseVector(indices=sparse_idx,
                                                         values=sparse_val),
                                using="sparse",
                                limit=prefetch_limit, filter=query_filter),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=top_k,
            with_payload=True,
        )
    finally:
        await client.close()

    return [_to_result(p) for p in result.points]
