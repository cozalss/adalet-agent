"""structlog tek yer config — Sprint-4 W8.5.

Processor zinciri:
  1. add_log_level (info/warning/error)
  2. TimeStamper (iso8601 utc)
  3. _redact_sensitive — hassas anahtarları "[REDACTED]" ile değiştir
  4. _mask_pii_in_strings — string değerlerde PII pattern → mask
  5. JSONRenderer (production) veya ConsoleRenderer (dev)

PROD log streamı object storage'a giden Filebeat/Vector için JSON şarttır.
Dev'de okunabilirlik için renkli console.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog

# Sensitive key allow-list — log payload'larında bu anahtarlar redact
SENSITIVE_KEYS: frozenset[str] = frozenset({
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "authorization", "auth", "jwt", "bearer", "private_key",
    "refresh_token", "access_token", "session_token",
    "redis_password", "qdrant_api_key", "jwt_secret",
    "langfuse_secret_key", "langfuse_public_key", "openai_api_key",
    "cookie", "set-cookie",
})

LOG_FORMAT = os.getenv("LOG_FORMAT", "json")  # "json" | "console"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def _redact_sensitive(_logger: Any, _method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Hassas anahtarları '[REDACTED]' ile değiştir.

    Case-insensitive key match. Nested dict desteği var (recursive).
    """
    out: dict[str, Any] = {}
    for key, value in event_dict.items():
        kl = str(key).lower()
        if kl in SENSITIVE_KEYS or any(s in kl for s in ("secret", "password", "token", "_key")):
            out[key] = "[REDACTED]"
        elif isinstance(value, dict):
            out[key] = _redact_dict(value)
        else:
            out[key] = value
    return out


def _redact_dict(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        kl = str(k).lower()
        if kl in SENSITIVE_KEYS or any(s in kl for s in ("secret", "password", "token", "_key")):
            out[k] = "[REDACTED]"
        elif isinstance(v, dict):
            out[k] = _redact_dict(v)
        else:
            out[k] = v
    return out


def _mask_pii_in_strings(_logger: Any, _method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """String değerlerde PII pattern'larını mask."""
    # Lazy import — log modülü PII modülünden bağımsız çağrılabilsin
    try:
        from api.pii import mask_pii
    except ImportError:
        return event_dict
    for key, value in list(event_dict.items()):
        if isinstance(value, str) and len(value) > 8:
            result = mask_pii(value)
            if result.has_pii:
                event_dict[key] = result.masked_text
                event_dict[f"{key}_pii_counts"] = result.counts
    return event_dict


def configure_logging() -> None:
    """Tek seferlik global config — main.py lifespan startup'unda çağrılır."""
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        _redact_sensitive,
        _mask_pii_in_strings,
    ]

    if LOG_FORMAT == "console":
        renderer: Any = structlog.dev.ConsoleRenderer(colors=False)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, LOG_LEVEL, logging.INFO),
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


__all__ = ("LOG_FORMAT", "LOG_LEVEL", "SENSITIVE_KEYS", "configure_logging")
