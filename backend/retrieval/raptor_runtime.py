"""RAPTOR runtime — process-singleton + lifespan preload.

Sprint-4 W3.2. main.py lifespan'da get_raptor_index() çağrılır; eğer
RAPTOR_PICKLE_PATH varsa diskten yüklenir, yoksa boş (no-op) index döner.

Build offline yapılır: `scripts/build_raptor.py`. Bu modül sadece runtime
load ve singleton wiring sağlar.

Kullanım (agent node):
    from retrieval.raptor_runtime import get_raptor_index
    idx = get_raptor_index()
    if idx and idx.built:
        hits = await idx.query(question, top_k=5)
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog

from retrieval.raptor import RAPTOR_ENABLED, RaptorIndex

log = structlog.get_logger()

RAPTOR_PICKLE_PATH = os.getenv(
    "RAPTOR_PICKLE_PATH",
    str(Path(__file__).parent.parent / "data" / "raptor" / "tree.pkl"),
)

_singleton: RaptorIndex | None = None


def get_raptor_index() -> RaptorIndex | None:
    """Process-singleton RaptorIndex.

    - `RAPTOR_ENABLED=0` (default) → None döner (no-op)
    - `RAPTOR_ENABLED=1` + pickle var → diskten yüklenir
    - `RAPTOR_ENABLED=1` + pickle yok → boş index (built=False, query=[] döner)
    """
    global _singleton
    if not RAPTOR_ENABLED:
        return None
    if _singleton is not None:
        return _singleton

    path = Path(RAPTOR_PICKLE_PATH)
    if path.exists():
        try:
            _singleton = RaptorIndex.load(path)
            return _singleton
        except (OSError, EOFError, KeyError) as exc:
            log.warning(
                "raptor_load_failed_falling_back",
                path=str(path), error=str(exc),
            )

    # Pickle yok / bozuk — boş index dön (no-op)
    _singleton = RaptorIndex()
    log.info("raptor_runtime_empty_index", reason="no_pickle_or_load_failed")
    return _singleton


def reset_raptor_singleton() -> None:
    """Test fixture — singleton'u sıfırla."""
    global _singleton
    _singleton = None


__all__ = ("RAPTOR_PICKLE_PATH", "get_raptor_index", "reset_raptor_singleton")
