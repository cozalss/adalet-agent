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


def _is_sensitive_key(key: Any) -> bool:
    """Anahtar hassas mı? Case-insensitive + substring (secret/password/token/_key)."""
    kl = str(key).lower()
    return kl in SENSITIVE_KEYS or any(
        s in kl for s in ("secret", "password", "token", "_key")
    )


def _redact_value(value: Any) -> Any:
    """Değere recursive in — dict VE list içindeki hassas anahtarları redact et."""
    if isinstance(value, dict):
        return _redact_dict(value)
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    return value


def _redact_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Hassas anahtarları '[REDACTED]'; dict+list değerlere recursive in."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        out[k] = "[REDACTED]" if _is_sensitive_key(k) else _redact_value(v)
    return out


def _redact_sensitive(
    _logger: Any, _method_name: str, event_dict: dict[str, Any],
) -> dict[str, Any]:
    """structlog processor — hassas anahtarları '[REDACTED]' ile değiştir.

    Case-insensitive key match. Nested dict VE list desteği var (recursive):
    örn. {"items": [{"token": "x"}]} listesi içindeki token de redact edilir.
    """
    return _redact_dict(event_dict)


# KVKK kritik: PII modülü import edilemezse log'lar maskesiz akar. Bunu sessizce
# geçme — bir kez stdlib logging ile CRITICAL uyar (structlog henüz config
# edilmemiş olabilir, döngüye girmemek için stdlib).
_pii_unavailable_warned = False


def _warn_pii_unavailable(exc: Exception) -> None:
    global _pii_unavailable_warned
    if not _pii_unavailable_warned:
        _pii_unavailable_warned = True
        logging.getLogger(__name__).critical(
            "PII maskeleme modülü yüklenemedi — loglar maskesiz akıyor (KVKK riski): %s",
            exc,
        )


def _mask_pii_nested(value: Any, mask_fn: Any) -> Any:
    """dict/list/string içine recursive in, string'lerde PII mask uygula."""
    if isinstance(value, str):
        if len(value) > 8:
            result = mask_fn(value)
            if result.has_pii:
                return result.masked_text
        return value
    if isinstance(value, dict):
        return {k: _mask_pii_nested(v, mask_fn) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_pii_nested(v, mask_fn) for v in value]
    return value


def _mask_pii_in_strings(
    _logger: Any, _method_name: str, event_dict: dict[str, Any],
) -> dict[str, Any]:
    """String değerlerde PII pattern'larını mask — nested dict/list dahil."""
    # Lazy import — log modülü PII modülünden bağımsız çağrılabilsin
    try:
        from api.pii import mask_pii
    except ImportError as exc:
        _warn_pii_unavailable(exc)
        return event_dict
    for key, value in list(event_dict.items()):
        if isinstance(value, str):
            if len(value) > 8:
                result = mask_pii(value)
                if result.has_pii:
                    event_dict[key] = result.masked_text
                    event_dict[f"{key}_pii_counts"] = result.counts
        elif isinstance(value, (dict, list)):
            # Nested yapı içindeki PII de maskelensin (liste/dict içi TCKN vs).
            event_dict[key] = _mask_pii_nested(value, mask_pii)
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
