"""Hybrid search — BGE-M3 dense + sparse (+ opsiyonel ColBERT), Qdrant RRF fusion.

Sprint-4 ile 3-kol prefetch desteği eklendi:
  1. dense        (BGE-M3 1024-d cosine)
  2. sparse       (BM25 IDF)
  3. colbert      (token MAX_SIM late-interaction)   — opsiyonel

Run-time'da collection ColBERT vec içeriyorsa 3-kol; yoksa 2-kol çalışır.
Caller hiç değişiklik yapmadan eski API ile çalışır.

Tek public fonksiyon:
    search(question, top_k=5, domain=None) → list[SearchResult]

Cross-encoder rerank için:
    search_with_rerank(question, top_k=5, candidates_n=50, domain=None)
        → list[RerankResult]

Performans hedefi: < 700 ms tek sorgu (embed + Qdrant + payload, ColBERT açık).
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

import structlog
from qdrant_client import models

from .embedding import Embedder, MursitEmbedder, get_embedder
from .mevzuat_urls import normalize_mevzuat_url
from .reranker import RerankResult, get_reranker
from .vector_store import COLLECTION_NAME, collection_has_colbert, get_shared_client

log = structlog.get_logger()

# Run-time ColBERT toggle — false ise schema'da olsa bile sorguda kullanma
COLBERT_QUERY_ENABLED = os.getenv("COLBERT_QUERY_ENABLED", "1").lower() in {"1", "true", "yes"}


@dataclass(slots=True)
class SearchResult:
    chunk_id: str
    score: float
    text: str
    source: str
    source_url: str
    domain: str
    metadata: dict[str, Any]


_embedder_singleton: Embedder | MursitEmbedder | None = None
_sparse_embedder_singleton: Embedder | None = None
_colbert_supported_cache: bool | None = None

# Dual embedder: Mursit dense (768-dim kaliteli) + BGE-M3 sparse (BM25 keyword)
# SPARSE_EMBEDDER_MODEL env ile ayrı sparse model belirtilir.
# Varsayılan: EMBEDDING_MODEL ile aynı (single-model mode).
_SPARSE_MODEL = os.getenv("SPARSE_EMBEDDER_MODEL", "")

# A/B verisi (v2 186 vaka, 2026-05-30): Mursit dense-only ile karşılaştırma:
#   vergi: BGE-M3 90.9% → Mursit 45.5% (-45pp) ← BM25 kritik
#   trafik: BGE-M3 81.8% → Mursit 54.5% (-27pp) ← BM25 kritik
#   icra:   BGE-M3 73.1% → Mursit 73.1% (=) ← BM25 nötr
#   kira:   BGE-M3 78.8% → Mursit 97.0% (+18pp) ← Mursit semantic üstün
# SPARSE_ENABLED_DOMAINS: bu domainlerde BGE-M3 sparse de aktif (dual mode)
_SPARSE_DOMAINS: frozenset[str] = frozenset(
    os.getenv("SPARSE_ENABLED_DOMAINS", "vergi,trafik,icra").split(",")
) if _SPARSE_MODEL else frozenset()

# Füzyon stratejisi (Context7/Qdrant best-practice): RRF (rank-tabanlı, DEFAULT) veya DBSF
# (Distribution-Based Score Fusion, Qdrant 1.10+ — skorları mean±3σ ile normalize edip toplar;
# farklı skor-DAĞILIMLI sparse+dense kollarını birleştirmede RRF'den robust). Tek-kol
# (dense-only Mursit) → DBSF anlamsız, RRF kalır; yalnız sparse-enabled domainde (2 kol) tetiklenir.
#
# ÖLÇÜLDÜ A/B (2026-06-04, eval_run v2 186 vaka, law, eval/runs/fusion_{rrf,dbsf}.json):
#   headline madde_recall@5 35.4%→35.7% (FLAT), madde_mrr 0.294→0.297 (FLAT),
#   domain@5 95.7→95.2 / kanun@5 82.8→82.3 (-0.5pp), AMA sparse-domain domain@1:
#   trafik 27.3→45.5% (+18pp, BM25 ölçek-normalizasyonu), icra 92.3→96.2% (+4pp), vergi =.
# Karar: DEFAULT RRF (headline kazancı yok); DBSF opt-in (trafik/icra ağırlıklı dağıtım).
# RRF_K Qdrant native FusionQuery'de expose EDİLMİYOR → sweep N/A (yalnız multi_query manual RRF'te).
_HYBRID_FUSION = os.getenv("HYBRID_FUSION", "rrf").strip().lower()


def _fusion_for(n_prefetch: int) -> models.Fusion:
    """≥2 prefetch (sparse+dense) varken HYBRID_FUSION=dbsf → DBSF; aksi halde RRF."""
    if _HYBRID_FUSION == "dbsf" and n_prefetch >= 2:
        return models.Fusion.DBSF
    return models.Fusion.RRF


async def maybe_dual_sparse(
    question: str, sparse_idx: list, sparse_val: list, sparse_domain: str | None,
) -> tuple[list, list]:
    """Mursit dense-only'de sparse BOŞken + domain BM25-kritikse (SPARSE_ENABLED_DOMAINS)
    BGE-M3 ile sparse vektörünü al; aksi halde değiştirmeden döner.

    vergi/trafik/icra: BGE-M3 sparse +27-45pp domain@1. search() VE search_with_hyde() bu
    helper'ı PAYLAŞIR (DRY) → HyDE yolu da sparse-kritik domainlerde BM25'i kaybetmez
    (denetim 2026-06-04: HyDE dense-only çalışıp vergi'de -45pp BM25 kaybı yaşıyordu)."""
    if sparse_idx or not _SPARSE_MODEL:
        return sparse_idx, sparse_val
    if sparse_domain and sparse_domain in _SPARSE_DOMAINS:
        _, (sparse_idx, sparse_val), _ = await _get_sparse_embedder().aencode_query(question)
        log.debug("dual_sparse_activated", domain=sparse_domain)
    return sparse_idx, sparse_val


def _get_embedder() -> Embedder | MursitEmbedder:
    """EMBEDDING_MODEL env'e göre doğru embedder singleton döndür."""
    global _embedder_singleton
    if _embedder_singleton is None:
        _embedder_singleton = get_embedder()
    return _embedder_singleton


def _get_sparse_embedder() -> Embedder | MursitEmbedder:
    """Sparse için ayrı embedder (dual mode) ya da ana embedder (single mode).

    SPARSE_EMBEDDER_MODEL=BAAI/bge-m3 ile BGE-M3 sparse kullanılır.
    Boşsa ana embedder kullanılır.

    PAYLAŞIM (2026-06-10, icra teşhisi): model colbert-rerank modeliyle AYNI ise
    (ikisi de BAAI/bge-m3) colbert'in CPU instance'ı yeniden kullanılır — ekstra
    VRAM/RAM yok. Demo sparse'ı GPU-sığdırma için kapatmıştı (vergi/trafik/icra'da
    ölçülmüş +27-45pp BM25 kazancı kayıptı); paylaşımla sparse yalnız sorgu-encode
    maliyetiyle (CPU ~50ms) geri açılabilir — corpus sparse vektörleri zaten seed'li.
    """
    global _sparse_embedder_singleton
    if not _SPARSE_MODEL:
        return _get_embedder()
    if _sparse_embedder_singleton is None:
        colbert_model = os.getenv("COLBERT_RERANK_MODEL", "BAAI/bge-m3")
        if colbert_model == _SPARSE_MODEL:
            _sparse_embedder_singleton = _get_colbert_embedder()
        else:
            _sparse_embedder_singleton = Embedder(_SPARSE_MODEL)
    return _sparse_embedder_singleton


_colbert_embedder_singleton: Embedder | None = None


def _get_colbert_embedder() -> Embedder:
    """ColBERT-rerank için DEDICATED BGE-M3 (compute_score multi-vector).

    Sparse-retrieval'dan AYRI (SPARSE_EMBEDDER_MODEL'e bağlı değil) — demo BGE-M3 sparse'ı
    GPU-OOM için kapatsa bile colbert-rerank çalışır. Default CPU (COLBERT_RERANK_DEVICE):
    Qwen GPU'yu doldurur → BGE-M3 (~2GB) CPU'da, OOM yok; rerank ~30 aday → kabul edilebilir
    latency. Singleton (bir kez yüklenir)."""
    global _colbert_embedder_singleton
    if _colbert_embedder_singleton is None:
        model = os.getenv("COLBERT_RERANK_MODEL", "BAAI/bge-m3")
        device = os.getenv("COLBERT_RERANK_DEVICE", "cpu").strip().lower()
        _colbert_embedder_singleton = Embedder(model, device=device)
    return _colbert_embedder_singleton


async def _detect_colbert_support(client) -> bool:
    """Bir kez kontrol et + cache'le; her sorguda Qdrant'a sormak istemiyoruz."""
    global _colbert_supported_cache
    if _colbert_supported_cache is None:
        _colbert_supported_cache = await collection_has_colbert(client)
    return _colbert_supported_cache


def _reset_colbert_cache() -> None:
    """Test/migration sonrası reset."""
    global _colbert_supported_cache
    _colbert_supported_cache = None


async def search(
    question: str,
    top_k: int = 5,
    prefetch_limit: int = 50,
    domain: str | None = None,
    kanun_kodu: list[str] | None = None,
    source: list[str] | None = None,
    sparse_domain: str | None = None,
    doc_type: str | list[str] | None = None,
) -> list[SearchResult]:
    """Hybrid search — dense + sparse (+ ColBERT) prefetch, RRF fusion, top_k.

    Args:
        question: Kullanıcı sorusu.
        top_k: Döndürülecek sonuç sayısı.
        prefetch_limit: Her vektör için ilk aşamada çekilecek aday sayısı.
        domain: Filtre — None ise tüm domainler (Qdrant payload domain filtresi).
        kanun_kodu: Filtre — verilirse yalnız bu kanun kodlarındaki law chunk'ları.
        source: Filtre — verilirse yalnız bu source'lardaki chunk'lar.
        sparse_domain: Dual embedder domain hint — Qdrant filtresi değil, sadece
            hangi domain için BGE-M3 sparse kullanılacağını belirler.
            vergi/trafik/icra için BGE-M3 sparse domain@1'i +27-45pp iyileştiriyor.
    """
    if not question.strip():
        return []

    # Paylaşılan client — kapatma (process-ömürlü singleton).
    client = get_shared_client()
    colbert_supported = await _detect_colbert_support(client)
    want_colbert = COLBERT_QUERY_ENABLED and colbert_supported

    embedder = _get_embedder()
    # to_thread: BGE-M3/Mursit forward CPU/GPU-bound — event loop'u bloke etme.
    dense_vec, (sparse_idx, sparse_val), colbert_vecs = await embedder.aencode_query(
        question, return_colbert=want_colbert,
    )

    # Dual embedder (paylaşılan helper): Mursit dense-only + sparse-kritik domain → BGE-M3 sparse.
    # vergi/trafik/icra +27-45pp; idari/tuketici/kira'da sparse zaten devre dışı (regresyon önlenir).
    sparse_idx, sparse_val = await maybe_dual_sparse(
        question, sparse_idx, sparse_val, sparse_domain or domain)

    query_filter = _build_filter(domain, kanun_kodu, source, doc_type)

    # Mursit dense-only: sparse boşsa BM25 prefetch atla (dim uyumsuzluğu önler)
    has_sparse = bool(sparse_idx)
    prefetch_list: list[models.Prefetch] = [
        models.Prefetch(
            query=dense_vec,
            using="dense",
            limit=prefetch_limit,
            filter=query_filter,
        ),
    ]
    if has_sparse:
        prefetch_list.append(
            models.Prefetch(
                query=models.SparseVector(indices=sparse_idx, values=sparse_val),
                using="sparse",
                limit=prefetch_limit,
                filter=query_filter,
            )
        )
    if want_colbert and colbert_vecs:
        prefetch_list.append(
            models.Prefetch(
                query=colbert_vecs,  # multi-vector list[list[float]]
                using="colbert",
                limit=prefetch_limit,
                filter=query_filter,
            )
        )

    result = await client.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=prefetch_list,
        query=models.FusionQuery(fusion=_fusion_for(len(prefetch_list))),
        limit=top_k,
        with_payload=True,
    )

    return [_to_result(point) for point in result.points]


async def search_with_rerank(
    question: str,
    top_k: int = 5,
    candidates_n: int = 50,
    domain: str | None = None,
    doc_type: str | list[str] | None = None,
) -> list[RerankResult]:
    """İki aşamalı pipeline: hybrid → cross-encoder rerank → top_k.

    Args:
        question: Kullanıcı sorusu.
        top_k: Final sonuç sayısı (varsayılan 5).
        candidates_n: Reranker'a gönderilecek aday sayısı (varsayılan 50).
        domain: Filtre — None ise tüm domainler.

    Returns:
        Cross-encoder relevance score'a göre sıralanmış RerankResult listesi.
    """
    candidates = await search(
        question=question,
        top_k=candidates_n,
        prefetch_limit=candidates_n,
        domain=domain,
        doc_type=doc_type,
    )
    if not candidates:
        return []

    # context7 SOTA lever: BGE-M3 multi-vector (dense+sparse+ColBERT) rerank — cross-encoder
    # doğru kanunu buluyor (kanun@5=82%) ama doğru MADDE'yi seçemiyor (madde@5=37%); ColBERT
    # token-level MAX_SIM ince madde-ayrımı için. Opt-in: RERANK_PROVIDER=bgem3 (default local).
    # YALNIZ doc_type='law': ColBERT yan koleksiyonu law-only seed'li (seed_law_colbert) →
    # law-dışı havuzda (emsal doc_type=None) stored MAX_SIM 0 hit verir ve "bulunamadı →
    # orijinal sırada geçir" fallback'i TÜM havuzu rerank'sız geçirirdi (sessiz bypass,
    # öncelik #2 2026-06-10). Law-dışı havuzlar cross-encoder'a düşer (gerçek rerank +
    # EMSAL_LIVE_TRIGGER_SCORE eşiği CE skor ölçeğinde kalibre).
    if doc_type == "law" and colbert_rerank_enabled():
        try:
            return await colbert_rerank_candidates(question, candidates, top_k)
        except Exception as exc:  # BGE-M3 yük/skor hatası → graceful: cross-encoder'a düş
            log.warning("colbert_rerank_failed_fallback_ce", error=str(exc) or type(exc).__name__)

    reranker = get_reranker()
    return await asyncio.to_thread(reranker.rerank, question, candidates, top_k)


_COLBERT_COLLECTION = os.getenv("COLBERT_COLLECTION", "adalet_law_colbert")
_colbert_stored_cache: bool | None = None


async def _stored_colbert_available(client) -> bool:
    """Yan colbert collection (seed_law_colbert) var mı? Bir kez kontrol + cache."""
    global _colbert_stored_cache
    if _colbert_stored_cache is None:
        try:
            _colbert_stored_cache = await client.collection_exists(_COLBERT_COLLECTION)
        except Exception:
            _colbert_stored_cache = False
    return _colbert_stored_cache


def _rr_from(c: object, score: float) -> RerankResult:
    """SearchResult|RerankResult + skor → RerankResult (ikisi de aynı alanları taşır)."""
    return RerankResult(
        chunk_id=c.chunk_id, score=float(score), text=c.text, source=c.source,  # type: ignore[attr-defined]
        source_url=c.source_url, domain=c.domain, metadata=c.metadata,  # type: ignore[attr-defined]
        original_score=getattr(c, "original_score", c.score),  # type: ignore[attr-defined]
    )


async def colbert_rerank_candidates(
    question: str, candidates: list, top_k: int,
) -> list[RerankResult]:
    """BGE-M3 ColBERT multi-vector rerank (ince madde-ayrımı, +5.2pp eval). İKİ yol:
    - STORED (HIZLI, default): yan colbert collection'da Qdrant MAX_SIM — passage-forward YOK,
      yalnız sorgu-colbert encode (1 forward) → deployable (~27s→~13s). seed_law_colbert kurar.
    - COMPUTE (fallback): BGE-M3 compute_score (passage'ları her sorguda encode → CPU'da yavaş).
    search_with_rerank + mevzuat_node PAYLAŞIR. RERANK_SCORE_MIN uygulanmaz (farklı dağılım);
    sadece reorder (downstream verify aynen). Adaylar SearchResult|RerankResult olabilir."""
    if os.getenv("COLBERT_RERANK_MODE", "stored").lower() != "compute":
        client = get_shared_client()
        if await _stored_colbert_available(client):
            try:
                return await _colbert_rerank_qdrant(question, candidates, top_k, client)
            except Exception as exc:  # Qdrant/colbert hatası → compute fallback
                log.warning("colbert_qdrant_failed_fallback_compute", error=str(exc) or type(exc).__name__)
    return await _colbert_rerank_compute(question, candidates, top_k)


async def _colbert_rerank_qdrant(question, candidates, top_k, client) -> list[RerankResult]:
    """Stored colbert (yan collection) → Qdrant MAX_SIM rerank. Yalnız SORGU-colbert encode
    (1 forward); passage colbert'leri önceden saklı → hızlı. candidate chunk_id'lerine filtreli."""
    emb = _get_colbert_embedder()
    # Modeli ANA thread'de yükle (Windows native access-violation guard — bkz. embedding.py:107).
    # encode_query'yi to_thread'e atmadan önce şart; aencode* wrapper'ları bunu yapar ama burada
    # sync encode_query doğrudan to_thread'e veriliyor → guard elle eklenir (code-review 2026-06-18).
    emb.ensure_loaded()
    _, _, q_colbert = await asyncio.to_thread(emb.encode_query, question, True)  # return_colbert
    if not q_colbert:
        raise ValueError("sorgu colbert vektörü boş")
    by_chunk = {c.chunk_id: c for c in candidates}
    hits = await client.query_points(
        collection_name=_COLBERT_COLLECTION, query=q_colbert, using="colbert",
        query_filter=models.Filter(must=[models.FieldCondition(
            key="chunk_id", match=models.MatchAny(any=list(by_chunk.keys())))]),
        limit=max(top_k, len(by_chunk)), with_payload=["chunk_id"],
    )
    hit_scores: list[tuple[object, float]] = []
    seen: set[str] = set()
    for h in hits.points:
        cid = (h.payload or {}).get("chunk_id")
        c = by_chunk.get(cid)
        if c is not None and cid not in seen:
            seen.add(cid)
            hit_scores.append((c, float(h.score)))
    if _colbert_fuse_hybrid() and len(hit_scores) > 1:
        # dense+sparse sinyalini geri kat (stored pure-colbert'in eksiği): candidate'ın hybrid
        # (RRF) skoru + colbert MAX_SIM'i min-max normalize edip ağırlıklı topla → weighted'e
        # yaklaş (40.9→~42 hedefi), HIZLI kalır (ekstra forward yok). Opt-in COLBERT_FUSE_HYBRID.
        cb = [s for _, s in hit_scores]
        hy = [float(getattr(c, "original_score", c.score)) for c, _ in hit_scores]
        ncb, nhy = _minmax(cb), _minmax(hy)
        w = _colbert_fuse_weight()
        fused = [(hit_scores[i][0], w * ncb[i] + (1.0 - w) * nhy[i]) for i in range(len(hit_scores))]
        fused.sort(key=lambda cs: cs[1], reverse=True)
        ranked = [_rr_from(c, s) for c, s in fused]
    else:
        ranked = [_rr_from(c, s) for c, s in hit_scores]
    # Yan collection'da olmayan aday (ör. law-dışı/yeni) → orijinal sırada sona ekle (recall korunur).
    for c in candidates:
        if c.chunk_id not in seen:
            seen.add(c.chunk_id)
            ranked.append(_rr_from(c, getattr(c, "original_score", c.score)))
    return ranked[:top_k]


def _minmax(xs: list[float]) -> list[float]:
    lo, hi = min(xs), max(xs)
    return [(x - lo) / (hi - lo) if hi > lo else 0.5 for x in xs]


def _colbert_fuse_hybrid() -> bool:
    """Stored colbert MAX_SIM'i candidate hybrid skoruyla füzyonla (dense+sparse geri-kat). Opt-in."""
    return os.getenv("COLBERT_FUSE_HYBRID", "0").lower() in {"1", "true", "yes"}


def _colbert_fuse_weight() -> float:
    """Füzyonda colbert ağırlığı (kalan = hybrid). COLBERT_FUSE_WEIGHT, default 0.5."""
    try:
        return float(os.getenv("COLBERT_FUSE_WEIGHT", "0.5"))
    except (ValueError, TypeError):
        return 0.5


async def _colbert_rerank_compute(question, candidates, top_k) -> list[RerankResult]:
    """compute_score fallback — passage'ları HER sorguda encode (CPU'da yavaş; stored yoksa).
    Boş/whitespace metin compute_score'a verilmez (near-zero distorsiyon) → en sona."""
    emb = _get_colbert_embedder()
    pairs = [(c, c.text.strip()) for c in candidates]
    scored: list[tuple[object, float]] = []
    nonempty = [(c, t) for c, t in pairs if t]
    if nonempty:
        emb.ensure_loaded()  # ana-thread yükleme (Windows guard) — rerank_scores to_thread'e gitmeden
        scores = await asyncio.to_thread(
            emb.rerank_scores, question, [t for _, t in nonempty], _colbert_weights(),
        )
        scored.extend((c, s) for (c, _), s in zip(nonempty, scores, strict=True))
    scored.extend((c, -1.0) for c, t in pairs if not t)
    scored.sort(key=lambda cs: cs[1], reverse=True)
    return [_rr_from(c, s) for c, s in scored[:top_k]]


def colbert_rerank_enabled() -> bool:
    """RERANK_PROVIDER=bgem3|colbert → BGE-M3 multi-vector rerank (opt-in, default local CE).

    Modül-sabiti DEĞİL bilinçli (call-time getenv): eval her config'i ayrı subprocess'te
    farklı env ile koşuyor + testler monkeypatch ediyor → runtime-okuma gerekli (review LOW)."""
    return os.getenv("RERANK_PROVIDER", "local").lower() in {"bgem3", "colbert", "bge-m3"}


def _colbert_weights() -> tuple[float, float, float]:
    """Dense/sparse/colbert ağırlıkları — COLBERT_RERANK_WEIGHTS='d,s,c' (default 0.4,0.2,0.4,
    FlagEmbedding MLDR-önerisi colbert-ağırlıklı)."""
    raw = os.getenv("COLBERT_RERANK_WEIGHTS", "0.4,0.2,0.4")
    try:
        d, s, c = (float(x) for x in raw.split(","))
        return (d, s, c)
    except (ValueError, TypeError):
        return (0.4, 0.2, 0.4)


async def fetch_maddeler(pairs: list[tuple[str, int]]) -> list[SearchResult]:
    """Belirli (kanun_kodu, madde_no) maddelerini vektörsüz filtreyle çek.

    Çapa-madde garantisi: domain'in kilit maddeleri (örn. İş Hukuku ihbar İK m.17)
    konuşma-dili sorguda cross-encoder noise-floor yüzünden sıralamaya giremese bile
    aday havuzunda bulunsun diye Qdrant'tan doğrudan çekilir. score=0.0 döner —
    gerçek alakayı cross-encoder rerank sonradan atar; bulunmazsa sessizce atlanır.
    """
    if not pairs:
        return []
    client = get_shared_client()
    # TEK scroll — her (kanun_kodu, madde_no) çifti nested `must`, hepsi `should`
    # (OR) ile birleşir. Önceki N-round-trip (pair başına scroll) yük altında
    # ciddi latency veriyordu; tek sorgu + Python-tarafı dedup ile aynı sonuç.
    should = [
        models.Filter(
            must=[
                models.FieldCondition(key="kanun_kodu", match=models.MatchValue(value=kod)),
                models.FieldCondition(key="madde_no", match=models.MatchValue(value=madde)),
            ],
            # P8 (2026-06-11): çapalar NORMAL maddelerdir — ek/geçici chunk'lar
            # (madde_tur ∈ {ek, gecici}, aynı madde_no'yu taşır: m-VUK-ek-11 ↔ no=11)
            # çapa isteğini karşılamamalı. Eski corpus'ta madde_tur alanı yok →
            # must_not eksik-alanda geçer (geriye-uyumlu, davranış birebir).
            must_not=[
                models.FieldCondition(
                    key="madde_tur", match=models.MatchAny(any=["ek", "gecici"]),
                ),
            ],
        )
        for kod, madde in pairs
    ]
    points, _ = await client.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=models.Filter(should=should),
        # Madde başına birden fazla chunk olabilir; cushion + Python dedup ile
        # (kanun_kodu, madde_no) başına ilk chunk'ı tut (eski limit=1/pair semantiği).
        limit=max(len(pairs) * 4, 32),
        with_payload=True,
    )
    seen: set[tuple[str | None, int | None]] = set()
    out: list[SearchResult] = []
    for p in points:
        payload = p.payload or {}
        key = (payload.get("kanun_kodu"), payload.get("madde_no"))
        if key in seen:
            continue
        seen.add(key)
        out.append(_to_result(p))
    # Sessiz-kırılma sigortası (2026-06-10 keşif #A): payload tip/şema kayması
    # çapaları SESSİZCE düşürür, log'da iz kalmaz, madde-recall fark edilmeden
    # çöker. Bulunamayan çapa artık WARNING bırakır (davranış aynı: atlanır).
    if len(out) < len(pairs):
        found = {(payload_kod, payload_no) for payload_kod, payload_no in seen}
        missing = [f"{kod}-{madde}" for kod, madde in pairs if (kod, madde) not in found]
        if missing:
            log.warning("anchor_madde_not_found", missing=missing)
    return out


def _build_filter(
    domain: str | None,
    kanun_kodu: list[str] | None = None,
    source: list[str] | None = None,
    doc_type: str | list[str] | None = None,
) -> models.Filter | None:
    conditions: list[models.FieldCondition] = []
    if domain:
        conditions.append(
            models.FieldCondition(
                key="domain",
                match=models.MatchValue(value=domain),
            )
        )
    if kanun_kodu:
        conditions.append(
            models.FieldCondition(
                key="kanun_kodu",
                match=models.MatchAny(any=list(kanun_kodu)),
            )
        )
    if source:
        conditions.append(
            models.FieldCondition(
                key="source",
                match=models.MatchAny(any=list(source)),
            )
        )
    if doc_type:
        # Query-time doc_type filtresi (denetim 2026-06-04): mevzuat retrieval'ı law-only'e
        # daraltır → case-law (anayasa) gürültüsü top-K'yı kirletip maddeleri dışarı itmez.
        # Ölçüldü: law-only filtre madde_recall@5 +3.3pp (icra +7.7pp).
        # list → MatchAny (P4 2026-06-10): mevzuat node {law, regulation} arar — 128
        # yönetmelik chunk'ı (Mesafeli/Garanti/THH/SSH) salt-law filtrede görünmezdi.
        match = (
            models.MatchAny(any=list(doc_type))
            if isinstance(doc_type, (list, tuple))
            else models.MatchValue(value=doc_type)
        )
        conditions.append(models.FieldCondition(key="doc_type", match=match))
    if not conditions:
        return None
    return models.Filter(must=conditions)


def _to_result(point: Any) -> SearchResult:
    payload = point.payload or {}
    chunk_id = payload.get("chunk_id") or str(point.id)
    # scroll() `Record` döner (score'suz); query_points() `ScoredPoint` (score'lu).
    # getattr ile ikisini de güvenle ele al — fetch_maddeler scroll kullanır.
    score = getattr(point, "score", None)
    source_url = payload.get("source_url", "")
    if payload.get("source") == "mevzuat":
        source_url = normalize_mevzuat_url(source_url, payload)
    return SearchResult(
        chunk_id=chunk_id,
        score=float(score) if score is not None else 0.0,
        text=payload.get("text", ""),
        source=payload.get("source", ""),
        source_url=source_url,
        domain=payload.get("domain", ""),
        metadata={
            k: v
            for k, v in payload.items()
            if k not in {"text", "source", "source_url", "domain", "chunk_id"}
        },
    )
