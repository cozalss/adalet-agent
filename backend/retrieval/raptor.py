"""RAPTOR — Recursive Abstractive Processing for Tree-Organized Retrieval.

Referans: Sarthi et al. ICLR 2024 — "RAPTOR: Recursive Abstractive Processing
for Tree-Organized Retrieval" (arxiv:2401.18059).

Sorun: Yargıtay kararları 5-50 sayfa, klasik chunking soruyu cevaplamak için
yetersiz bağlam verir (chunk → ezbere "Madde 11" yazılı bir cümle, ama
kararın asıl sonucu sayfa 20'de). Vatandaş "bu emsal benim davama uyar mı?"
diye sorduğunda, asıl gerek **kararın ÖZETİ + ÖZET'in ÖZETİ + ÖZET'in
ÖZETİNİN ÖZETİ** hiyerarşisidir.

Akış:
  1. Leaf level: chunk_text(decision) → chunks (1200 char, mevcut chunker)
  2. Embed all chunks (BGE-M3 dense)
  3. GMM cluster (sklearn) — UMAP'siz, raw embedding
  4. Her cluster için LLM summary (cluster_size ≤ 8)
  5. Summary'leri embed et, tekrar cluster, tekrar summary → LEVEL=3 dur
  6. Query: dense similarity her seviyede top-K, concat

Default-safe: ENV `RAPTOR_ENABLED=0` → modül import edilse bile build/query
çağrıları no-op döner. Production'da offline tree build, query online.

Saklama: tree[level] = list[RaptorNode]. Çok büyük corpus için disk-based
backend (pickle/parquet) Sprint-9'a ertelendi. Şimdilik in-memory.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field

import structlog

log = structlog.get_logger()

RAPTOR_ENABLED = os.getenv("RAPTOR_ENABLED", "0").lower() in {"1", "true", "yes"}
RAPTOR_LEVELS = int(os.getenv("RAPTOR_LEVELS", "3"))
RAPTOR_MAX_CLUSTER_SIZE = int(os.getenv("RAPTOR_MAX_CLUSTER_SIZE", "8"))
RAPTOR_MIN_CLUSTER_SIZE = int(os.getenv("RAPTOR_MIN_CLUSTER_SIZE", "2"))
RAPTOR_SUMMARY_MAX_TOKENS = int(os.getenv("RAPTOR_SUMMARY_MAX_TOKENS", "400"))

_SUMMARY_SYSTEM = (
    "Sen Türk hukuku uzmanı bir özetleme asistanısın. Verilen 2-8 metin "
    "parçası (kanun/karar) için TEK BİR Türkçe paragraf özet üret. Hedef: "
    "soyut bir vatandaş arama sorgusunu eşleştirmek. ÖZETTE madde no "
    "veya esas/karar uydurma — orijinal metinlerde geçenleri AYNEN aktar."
)

_SUMMARY_USER_TEMPLATE = (
    "Aşağıdaki {n} metin parçasını TEK paragraf olarak özetle. Hukuki "
    "kavramları koruyarak yaz (max ~150 kelime):\n\n{texts}\n\nÖzet:"
)


# --------------------------------------------------------------------------
#  Data model
# --------------------------------------------------------------------------

@dataclass(slots=True)
class RaptorNode:
    """Hiyerarşik ağaç düğümü."""

    node_id: str
    level: int                       # 0 = leaf (orijinal chunk), 1+ = özet
    text: str
    embedding: list[float] | None = field(default=None)
    children: list[str] = field(default_factory=list)
    source_chunk_ids: list[str] = field(default_factory=list)  # leaf trace
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class RaptorQueryResult:
    node: RaptorNode
    score: float
    matched_level: int


# --------------------------------------------------------------------------
#  Index
# --------------------------------------------------------------------------

class RaptorIndex:
    """Hiyerarşik özet ağacı — in-memory."""

    def __init__(self) -> None:
        self.tree: dict[int, list[RaptorNode]] = {}
        self.built = False

    def all_nodes(self) -> list[RaptorNode]:
        out: list[RaptorNode] = []
        for level_nodes in self.tree.values():
            out.extend(level_nodes)
        return out

    async def build(
        self,
        documents: list[tuple[str, str]],   # [(chunk_id, text), ...]
        embedder=None,
        llm_summarize=None,
        force_enabled: bool = False,
    ) -> None:
        """Tree'yi oluştur.

        Args:
            documents: leaf seviyesinde (id, text) çiftleri
            embedder: BGE-M3 wrapper (None ise lazy default)
            llm_summarize: async (texts) -> summary fonksiyonu (None ise default)
            force_enabled: True ise modül-level RAPTOR_ENABLED cache'ini bypass eder
                           (test ortamında env order bağımlılığı için)
        """
        # Sprint-4 W3.5: env'i runtime'da yeniden oku — test'lerde
        # `os.environ["RAPTOR_ENABLED"]="1"` set edilse bile import sıralaması
        # nedeniyle modül-level constant False cache'lenmiş olabilir.
        enabled = force_enabled or os.getenv("RAPTOR_ENABLED", "0").lower() in {
            "1", "true", "yes",
        }
        if not enabled:
            log.info("raptor_disabled")
            self.built = True
            return
        if not documents:
            self.built = True
            return

        if embedder is None:
            from retrieval.embedding import Embedder
            embedder = Embedder()
        if llm_summarize is None:
            llm_summarize = _default_summarize

        # --- Level 0: leaf nodes ---
        leaf_texts = [t for _id, t in documents]
        leaf_ids = [i for i, _t in documents]
        leaf_embeds = embedder.encode(leaf_texts, return_colbert=False).dense

        leaves = [
            RaptorNode(
                node_id=f"L0:{cid}",
                level=0,
                text=t,
                embedding=emb,
                source_chunk_ids=[cid],
            )
            for cid, t, emb in zip(leaf_ids, leaf_texts, leaf_embeds, strict=True)
        ]
        self.tree[0] = leaves

        # --- Yukarı seviyeler ---
        current = leaves
        for level in range(1, RAPTOR_LEVELS + 1):
            if len(current) < RAPTOR_MIN_CLUSTER_SIZE:
                log.info("raptor_stop_small", level=level, n=len(current))
                break

            clusters = _cluster_nodes(current)
            if not clusters:
                break

            next_level = await self._build_level(
                level=level, current=current, clusters=clusters,
                embedder=embedder, llm_summarize=llm_summarize,
            )
            if not next_level:
                log.info("raptor_no_summaries", level=level)
                break

            self.tree[level] = next_level
            current = next_level
            log.info("raptor_level_built", level=level, n=len(next_level))

        self.built = True
        log.info("raptor_built", levels=list(self.tree.keys()), n_total=len(self.all_nodes()))

    async def _build_level(
        self,
        *,
        level: int,
        current: list[RaptorNode],
        clusters: list[list[int]],
        embedder,  # type: ignore[no-untyped-def]
        llm_summarize,  # type: ignore[no-untyped-def]
    ) -> list[RaptorNode]:
        """Bir RAPTOR seviyesini cluster'lardan inşa et (helper)."""
        next_level: list[RaptorNode] = []
        for cl_idx, member_idxs in enumerate(clusters):
            if len(member_idxs) < RAPTOR_MIN_CLUSTER_SIZE:
                continue
            members = [current[i] for i in member_idxs]
            texts = [m.text for m in members]
            summary = await llm_summarize(texts)
            if not summary or not summary.strip():
                continue
            summary_emb = embedder.encode([summary], return_colbert=False).dense[0]
            src_chunks: list[str] = []
            for m in members:
                src_chunks.extend(m.source_chunk_ids)
            next_level.append(RaptorNode(
                node_id=f"L{level}:c{cl_idx}",
                level=level,
                text=summary,
                embedding=summary_emb,
                children=[m.node_id for m in members],
                source_chunk_ids=src_chunks,
            ))
        return next_level

    def save(self, path: str | os.PathLike) -> None:
        """Tree'yi pickle olarak diske yaz. Sprint-4 W3.1.

        Sprint-4 W3.5: pickle class identity bağımlılığını kırmak için
        node'ları dict olarak serialize ediyoruz (pytest reload veya import
        order'a göre `RaptorNode` farklı class identity'ye sahip olabiliyor).
        Yine pickle protocol'ü kullanılır — dataclass-asdict gibi bir adım.
        """
        import pickle
        from pathlib import Path as _P

        if not self.built:
            raise RuntimeError("RaptorIndex.save() build() öncesi çağrılamaz")
        p = _P(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        # Dict-only payload — class-identity safe
        serializable: dict[int, list[dict]] = {}
        for level, nodes in self.tree.items():
            serializable[int(level)] = [
                {
                    "node_id": n.node_id,
                    "level": n.level,
                    "text": n.text,
                    "embedding": n.embedding,
                    "children": list(n.children),
                    "source_chunk_ids": list(n.source_chunk_ids),
                    "metadata": dict(n.metadata),
                }
                for n in nodes
            ]

        with p.open("wb") as fh:
            pickle.dump({"tree": serializable, "built": True, "version": 2}, fh)
        log.info("raptor_saved", path=str(p), n_nodes=len(self.all_nodes()))

    @classmethod
    def load(cls, path: str | os.PathLike) -> RaptorIndex:
        """Diskten yükle (pickle). Sprint-4 W3.1.

        Pickle güvenlik notu: bu dosya BIZIM build script'imizin çıktısı,
        third-party input değil. Yine de production'da hash checksum
        kontrolü iyi pratik (W7 secret hardening'de eklenecek).

        W3.5: dict-based deserialize (class identity bağımlılığı yok).
        """
        import pickle
        from pathlib import Path as _P

        p = _P(path)
        if not p.exists():
            raise FileNotFoundError(f"RAPTOR pickle bulunamadı: {p}")
        with p.open("rb") as fh:
            data = pickle.load(fh)
        idx = cls()
        raw_tree = data.get("tree", {})

        # v1 (legacy) ve v2 (dict-based) ikisini de destekle.
        version = int(data.get("version", 1))
        rebuilt: dict[int, list[RaptorNode]] = {}
        for level, items in raw_tree.items():
            level_int = int(level)
            if version >= 2:
                # items: list[dict]
                rebuilt[level_int] = [
                    RaptorNode(
                        node_id=d["node_id"],
                        level=int(d["level"]),
                        text=d["text"],
                        embedding=d.get("embedding"),
                        children=list(d.get("children", [])),
                        source_chunk_ids=list(d.get("source_chunk_ids", [])),
                        metadata=dict(d.get("metadata", {})),
                    )
                    for d in items
                ]
            else:
                # v1: items zaten RaptorNode listesi (eski pickle)
                rebuilt[level_int] = items   # type: ignore[assignment]

        idx.tree = rebuilt
        idx.built = bool(data.get("built", True))
        log.info("raptor_loaded", path=str(p), n_nodes=len(idx.all_nodes()))
        return idx

    async def query(
        self,
        question: str,
        top_k: int = 5,
        per_level_k: int = 3,
        embedder=None,
    ) -> list[RaptorQueryResult]:
        """Her seviyeden top-K çek, score'a göre concat."""
        if not self.built or not self.tree:
            return []
        if embedder is None:
            from retrieval.embedding import Embedder
            embedder = Embedder()

        q_dense, _, _ = embedder.encode_query(question, return_colbert=False)

        hits: list[RaptorQueryResult] = []
        for level, nodes in self.tree.items():
            scored = []
            for n in nodes:
                if n.embedding is None:
                    continue
                score = _cosine(q_dense, n.embedding)
                scored.append((score, n))
            scored.sort(key=lambda x: x[0], reverse=True)
            for score, node in scored[:per_level_k]:
                hits.append(RaptorQueryResult(node=node, score=score, matched_level=level))

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]


# --------------------------------------------------------------------------
#  Clustering — sklearn GMM (BIC ile cluster sayısı seçimi)
# --------------------------------------------------------------------------

def _cluster_nodes(nodes: list[RaptorNode]) -> list[list[int]]:
    """GMM cluster — her cluster için node index listesi döner.

    Çok küçük gruplar (n<MIN_CLUSTER_SIZE) → tek cluster.
    BIC ile optimal k seçilir (max k = n/MAX_SIZE).
    """
    import numpy as np

    embeddings = np.array(
        [n.embedding for n in nodes if n.embedding is not None],
        dtype=np.float32,
    )
    n = len(embeddings)
    if n < RAPTOR_MIN_CLUSTER_SIZE:
        return [list(range(n))]

    max_k = max(1, min(n // RAPTOR_MAX_CLUSTER_SIZE + 1, 20))
    try:
        from sklearn.mixture import GaussianMixture
    except ImportError:
        # sklearn yoksa: tek cluster fallback
        log.warning("sklearn_missing_raptor_fallback")
        return [list(range(n))]

    best_k = 1
    best_bic = float("inf")
    for k in range(1, max_k + 1):
        try:
            gmm = GaussianMixture(
                n_components=k, random_state=42, covariance_type="diag",
                reg_covar=1e-4, max_iter=100,
            )
            gmm.fit(embeddings)
            bic = gmm.bic(embeddings)
            if bic < best_bic:
                best_bic = bic
                best_k = k
        except Exception as exc:
            log.debug("gmm_failed", k=k, error=str(exc))
            continue

    if best_k == 1:
        return [list(range(n))]

    gmm = GaussianMixture(
        n_components=best_k, random_state=42, covariance_type="diag",
    )
    labels = gmm.fit_predict(embeddings)

    clusters: list[list[int]] = [[] for _ in range(best_k)]
    for idx, lab in enumerate(labels):
        clusters[int(lab)].append(idx)
    # Boş cluster'ları at
    return [c for c in clusters if c]


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity (numpy)."""
    import numpy as np
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


# --------------------------------------------------------------------------
#  Default summarizer — agents.llm.MockLLM/Qwen
# --------------------------------------------------------------------------

async def _default_summarize(texts: list[str]) -> str:
    """LLM ile cluster özetle. MockLLM dummy döner ama akış kırılmaz."""
    from agents.llm import ChatMessage, get_llm

    joined = "\n\n---\n\n".join(t[:1500] for t in texts)
    user_msg = _SUMMARY_USER_TEMPLATE.format(n=len(texts), texts=joined)
    llm = get_llm()
    try:
        resp = await llm.chat(
            messages=[
                ChatMessage(role="system", content=_SUMMARY_SYSTEM),
                ChatMessage(role="user", content=user_msg),
            ],
            temperature=0.1,
            max_tokens=RAPTOR_SUMMARY_MAX_TOKENS,
            json_mode=False,
        )
        return resp.content.strip()
    except Exception as exc:
        log.warning("raptor_summarize_failed", error=str(exc))
        # Fallback: ilk metnin ilk 300 char'ı (özet yerine)
        return texts[0][:300] if texts else ""


__all__: Iterable[str] = (
    "RAPTOR_ENABLED",
    "RAPTOR_LEVELS",
    "RaptorIndex",
    "RaptorNode",
    "RaptorQueryResult",
)
