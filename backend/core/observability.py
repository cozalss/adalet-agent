"""Langfuse observability — Sprint-4 W8.1.

LangGraph callback handler ile her node bittiğinde trace event yayınla.
LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY env'leri yoksa no-op fallback.

Kullanım:
  >>> handler = get_langfuse_handler(trace_name="ask", user_id="...")
  >>> if handler:
  ...     state = await graph.ainvoke(initial, config={"callbacks": [handler]})

Cost tracker (W8.6) ayrı script — Langfuse'tan günlük export çeker.
"""

from __future__ import annotations

import os
from typing import Any

import structlog

log = structlog.get_logger()

LANGFUSE_ENABLED = bool(
    os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"),
)
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")


def get_langfuse_handler(
    trace_name: str = "ask",
    user_id: str | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any:
    """LangChain-compatible callback handler döner. ENV yoksa None."""
    if not LANGFUSE_ENABLED:
        return None
    try:
        from langfuse.callback import CallbackHandler
    except ImportError:
        log.warning("langfuse_import_failed")
        return None
    try:
        return CallbackHandler(
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
            host=LANGFUSE_HOST,
            trace_name=trace_name,
            user_id=user_id,
            session_id=session_id,
            metadata=metadata or {},
        )
    except Exception as exc:
        log.warning("langfuse_handler_failed", error=str(exc))
        return None


__all__ = ("LANGFUSE_ENABLED", "LANGFUSE_HOST", "get_langfuse_handler")
