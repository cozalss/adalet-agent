"""Feedback repository — Postgres veya dosya (JSONL) fallback.

env-gated: DATABASE_URL set ise PostgresFeedbackRepo (kalıcı, sorgulanabilir),
değilse FilesystemFeedbackRepo (eski JSONL davranışı — dev/test/CI).

Çağıran (api/routes/feedback.py) `get_feedback_repo().save(record)` kullanır;
backend seçimi şeffaf.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import structlog

log = structlog.get_logger()


class FeedbackRepo(Protocol):
    """Tüm feedback backend'leri bu protokole uyar."""

    async def save(self, record: dict[str, Any]) -> None: ...


class FilesystemFeedbackRepo:
    """Append-only JSONL — eski davranış. Read-only fs'te FEEDBACK_LOG_DIR mount."""

    name = "filesystem"

    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir

    def _append_jsonl(self, log_path: Path, record: dict[str, Any]) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def save(self, record: dict[str, Any]) -> None:
        day = datetime.now(UTC).strftime("%Y%m%d")
        path = self.log_dir / f"feedback_{day}.jsonl"
        await asyncio.to_thread(self._append_jsonl, path, record)


class PostgresFeedbackRepo:
    """SQLModel Feedback tablosuna yazar (kalıcı + sorgulanabilir)."""

    name = "postgres"

    async def save(self, record: dict[str, Any]) -> None:
        from db.engine import session_scope
        from db.models import Feedback

        row = Feedback(
            feedback_id=record["feedback_id"],
            principal_kind=record.get("principal_kind", ""),
            principal_sub_hash=record.get("principal_sub_hash", ""),
            conversation_id=record.get("conversation_id", ""),
            turn_index=record.get("turn_index"),
            rating=record.get("rating", ""),
            comment_masked=record.get("comment_masked", ""),
        )
        async with session_scope() as session:
            session.add(row)


def get_feedback_repo(log_dir: Path) -> FeedbackRepo:
    """env-gated factory — DB açıksa Postgres, değilse JSONL dosya."""
    from db.engine import is_db_enabled

    if is_db_enabled():
        return PostgresFeedbackRepo()
    return FilesystemFeedbackRepo(log_dir)
