"""JSONL progress store — seed crash olursa kaldığı yerden devam.

Format: data/seed_state/{court}_{domain}.jsonl, satır başına bir JSON kayıt:
    {"doc_id": "y-12345", "status": "ok", "chunks": 7, "at": "2026-05-24T..."}
    {"doc_id": "y-12346", "status": "error", "reason": "timeout", "at": "..."}
    {"doc_id": "y-12347", "status": "skipped", "reason": "empty_text", "at": "..."}
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

DocStatus = Literal["ok", "error", "skipped"]


class SeedState:
    """Bir (court, domain) çiftinin seed durumu — JSONL append-only store."""

    def __init__(self, state_dir: Path, court: str, domain: str) -> None:
        self.state_dir = state_dir
        self.court = court
        self.domain = domain
        self._path = state_dir / f"{court}_{domain}.jsonl"
        self._seen: set[str] = set()
        self._loaded = False

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> set[str]:
        """JSONL dosyasını oku, daha önce işlenmiş doc_id setini döndür.

        Bozuk satır varsa uyarı verir ve atlar — crash anında yarım yazılmış
        son satır kabul edilemez ama önceki satırlar geçerli kalır.
        """
        self._seen.clear()
        if not self._path.exists():
            self._loaded = True
            return self._seen

        with self._path.open(encoding="utf-8") as fh:
            for line_num, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(
                        "state_corrupt_line",
                        extra={"file": str(self._path), "line": line_num},
                    )
                    continue

                doc_id = record.get("doc_id")
                if doc_id:
                    self._seen.add(doc_id)

        self._loaded = True
        return self._seen

    def is_done(self, doc_id: str) -> bool:
        """Bu doc_id daha önce işlendi mi? (ok / error / skipped fark etmez)."""
        if not self._loaded:
            self.load()
        return doc_id in self._seen

    def mark_done(
        self,
        doc_id: str,
        status: DocStatus = "ok",
        chunks: int = 0,
        reason: str | None = None,
    ) -> None:
        """Doc'u JSONL'a ekle ve in-memory set'i güncelle."""
        if not self._loaded:
            self.load()

        record: dict[str, object] = {
            "doc_id": doc_id,
            "status": status,
            "chunks": chunks,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        if reason:
            record["reason"] = reason

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()

        self._seen.add(doc_id)

    def count(self) -> int:
        """Toplam işlenmiş doc sayısı (yüklü değilse yükler)."""
        if not self._loaded:
            self.load()
        return len(self._seen)
