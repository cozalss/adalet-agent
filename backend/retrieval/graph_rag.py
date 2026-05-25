"""GraphRAG — Türk hukuku için bilgi grafı (NetworkX backed).

Sorun: Klasik chunk retrieval bağımsız parçalar getirir. Hukuk DOĞASI gereği
ilişkiseldir: "Yargıtay 9.HD 2019/1234 KARARI" → "İş Kanunu m.32" → "Kıdem
tazminatı" kavramı → "T.B.K. m.83" ödeme yöntemi. Bu zincir tek bir BGE-M3
similarity'sinde kaybolur.

Çözüm: Heterogeneous knowledge graph (NetworkX MultiDiGraph):
  Node tipleri:
    LawNode    — (kanun_kodu, madde_no)
    CaseNode   — (mahkeme, esas/karar)
    ConceptNode — kavram ("kıdem tazminatı", "ayıplı mal")

  Edge tipleri:
    CITES      — case → law           (kararda madde geçer)
    GOVERNS    — law → concept        (madde kavramı düzenler)
    DISCUSSES  — case → concept       (karar kavramı tartışır)
    RELATES_TO — concept ↔ concept    (synonym/related)

Query yolu:
  1. Standart retrieval → seed Citation listesi (chunk_id'leri)
  2. Seed'lerden graph node'larını bul (citation.parse_citation + payload eşle)
  3. k-hop traverse → ilgili node'ların döküman listesini topla
  4. Bu döküman id'lerini Qdrant'ta fetch → ek Citation listesi
  5. Caller merge + rerank

Default-safe: ENV `GRAPH_RAG_ENABLED=0` → modül boş graph döner, expand
sıfır yeni node getirir, akış kırılmaz. Production'da offline graph
`scripts/build_graph.py` ile oluşturulur, in-memory yüklenir.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import structlog

log = structlog.get_logger()

GRAPH_RAG_ENABLED = os.getenv("GRAPH_RAG_ENABLED", "0").lower() in {"1", "true", "yes"}
GRAPH_HOPS_DEFAULT = int(os.getenv("GRAPH_HOPS", "2"))
GRAPH_MAX_EXPAND = int(os.getenv("GRAPH_MAX_EXPAND", "20"))
GRAPH_PATH = Path(os.getenv("GRAPH_PATH", "data/graph/legal_graph.json"))

NodeType = Literal["law", "case", "concept"]
EdgeType = Literal["cites", "governs", "discusses", "relates_to"]


# --------------------------------------------------------------------------
#  Data model
# --------------------------------------------------------------------------

@dataclass(slots=True, frozen=True)
class GraphNode:
    """Heterojen graf düğümü — id immutable, attrs metadata."""

    node_id: str           # "law:TKHK:11", "case:Yargitay:2019/1234", "concept:kidem-tazminati"
    node_type: NodeType
    label: str             # insan okunur ("TKHK Madde 11")
    attrs: tuple = field(default_factory=tuple)  # (key, value) çiftleri, hashable


@dataclass(slots=True)
class GraphHit:
    """expand() çıktısı — node + nasıl ulaşıldığı."""

    node: GraphNode
    distance: int          # seed'den hop sayısı
    path: list[str]        # edge sequence ("cites", "governs", ...)
    score: float = 1.0     # 1/(distance+1) basit prior


# --------------------------------------------------------------------------
#  Index
# --------------------------------------------------------------------------

class LegalGraph:
    """NetworkX MultiDiGraph wrapper. Optional disk persistence (JSON)."""

    def __init__(self) -> None:
        try:
            import networkx as nx
        except ImportError:
            log.warning("networkx_missing_graph_disabled")
            self._graph = None
            return
        self._nx = nx
        self._graph = nx.MultiDiGraph()
        self._nodes: dict[str, GraphNode] = {}

    @property
    def is_available(self) -> bool:
        return self._graph is not None

    @property
    def n_nodes(self) -> int:
        return self._graph.number_of_nodes() if self._graph is not None else 0

    @property
    def n_edges(self) -> int:
        return self._graph.number_of_edges() if self._graph is not None else 0

    # --- Construction helpers ---

    def add_law(self, kanun: str, madde: int, label: str | None = None) -> str:
        nid = f"law:{kanun.upper()}:{madde}"
        if self._graph is None:
            return nid
        if nid not in self._nodes:
            node = GraphNode(
                node_id=nid, node_type="law",
                label=label or f"{kanun.upper()} Madde {madde}",
                attrs=(("kanun", kanun.upper()), ("madde", madde)),
            )
            self._nodes[nid] = node
            self._graph.add_node(nid, node_type="law", label=node.label)
        return nid

    def add_case(self, mahkeme: str, esas: str, karar: str, label: str | None = None) -> str:
        nid = f"case:{mahkeme}:{esas}/{karar}"
        if self._graph is None:
            return nid
        if nid not in self._nodes:
            node = GraphNode(
                node_id=nid, node_type="case",
                label=label or f"{mahkeme} {esas}/{karar}",
                attrs=(("mahkeme", mahkeme), ("esas", esas), ("karar", karar)),
            )
            self._nodes[nid] = node
            self._graph.add_node(nid, node_type="case", label=node.label)
        return nid

    def add_concept(self, name: str) -> str:
        slug = _slug(name)
        nid = f"concept:{slug}"
        if self._graph is None:
            return nid
        if nid not in self._nodes:
            node = GraphNode(
                node_id=nid, node_type="concept",
                label=name, attrs=(("name", name),),
            )
            self._nodes[nid] = node
            self._graph.add_node(nid, node_type="concept", label=name)
        return nid

    def link(
        self, src_id: str, dst_id: str, edge_type: EdgeType, weight: float = 1.0,
    ) -> None:
        if self._graph is None:
            return
        self._graph.add_edge(src_id, dst_id, key=edge_type, edge_type=edge_type, weight=weight)

    # --- Query ---

    def expand(
        self, seed_ids: list[str], hops: int = GRAPH_HOPS_DEFAULT,
        max_nodes: int = GRAPH_MAX_EXPAND,
    ) -> list[GraphHit]:
        """Seed'lerden k-hop BFS ile alakalı node'ları döndür.

        Score: 1 / (distance + 1) — yakın daha önemli.
        Path: edge_type sequence (debug için).
        """
        if not GRAPH_RAG_ENABLED or self._graph is None or not seed_ids:
            return []

        visited: dict[str, GraphHit] = {}
        # BFS queue: (node_id, distance, edge_path)
        queue: list[tuple[str, int, list[str]]] = [
            (sid, 0, []) for sid in seed_ids if sid in self._nodes
        ]
        idx = 0
        while idx < len(queue) and len(visited) < max_nodes:
            current, dist, path = queue[idx]
            idx += 1
            if dist > hops:
                continue
            if current in visited and visited[current].distance <= dist:
                continue
            if current in self._nodes:
                node = self._nodes[current]
                visited[current] = GraphHit(
                    node=node, distance=dist, path=path,
                    score=1.0 / (dist + 1),
                )
            if dist >= hops:
                continue
            # Komşuları sıraya al
            for neighbor in self._graph.successors(current):
                edge_data = self._graph.get_edge_data(current, neighbor)
                if edge_data:
                    # Multi-edge: ilk edge_type'i al
                    first_key = next(iter(edge_data.keys()))
                    queue.append((neighbor, dist + 1, [*path, str(first_key)]))
            for neighbor in self._graph.predecessors(current):
                edge_data = self._graph.get_edge_data(neighbor, current)
                if edge_data:
                    first_key = next(iter(edge_data.keys()))
                    queue.append((neighbor, dist + 1, [*path, f"~{first_key}"]))

        hits = sorted(visited.values(), key=lambda h: (h.distance, -h.score))
        return hits[:max_nodes]

    # --- Persistence ---

    def save(self, path: Path = GRAPH_PATH) -> None:
        """JSON node-link format'a yaz (basit, taşınabilir)."""
        if self._graph is None:
            return
        from networkx.readwrite.json_graph import node_link_data

        path.parent.mkdir(parents=True, exist_ok=True)
        data = node_link_data(self._graph, edges="links")
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("graph_saved", path=str(path), n_nodes=self.n_nodes, n_edges=self.n_edges)

    @classmethod
    def load(cls, path: Path = GRAPH_PATH) -> LegalGraph:
        """Disk'ten geri yükle. Yoksa boş graph döner."""
        g = cls()
        if g._graph is None or not path.exists():
            return g
        from networkx.readwrite.json_graph import node_link_graph
        data = json.loads(path.read_text(encoding="utf-8"))
        g._graph = node_link_graph(data, edges="links", multigraph=True, directed=True)
        # _nodes'u yeniden oluştur
        for nid, attrs in g._graph.nodes(data=True):
            nt = attrs.get("node_type", "concept")
            label = attrs.get("label", nid)
            g._nodes[nid] = GraphNode(
                node_id=nid, node_type=nt, label=label, attrs=(),
            )
        log.info("graph_loaded", path=str(path), n_nodes=g.n_nodes, n_edges=g.n_edges)
        return g


# --------------------------------------------------------------------------
#  Seed extraction — Citation listesinden graph node id'leri çıkar
# --------------------------------------------------------------------------

# Tanınan kanun kısaltmaları — seed_mevzuat KANUN_KODU_TO_NUMARA ile senkron tutulmalı.
# Bu liste graph CITES edge'lerini etkiler; ne kadar geniş olursa o kadar zengin graph.
_LAW_CODES = (
    "TKHK", "TBK", "IK", "İK", "SGK", "HMK", "TCK", "BK", "MK", "İYUK", "IYUK",
    "TMK", "ANAYASA", "IIK", "İİK", "SK", "ISGK", "İSGK", "VUK", "TK", "KK", "KMK",
    "RKHK",
)
# Tek bir non-capturing alt-grup içinde alternation
_LAW_CODE_GROUP = "(" + "|".join(_LAW_CODES) + ")"

# "TKHK Madde 11", "İK m.32", "5510 sayılı kanun 4. maddesi", "T.B.K. m.299"
# Üç varyantı yakalar:
#   1. Kısaltma + (m./madde/M.) + sayı  → "TKHK m.11", "İş K. md. 32"
#   2. Sayılı kanun ifadesi              → "6098 sayılı kanunun 299. m."
#   3. Nokta ile yazılmış (T.B.K., İ.K.) → "T.B.K. m.83"
_LAW_ID_RE = re.compile(
    # Form 1: bilinen kanun kısaltması + ops. nokta + ops. "m./md./madde" + sayı
    rf"\b{_LAW_CODE_GROUP}\.?\s*(?:m\.?d?\.?|madde)?\s*(\d{{1,4}})",
    re.IGNORECASE,
)

# "Yargıtay 9.HD 2019/1234", "Yargıtay HGK 2020/567", "Danıştay 5.D 2018/123"
# Daire opsiyonel; esas yıl + karar numarası ana sinyal.
_CASE_ID_RE = re.compile(
    r"(Yargıtay|Danıştay|Anayasa(?:\s*Mahkemesi)?)"
    r"(?:\s+(?:HGK|İBK|CGK|\d+\.?\s*[HC]?D|\d+\.?\s*Daire))?"
    r"\s+(\d{4})\s*/\s*(\d{1,6})",
    re.IGNORECASE,
)


def extract_seed_ids(citation_titles: Iterable[str]) -> list[str]:
    """Citation.title metinlerinden graph node id'leri çıkar."""
    seeds: list[str] = []
    seen: set[str] = set()
    for title in citation_titles:
        for m in _LAW_ID_RE.finditer(title):
            nid = f"law:{m.group(1).upper()}:{int(m.group(2))}"
            if nid not in seen:
                seen.add(nid)
                seeds.append(nid)
        for m in _CASE_ID_RE.finditer(title):
            nid = f"case:{m.group(1)}:{m.group(2)}/{m.group(3)}"
            if nid not in seen:
                seen.add(nid)
                seeds.append(nid)
    return seeds


def _slug(name: str) -> str:
    """Türkçe diakritikleri yumuşat + alphanumeric+dash."""
    mapping = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    s = name.translate(mapping).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "concept"


# --------------------------------------------------------------------------
#  Singleton — process-wide graph (lazy load)
# --------------------------------------------------------------------------

_graph_singleton: LegalGraph | None = None


def get_graph() -> LegalGraph:
    global _graph_singleton
    if _graph_singleton is None:
        if GRAPH_PATH.exists():
            _graph_singleton = LegalGraph.load(GRAPH_PATH)
        else:
            _graph_singleton = LegalGraph()
            log.info("graph_empty", path=str(GRAPH_PATH))
    return _graph_singleton


def reset_graph() -> None:
    global _graph_singleton
    _graph_singleton = None


__all__ = (
    "GRAPH_RAG_ENABLED",
    "GraphHit",
    "GraphNode",
    "LegalGraph",
    "extract_seed_ids",
    "get_graph",
    "reset_graph",
)
