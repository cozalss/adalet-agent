"""Langfuse v4 observability — Sprint-6 W8.1 refactor.

Langfuse v4 (2025+) `@observe()` decorator pattern. Eski v2.x
`CallbackHandler` deprecated.

Kullanım — node fonksiyonlarında:
  >>> from core.observability import observe_node
  >>>
  >>> @observe_node(as_type="generation")
  >>> async def draft_node(state):
  >>>     ...

Kullanım — ask endpoint'inde:
  >>> from core.observability import observe_ask_request
  >>>
  >>> @observe_ask_request()
  >>> async def ask(req: AskRequest):
  >>>     final_state = await graph.ainvoke(initial)
  >>>     return _state_to_response(final_state, trace_id=current_trace_id())

ENV (`.env`):
  LANGFUSE_PUBLIC_KEY=pk-lf-xxx
  LANGFUSE_SECRET_KEY=sk-lf-xxx
  LANGFUSE_HOST=https://cloud.langfuse.com  # opsiyonel

ENV yoksa: decorator no-op, app etkilenmez. Tüm hatalar `log.warning` ile bastırılır.

Cost tracker (W8.6) ayrı script — Langfuse'tan günlük export çeker.
"""

from __future__ import annotations

import functools
import os
import threading
from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypeVar

import structlog

log = structlog.get_logger()

LANGFUSE_ENABLED = bool(
    os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"),
)
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

_F = TypeVar("_F", bound=Callable[..., Awaitable[Any]])

# Module-level Langfuse client singleton (init at first use, lifespan friendly)
_client: Any = None
_observe_fn: Callable[..., Any] | None = None
# Eşzamanlı ilk istekler iki ayrı Langfuse client (çift arka-plan thread/bağlantı)
# kurmasın — double-checked locking (review HIGH).
_langfuse_lock = threading.Lock()


def _init_langfuse() -> tuple[Any, Callable[..., Any] | None]:
    """Lazy Langfuse v4 init. Returns (client, observe_decorator) or (None, None)."""
    if not LANGFUSE_ENABLED:
        return None, None
    try:
        from langfuse import Langfuse, observe
    except ImportError as exc:
        log.warning("langfuse_import_failed", error=str(exc), hint="pip install langfuse")
        return None, None
    try:
        client = Langfuse(
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
            host=LANGFUSE_HOST,
        )
        log.info("langfuse_initialized", host=LANGFUSE_HOST)
        return client, observe
    except Exception as exc:
        log.warning("langfuse_init_failed", error=str(exc))
        return None, None


def get_langfuse_client() -> Any:
    """Langfuse v4 client singleton — None ENV yoksa."""
    global _client, _observe_fn
    if _client is None and LANGFUSE_ENABLED:
        with _langfuse_lock:
            if _client is None:  # double-check — lock beklerken başka thread kurmuş olabilir
                _client, _observe_fn = _init_langfuse()
    return _client


def observe_node(
    as_type: Literal["span", "generation"] = "span",
    name: str | None = None,
) -> Callable[[_F], _F]:
    """Decorator: LangGraph node fonksiyonlarını Langfuse trace'ine ekle.

    ENV yoksa veya import başarısız ise no-op (orijinal fonksiyon döner).

    Args:
        as_type: "span" (varsayılan, ajan node) veya "generation" (LLM çağrısı)
        name: Trace'te görünecek isim (None → fonksiyon adı)
    """
    def decorator(fn: _F) -> _F:
        global _observe_fn
        # ENV yoksa → no-op
        if not LANGFUSE_ENABLED:
            return fn
        # Init lazy (test ortamı için her decorator'da kontrol)
        if _observe_fn is None:
            _client_local, observe = _init_langfuse()
            if observe is None:
                # Import veya init başarısız → no-op decorator
                return fn
            _observe_fn = observe
        try:
            decorated: _F = _observe_fn(as_type=as_type, name=name or fn.__name__)(fn)
            return decorated
        except Exception as exc:
            log.warning("observe_decorator_failed", fn=fn.__name__, error=str(exc))
            return fn
    return decorator


def observe_ask_request(name: str = "ask") -> Callable[[_F], _F]:
    """Top-level decorator: /ask endpoint için root trace başlat."""
    return observe_node(as_type="span", name=name)


def current_trace_id() -> str | None:
    """Aktif Langfuse trace ID'sini döner. Yoksa None.

    `AskResponse.trace_id` doldurmak için endpoint sonunda çağırılır.
    Frontend bu ID ile Langfuse dashboard'a deeplink üretebilir.
    """
    client = get_langfuse_client()
    if client is None:
        return None
    try:
        # v4 API: client.get_current_trace_id() veya context'ten oku
        if hasattr(client, "get_current_trace_id"):
            tid = client.get_current_trace_id()
            return str(tid) if tid is not None else None
        # Fallback: OTEL span context'inden
        from opentelemetry import trace
        span = trace.get_current_span()
        if span and span.get_span_context().trace_id:
            return f"{span.get_span_context().trace_id:032x}"
    except Exception as exc:
        log.debug("trace_id_extract_failed", error=str(exc))
    return None


def update_current_trace(
    user_id: str | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Aktif trace'in user_id/session_id/metadata field'larını günceller.

    Langfuse v4 `@observe()` ile başlayan trace'i request bağlamıyla zenginleştirir.
    """
    client = get_langfuse_client()
    if client is None:
        return
    try:
        if hasattr(client, "update_current_trace"):
            client.update_current_trace(
                user_id=user_id,
                session_id=session_id,
                metadata=metadata or {},
            )
    except Exception as exc:
        log.debug("trace_update_failed", error=str(exc))


def flush_langfuse() -> None:
    """Pending trace'leri Langfuse cloud'a gönder. Lifespan shutdown'da çağır."""
    client = get_langfuse_client()
    if client is None:
        return
    try:
        if hasattr(client, "flush"):
            client.flush()
            log.info("langfuse_flushed")
    except Exception as exc:
        log.warning("langfuse_flush_failed", error=str(exc))


# ============================================================================
# Geri uyumluluk shim: eski get_langfuse_handler() çağrıları için no-op döner.
# ask.py mevcut callback handler pattern'ini kullanıyorsa kırılmaz.
# Sprint-7+ shim'i kaldır.
# ============================================================================


def get_langfuse_handler(
    trace_name: str = "ask",
    user_id: str | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any:
    """DEPRECATED — Langfuse v2 CallbackHandler pattern.

    Langfuse v4'te bu pattern desteklenmiyor; @observe decorator kullan.
    Şimdilik trace_id metadata güncellemesi yapar, None döner.
    """
    _ = trace_name  # v2 imzasını koru (eski caller'lar geçiyor), v4'te kullanılmıyor
    if not LANGFUSE_ENABLED:
        return None
    # v4'te callback handler yok — sadece trace meta güncelle
    update_current_trace(user_id=user_id, session_id=session_id, metadata=metadata)
    return None


@functools.lru_cache(maxsize=1)
def _has_langfuse() -> bool:
    """Test-friendly: langfuse paketi import edilebilir mi?"""
    try:
        import langfuse  # noqa: F401
        return True
    except ImportError:
        return False


__all__ = (
    "LANGFUSE_ENABLED",
    "LANGFUSE_HOST",
    "current_trace_id",
    "flush_langfuse",
    "get_langfuse_client",
    "get_langfuse_handler",  # deprecated shim
    "observe_ask_request",
    "observe_node",
    "update_current_trace",
)
