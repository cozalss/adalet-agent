"""POST /ask — kullanıcı sorusunu LangGraph zincirine ver.

İki mod:
  POST /ask           → tek seferlik blocking JSON (AskResponse)
  POST /ask/stream    → SSE; her node bittiğinde event yayar

Sprint-5 ekleri:
  - conversation_id ile multi-turn session_store entegrasyonu
  - want_tts ile Piper TTS post-process (audio_url field'ı set edilir)

LangGraph zinciri compile-once; lazy singleton ile cache'lenir.
Langfuse trace opsiyonel (LANGFUSE_PUBLIC_KEY varsa).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from agents.graph import build_graph, make_initial_state
from agents.state import ConversationTurn
from api.audit import AuditEvent
from api.audit import emit as emit_audit
from api.limiter import ask_rate_for, limiter
from api.middleware.auth import Principal, authenticate
from api.middleware.sanitize import sanitize_question
from api.pii import mask_pii
from api.schemas import AskRequest, AskResponse, CitationSchema, ClaimSchema
from api.session_store import get_store
from core.observability import (
    current_trace_id,
    get_langfuse_handler,
    observe_ask_request,
    update_current_trace,
)

log = structlog.get_logger()
router = APIRouter(prefix="/ask", tags=["ask"])

_graph_singleton: Any = None


def _get_graph() -> Any:
    """Process-singleton compiled graph."""
    global _graph_singleton
    if _graph_singleton is None:
        _graph_singleton = build_graph()
    return _graph_singleton


def _new_conversation_id() -> str:
    """Yeni session için UUID4."""
    return uuid.uuid4().hex


async def _build_initial_with_session(req: AskRequest) -> tuple[dict, str]:
    """conversation_id ile chat_history'i yükle, initial state hazırla.

    Returns:
        (initial_state, conversation_id)
    """
    conv_id = req.conversation_id or _new_conversation_id()
    store = get_store()
    history = await store.get_history(conv_id) if req.conversation_id else []

    initial = make_initial_state(
        req.question,
        want_dilekce=req.want_dilekce,
        user_meta=req.user_meta,
    )
    initial["conversation_id"] = conv_id
    initial["chat_history"] = history
    initial["want_tts"] = req.want_tts
    return initial, conv_id


async def _persist_turn(
    conv_id: str, role: str, content: str, domain: str | None = None,
) -> None:
    """Session store'a tek tur yaz."""
    if not content:
        return
    store = get_store()
    turn: ConversationTurn = {"role": role, "content": content[:2000]}  # type: ignore[typeddict-item]
    if domain and domain != "unknown":
        turn["domain"] = domain  # type: ignore[typeddict-unknown-key]
    try:
        await store.append_turn(conv_id, turn)
    except Exception as exc:
        log.warning("session_persist_failed", conv_id=conv_id, error=str(exc))


@router.post("", response_model=AskResponse)
@limiter.limit(ask_rate_for)
@observe_ask_request(name="ask")
async def ask(
    request: Request, req: AskRequest,
    principal: Principal = Depends(authenticate),
) -> AskResponse:
    """Tek seferlik soru-cevap. Streaming için POST /ask/stream'i kullan.

    Rate limit: env `RATE_LIMIT_ASK` (default 10/minute). slowapi `Request`
    parametresine bağlı, decorator kwargs üzerinden tetiklenir.

    W6 hardening:
      - JWT/API-key auth (AUTH_ENABLED=1 ise)
      - Prompt-injection sanitize (HARD block → 400)
      - PII mask: kullanıcı sorusu session/audit'e PII'siz yazılır
      - Audit log: hash(question), domain, verdict
    """
    _ = request
    start = time.perf_counter()

    # W6.3 — sanitize (hard PI → 400)
    s_result = sanitize_question(req.question)
    if s_result.blocked:
        emit_audit(AuditEvent(
            event="ask_blocked_pi", principal=principal,
            question=req.question, conversation_id=req.conversation_id or "",
            errors=tuple(s_result.matched_hard),
        ))
        raise HTTPException(
            status_code=400, detail=f"prompt-injection: {s_result.reason}",
        )
    cleaned_question = s_result.cleaned_text

    # W6.4 — PII mask (persist+audit için)
    pii_result = mask_pii(cleaned_question)
    safe_for_log = pii_result.masked_text

    # Sanitize sonrası kalan metin LLM'e gider (PI temizlenmiş ama PII orijinal)
    sanitized_req = req.model_copy(update={"question": cleaned_question})

    graph = _get_graph()
    initial, conv_id = await _build_initial_with_session(sanitized_req)

    # W8.1 — Langfuse v4: @observe_ask_request decorator inner fn'i sarar, trace
    # otomatik açılır. update_current_trace ile user/session/metadata zenginleştir.
    update_current_trace(
        user_id=principal.sub,
        session_id=conv_id,
        metadata={"domain": initial.get("domain"), "principal_kind": principal.kind},
    )
    # Backward-compat: get_langfuse_handler v4'te None döner (callback handler yok)
    _ = get_langfuse_handler  # imported for legacy callers; v4 no-op

    try:
        final_state = await graph.ainvoke(initial)
    except Exception as exc:
        emit_audit(AuditEvent(
            event="ask_pipeline_failed", principal=principal,
            question=safe_for_log, conversation_id=conv_id,
            errors=(str(exc),),
        ))
        log.exception("ask_pipeline_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Pipeline hata: {exc!s}") from exc

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    response = _state_to_response(final_state, elapsed_ms, conv_id)
    # v4 — trace_id'yi yanıta ekle (frontend Langfuse dashboard linki üretebilir)
    response = response.model_copy(update={"trace_id": current_trace_id()})

    # Persist ile audit PII'siz
    await _persist_turn(conv_id, "user", safe_for_log, final_state.get("domain"))
    await _persist_turn(conv_id, "assistant", response.answer, final_state.get("domain"))
    emit_audit(AuditEvent(
        event="ask_response", principal=principal,
        question=safe_for_log,
        domain=response.domain, verdict=response.verdict,
        conversation_id=conv_id, latency_ms=elapsed_ms,
        errors=tuple(response.errors or ()),
    ))

    return response


@router.post("/stream")
@limiter.limit(ask_rate_for)
async def ask_stream(
    request: Request, req: AskRequest,
    principal: Principal = Depends(authenticate),
) -> StreamingResponse:
    """SSE — her node bittiğinde event yay. Long-running latency UX için.

    Sprint-6 fix: graph tek seferlik koşar — `astream(values)` ile her node
    çıktığında akümülasyonu yayınla, son values event'inden final state'i
    üret. Daha önce astream → ainvoke ile iki kez çalıştırılıyordu (2x maliyet,
    non-deterministik LLM çıktısı riski).

    PII: persist `safe_for_log` (PII-masked) ile yapılır, raw soru asla
    session'a yazılmaz.
    """
    _ = request  # slowapi request — yan etki için tutuluyor
    s_result = sanitize_question(req.question)
    if s_result.blocked:
        emit_audit(AuditEvent(
            event="ask_stream_blocked_pi", principal=principal,
            question=req.question, conversation_id=req.conversation_id or "",
            errors=tuple(s_result.matched_hard),
        ))
        raise HTTPException(status_code=400, detail=f"prompt-injection: {s_result.reason}")

    cleaned_question = s_result.cleaned_text
    safe_for_log = mask_pii(cleaned_question).masked_text  # PII-masked persist için
    sanitized_req = req.model_copy(update={"question": cleaned_question})
    graph = _get_graph()
    initial, conv_id = await _build_initial_with_session(sanitized_req)

    async def event_source() -> AsyncIterator[str]:
        start = time.perf_counter()
        final_state: dict = {}
        try:
            # stream_mode="values" → her node sonrası tüm state döner; en son
            # event final_state olur. İkinci graph.ainvoke gereksiz.
            async for state in graph.astream(initial, stream_mode="values"):
                final_state = state
                payload = {
                    "keys": list(state.keys()),
                    "domain": state.get("domain"),
                    "retry_count": state.get("retry_count", 0),
                }
                yield f"event: node\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

            elapsed = int((time.perf_counter() - start) * 1000)
            resp = _state_to_response(final_state, elapsed, conv_id)
            yield f"event: final\ndata: {resp.model_dump_json()}\n\n"

            # PII-masked persist (raw req.question DEĞIL)
            await _persist_turn(conv_id, "user", safe_for_log, final_state.get("domain"))
            await _persist_turn(conv_id, "assistant", resp.answer, final_state.get("domain"))
            emit_audit(AuditEvent(
                event="ask_stream_response", principal=principal,
                question=safe_for_log,
                domain=resp.domain, verdict=resp.verdict,
                conversation_id=conv_id, latency_ms=elapsed,
                errors=tuple(resp.errors or ()),
            ))
        except asyncio.CancelledError:
            log.warning("ask_stream_cancelled", conv_id=conv_id)
            raise
        except Exception as exc:
            log.exception("ask_stream_failed", error=str(exc))
            emit_audit(AuditEvent(
                event="ask_stream_failed", principal=principal,
                question=safe_for_log, conversation_id=conv_id,
                errors=(str(exc),),
            ))
            err_payload = {"detail": str(exc), "code": "stream_failed"}
            yield f"event: error\ndata: {json.dumps(err_payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/session/{conversation_id}")
async def clear_session(
    conversation_id: str,
    principal: Principal = Depends(authenticate),
) -> dict:
    """Konuşma geçmişini sil — kullanıcı 'yeni konu' başlatınca."""
    _ = principal
    store = get_store()
    await store.clear(conversation_id)
    return {"cleared": conversation_id}


def _state_to_response(
    state: dict, elapsed_ms: int, conv_id: str | None = None,
) -> AskResponse:
    """LangGraph final state → API response."""
    refs = list(state.get("mevzuat_refs", [])) + list(state.get("emsal_refs", []))
    citations = [
        CitationSchema(
            source_id=r["source_id"],
            doc_type=r["doc_type"],
            title=r["title"],
            snippet=r["snippet"][:500],
            url=r["url"],
            score=min(max(float(r["score"]), 0.0), 1.0),
        )
        for r in refs
    ]
    claims = [
        ClaimSchema(
            text=c["text"],
            cite_ids=c.get("cite_ids", []),
            verified=c.get("verified", False),
            verify_score=float(c.get("verify_score", 0.0)),
            verify_reason=c.get("verify_reason", ""),
        )
        for c in state.get("verified_claims", []) or state.get("claims", [])
    ]
    return AskResponse(
        answer=state.get("response", ""),
        domain=state.get("domain", "unknown"),
        domain_confidence=float(state.get("domain_confidence", 0.0)),
        confidence=float(state.get("confidence", 0.0)),
        verdict=state.get("debate_verdict", "pass"),
        citations=citations,
        claims=claims,
        disclaimers=state.get("disclaimers", []),
        debate_notes=state.get("debate_notes", ""),
        retry_count=int(state.get("retry_count", 0)),
        errors=state.get("errors", []),
        latency_ms=elapsed_ms,
        conversation_id=conv_id or state.get("conversation_id"),
    )
