"""Seed run istatistikleri ve progress reporting."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RunStats:
    """Tek bir (court, domain) çalışmasının sayaçları."""

    court: str
    domain: str
    fetched: int = 0
    embedded: int = 0
    upserted_docs: int = 0
    upserted_chunks: int = 0
    skipped_resume: int = 0
    errors: int = 0
    started_at: float = field(default_factory=time.monotonic)
    _last_log_count: int = 0

    @property
    def elapsed_sec(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def docs_per_min(self) -> float:
        elapsed_min = max(self.elapsed_sec / 60.0, 1e-6)
        return self.upserted_docs / elapsed_min

    def eta_minutes(self, target_total: int) -> float:
        """Hedef toplam doc sayısına göre kalan dakika tahmini."""
        rate = self.docs_per_min
        if rate < 1e-3:
            return float("inf")
        remaining = max(0, target_total - self.upserted_docs)
        return remaining / rate

    def log_if_due(self, every: int, target_total: int) -> None:
        """Her `every` doc'ta bir progress satırı bas."""
        if self.upserted_docs - self._last_log_count < every:
            return
        self._last_log_count = self.upserted_docs

        eta_min = self.eta_minutes(target_total)
        eta_str = f"{eta_min:.1f} dk" if eta_min != float("inf") else "—"

        logger.info(
            "seed_progress",
            extra={
                "court": self.court,
                "domain": self.domain,
                "upserted_docs": self.upserted_docs,
                "upserted_chunks": self.upserted_chunks,
                "errors": self.errors,
                "skipped_resume": self.skipped_resume,
                "rate_docs_per_min": round(self.docs_per_min, 1),
                "eta_min": eta_str,
            },
        )

    def summary_line(self) -> str:
        return (
            f"[{self.court}/{self.domain}] "
            f"upserted={self.upserted_docs} ({self.upserted_chunks} chunks) "
            f"skipped_resume={self.skipped_resume} "
            f"errors={self.errors} "
            f"in {self.elapsed_sec:.0f}s "
            f"({self.docs_per_min:.1f} doc/min)"
        )
