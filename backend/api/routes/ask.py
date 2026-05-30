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
import contextlib
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from fastapi.responses import StreamingResponse

from agents.config import get_ask_graph_timeout_s
from agents.graph import build_graph, make_initial_state
from agents.state import ConversationTurn
from api.audit import AuditEvent
from api.audit import emit as emit_audit
from api.dilekce_store import store_pdf
from api.limiter import ask_rate_for, limiter
from api.middleware.auth import Principal, authenticate
from api.middleware.sanitize import sanitize_question
from api.pii import fingerprint, mask_pii
from api.schemas import (
    AskRequest,
    AskResponse,
    CitationSchema,
    ClaimSchema,
    PredictionSchema,
)
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
SSE_SCHEMA_VERSION = 1


def _get_graph() -> Any:
    """Process-singleton compiled graph."""
    global _graph_singleton
    if _graph_singleton is None:
        _graph_singleton = build_graph()
    return _graph_singleton


def _new_conversation_id() -> str:
    """Yeni session için UUID4."""
    return uuid.uuid4().hex


def _merge_history_facts(history: list[ConversationTurn]) -> dict[str, Any]:
    """Session geçmişindeki structured olguları oldest->newest birleştir."""
    merged: dict[str, Any] = {}
    for turn in history:
        facts = turn.get("case_facts") or {}
        if isinstance(facts, dict):
            merged.update({k: v for k, v in facts.items() if str(v).strip()})
    return merged


def _sse_event(event: str, payload: dict[str, Any]) -> str:
    """Tek SSE serializer. `final` dışındaki payload'lar v=1 sözleşmesini taşır."""
    data = {"v": SSE_SCHEMA_VERSION, **payload}
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


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
    initial["case_facts"] = _merge_history_facts(history)
    initial["want_tts"] = req.want_tts
    return initial, conv_id


async def _persist_turn(
    conv_id: str,
    role: str,
    content: str,
    domain: str | None = None,
    case_facts: dict[str, Any] | None = None,
) -> None:
    """Session store'a tek tur yaz."""
    if not content:
        return
    store = get_store()
    turn: ConversationTurn = {"role": role, "content": content[:2000]}  # type: ignore[typeddict-item]
    if domain and domain != "unknown":
        turn["domain"] = domain  # type: ignore[typeddict-unknown-key]
    if case_facts:
        turn["case_facts"] = {
            str(k): v for k, v in case_facts.items() if str(v).strip()
        }  # type: ignore[typeddict-unknown-key]
    try:
        await store.append_turn(conv_id, turn)
    except Exception as exc:
        log.warning("session_persist_failed", conv_id=conv_id, error=str(exc))


async def _bind_or_verify_owner(conv_id: str, principal: Principal) -> None:
    """IDOR koruması — conversation'ı sahibine bağla / sahipliği doğrula.

    - Anonim (AUTH_ENABLED=0, dev/test) → no-op; herkes 'dev', IDOR yok.
    - İlk erişim → owner = fingerprint(sub) bağlanır (set-if-absent).
    - Sonraki erişim → mevcut owner ≠ çağıran fingerprint ise 403.

    Owner ham sub değil fingerprint olarak saklanır (KVKK — Redis'te email yok).
    Store hatası akışı bloke etmesin (best-effort); ownership ihlali ise 403 yükselt.
    """
    if principal.anonymous:
        return
    owner = fingerprint(principal.sub)
    store = get_store()
    try:
        existing = await store.get_owner(conv_id)
    except Exception as exc:
        # Fail-CLOSED: sahipliği doğrulayamıyorsak (store down) erişime izin
        # VERME — fail-open bir IDOR penceresi açardı (saldırgan store'u
        # düşürüp başkasının conv_id'sine erişebilir). 503 → geçici hata.
        log.warning("owner_check_failed", conv_id=conv_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Oturum doğrulaması geçici olarak yapılamıyor, tekrar deneyin.",
        ) from exc
    if existing is None:
        with contextlib.suppress(Exception):
            await store.set_owner_if_absent(conv_id, owner)
        return
    if existing != owner:
        emit_audit(AuditEvent(
            event="session_idor_blocked", principal=principal,
            conversation_id=conv_id,
        ))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu oturuma erişim yetkiniz yok.",
        )


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
    # IDOR: conversation'ı sahibine bağla / sahipliği doğrula (resume'da başkasının
    # oturumuna erişim 403). Anonim modda no-op.
    await _bind_or_verify_owner(conv_id, principal)

    # W8.1 — Langfuse v4: @observe_ask_request decorator inner fn'i sarar, trace
    # otomatik açılır. update_current_trace ile user/session/metadata zenginleştir.
    update_current_trace(
        user_id=principal.sub,
        session_id=conv_id,
        metadata={"domain": initial.get("domain"), "principal_kind": principal.kind},
    )
    # Backward-compat: get_langfuse_handler v4'te None döner (callback handler yok)
    _ = get_langfuse_handler  # imported for legacy callers; v4 no-op

    timeout_s = get_ask_graph_timeout_s()
    try:
        if timeout_s > 0:
            final_state = await asyncio.wait_for(graph.ainvoke(initial), timeout=timeout_s)
        else:
            final_state = await graph.ainvoke(initial)
    except TimeoutError as exc:
        # Hung graph üst sınırı aştı — worker'ı süresiz tutmadan 504 dön.
        emit_audit(AuditEvent(
            event="ask_pipeline_timeout", principal=principal,
            question=safe_for_log, conversation_id=conv_id,
            errors=(f"timeout>{timeout_s}s",),
        ))
        log.warning("ask_pipeline_timeout", conv_id=conv_id, timeout_s=timeout_s)
        raise HTTPException(
            status_code=504,
            detail="İstek zaman aşımına uğradı, lütfen tekrar deneyin.",
        ) from exc
    except Exception as exc:
        emit_audit(AuditEvent(
            event="ask_pipeline_failed", principal=principal,
            question=safe_for_log, conversation_id=conv_id,
            errors=(str(exc),),
        ))
        log.exception("ask_pipeline_failed", error=str(exc))
        # İç exception detayını (dosya yolu, modül, bağlantı string'i) istemciye
        # sızdırma — tam trace yalnız log'a/audit'e gider.
        raise HTTPException(
            status_code=500,
            detail="İstek işlenemedi, lütfen tekrar deneyin.",
        ) from exc

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    # Dilekçe Ajanı PDF üretmişse in-memory cache'e koy (15 dk TTL); frontend
    # /api/dilekce/{conv_id} ile indirir. KVKK + IDOR: owner_sub ile bağlanır,
    # principal.sub == owner_sub kontrolü route'da yapılır.
    if final_state.get("dilekce_pdf_bytes"):
        store_pdf(
            conversation_id=conv_id,
            pdf_bytes=final_state["dilekce_pdf_bytes"],
            filename=final_state.get("dilekce_filename") or "dilekce.pdf",
            template_id=final_state.get("dilekce_template_id") or "",
            owner_sub=principal.sub,
        )
    response = _state_to_response(final_state, elapsed_ms, conv_id)
    # v4 — trace_id'yi yanıta ekle (frontend Langfuse dashboard linki üretebilir)
    response = response.model_copy(update={"trace_id": current_trace_id()})

    # Persist ile audit PII'siz
    await _persist_turn(
        conv_id,
        "user",
        safe_for_log,
        final_state.get("domain"),
        final_state.get("case_facts") or None,
    )
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
    # IDOR: sahip bağla / doğrula (stream başlamadan; mismatch → 403).
    await _bind_or_verify_owner(conv_id, principal)

    async def event_source() -> AsyncIterator[str]:
        start = time.perf_counter()
        final_state: dict = {}
        timeout_s = get_ask_graph_timeout_s()
        # /ask ile aynı uçtan uca tavan; 0 = devre dışı. nullcontext 3.10+ async
        # CM olarak çalışır → astream döngüsünü tek kopyayla sarmalar.
        guard: Any = asyncio.timeout(timeout_s) if timeout_s > 0 else contextlib.nullcontext()
        # Ara event sentinel'leri — her event bir kez gönderilir.
        _sent_triage = False
        _sent_sources = False
        _sent_drafting = False
        _sent_clarify = False
        try:
            # stream_mode="values" → her node sonrası tüm state döner; en son
            # event final_state olur. İkinci graph.ainvoke gereksiz.
            async with guard:
                async for state in graph.astream(initial, stream_mode="values"):
                    final_state = state
                    # NOT: iç state anahtarlarını (list(state.keys())) istemciye
                    # yayma — iç şema sızıntısı. Frontend yalnız ilerleme sinyali.
                    payload = {
                        "domain": state.get("domain"),
                        "retry_count": state.get("retry_count", 0),
                    }
                    yield _sse_event("node", payload)

                    # --- Algılanan gecikme azaltma: ara ilerleme event'leri ---
                    # Triaj tamamlandı → intent + domain belli (2-3s'de kullanıcıya
                    # bilgi). response_intent set olur olmaz yayılır; böylece
                    # smalltalk/redirect/clarify yolları da (domain=unknown olsa bile)
                    # frontend'e erken sinyal verir — yol türünü ayırt edebilir.
                    intent = state.get("response_intent")
                    if not _sent_triage and intent:
                        _sent_triage = True
                        triage_evt = {
                            "intent": intent,
                            "domain": state.get("domain"),
                            "confidence": state.get("domain_confidence", 0.0),
                        }
                        yield _sse_event("triage", triage_evt)

                    # Netleştirme yolu → frontend soruları "yanıt" değil "soru" olarak
                    # render etsin (stalled-answer ile karışmasın).
                    if not _sent_clarify and state.get("clarify_response"):
                        _sent_clarify = True
                        n_q = len(state.get("clarifying_questions") or [])
                        yield _sse_event("clarify", {"questions": n_q})

                    # Kaynaklar geldi → kaynak sayısı belli
                    mevz = state.get("mevzuat_refs") or []
                    emsal = state.get("emsal_refs") or []
                    if not _sent_sources and (mevz or emsal):
                        _sent_sources = True
                        sources_evt = {"count": len(mevz) + len(emsal)}
                        yield _sse_event("sources", sources_evt)

                    # Draft hazır → cevap yazılıyor
                    if not _sent_drafting and state.get("draft_response"):
                        _sent_drafting = True
                        yield _sse_event("drafting", {})

            elapsed = int((time.perf_counter() - start) * 1000)
            resp = _state_to_response(final_state, elapsed, conv_id)
            yield f"event: final\ndata: {resp.model_dump_json()}\n\n"

            # PII-masked persist (raw req.question DEĞIL)
            await _persist_turn(
                conv_id,
                "user",
                safe_for_log,
                final_state.get("domain"),
                final_state.get("case_facts") or None,
            )
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
        except TimeoutError:
            log.warning("ask_stream_timeout", conv_id=conv_id, timeout_s=timeout_s)
            emit_audit(AuditEvent(
                event="ask_stream_timeout", principal=principal,
                question=safe_for_log, conversation_id=conv_id,
                errors=(f"timeout>{timeout_s}s",),
            ))
            err_payload = {"detail": "İstek zaman aşımına uğradı", "code": "stream_timeout"}
            yield _sse_event("error", err_payload)
        except Exception as exc:
            log.exception("ask_stream_failed", error=str(exc))
            emit_audit(AuditEvent(
                event="ask_stream_failed", principal=principal,
                question=safe_for_log, conversation_id=conv_id,
                errors=(str(exc),),
            ))
            # İç exception detayını SSE ile istemciye sızdırma — log/audit yeterli.
            err_payload = {"detail": "İstek işlenemedi", "code": "stream_failed"}
            yield _sse_event("error", err_payload)

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
    conversation_id: str = Path(
        ...,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
    principal: Principal = Depends(authenticate),
) -> dict:
    """Konuşma geçmişini sil — kullanıcı 'yeni konu' başlatınca.

    conversation_id Path pattern ile kısıtlı ([A-Za-z0-9_-], 8-128) — Redis key
    enjeksiyonu / path-traversal denemelerini (`*`, `:`, `/`) 422 ile reddeder.

    IDOR koruması: owner binding ile yalnız oturum sahibi silebilir. Başkasının
    conversation_id'sini bilen kullanıcı 403 alır (auth açıkken).
    """
    await _bind_or_verify_owner(conversation_id, principal)
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
    pred = state.get("prediction")
    prediction = (
        PredictionSchema(
            verdict_class=pred["verdict_class"],
            confidence=float(pred["confidence"]),
            similar_case_ids=list(pred.get("similar_case_ids", [])),
            reasoning=pred.get("reasoning", ""),
        )
        if pred
        else None
    )
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
        prediction=prediction,
        errors=state.get("errors", []),
        latency_ms=elapsed_ms,
        conversation_id=conv_id or state.get("conversation_id"),
    )
