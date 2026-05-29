"""Audit log — Sprint-4 W6.5.

Ayrı bir 'audit' stream (structlog) — production'da `audit.log` dosyasına yazılır.
PII içermez: question metni yerine `hash_question()` fingerprint kullanılır.

Alanlar:
  - ts (auto), event ("ask_request", "ask_response", "session_clear")
  - principal_kind ("user" | "api_key" | "anonymous")
  - principal_sub (user.sub veya api_key label)
  - question_hash (16 hex), question_len, domain, verdict, conv_id
  - latency_ms, errors

Tasarım:
- Production: stdout JSON satır akışı (Filebeat / Vector → object storage)
- Local dev: AUDIT_LOG_DISABLED=1 → no-op
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import Any

import structlog

from api.middleware.auth import Principal
from api.pii import fingerprint, hash_question

AUDIT_LOG_DISABLED = os.getenv("AUDIT_LOG_DISABLED", "0").lower() in {"1", "true", "yes"}


def _build_audit_logger() -> Any:
    """Ayrı audit logger — root logger'a karışmaz."""
    py_logger = logging.getLogger("adalet.audit")
    if not py_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        py_logger.addHandler(handler)
        py_logger.setLevel(logging.INFO)
        py_logger.propagate = False
    return structlog.wrap_logger(
        py_logger,
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
    )


_audit_log = _build_audit_logger()


@dataclass(frozen=True)
class AuditEvent:
    event: str
    principal: Principal
    question: str = ""
    domain: str = ""
    verdict: str = ""
    conversation_id: str = ""
    latency_ms: int = 0
    errors: tuple[str, ...] = ()


def emit(event: AuditEvent) -> None:
    """Audit event'i loga yaz (PII'siz)."""
    if AUDIT_LOG_DISABLED:
        return
    payload = {
        "audit_event": event.event,
        "principal_kind": event.principal.kind,
        # KVKK: ham sub (email/beta:... içerebilir) YERİNE deterministik
        # fingerprint — gruplanabilir ama kimliksiz (feedback/ask ile tutarlı).
        "principal_sub_hash": fingerprint(event.principal.sub),
        "question_hash": hash_question(event.question) if event.question else "",
        "question_len": len(event.question),
        "domain": event.domain,
        "verdict": event.verdict,
        "conversation_id": event.conversation_id,
        "latency_ms": event.latency_ms,
        "n_errors": len(event.errors),
    }
    _audit_log.info("audit", **payload)


__all__ = ("AUDIT_LOG_DISABLED", "AuditEvent", "emit")
