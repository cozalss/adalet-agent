"""Pydantic şemaları — /ask request/response.

Sıfır halüsinasyon promise gereği response her zaman:
  - citation listesi (kaynak + URL)
  - güven skoru (0..1)
  - disclaimer (her cevap altında)
  - verdict (pass / retry / reject)

Reject durumunda answer = boilerplate "avukata danışın" template.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# Domain enum — agents.state.Domain ile aynı küme
Domain = Literal[
    "tuketici",
    "isHukuku",
    "kira",
    "icra",
    "trafik",
    "vergi",
    "tapu",
    "idari",
    "unknown",
]

Verdict = Literal["pass", "retry", "reject"]


class AskRequest(BaseModel):
    """Kullanıcı sorusu — tek alanlı minimal request.

    Multi-turn için `conversation_id` ver; session store geçmişi yükler.
    Multimodal (sesli/görsel) için /ask/multipart endpoint'i kullanın.
    """

    question: str = Field(..., min_length=3, max_length=2000, description="Vatandaşın hukuki sorusu")
    want_dilekce: bool = Field(False, description="Resmi dilekçe taslağı istenir mi?")
    want_tts: bool = Field(False, description="Cevabı sesli üret (TTS)")
    conversation_id: str | None = Field(
        None, max_length=128, description="Multi-turn için session anahtarı",
    )
    user_meta: dict[str, Any] | None = Field(None, description="Şehir, taraf, vb. opsiyonel metadata")
    stream: bool = Field(False, description="True → SSE stream'le aşama aşama dön")


class CitationSchema(BaseModel):
    """API yanıtındaki tek bir kaynak."""

    source_id: str
    doc_type: Literal["law", "case"]
    title: str
    snippet: str
    url: str
    score: float = Field(..., ge=0.0, le=1.0)


class ClaimSchema(BaseModel):
    """Verify'dan geçmiş iddia (transparency panel için)."""

    text: str
    cite_ids: list[str] = Field(default_factory=list)
    verified: bool
    verify_score: float
    verify_reason: str


class AskResponse(BaseModel):
    """Tam yanıt — UI buradan render eder."""

    answer: str = Field(..., description="Markdown formatlı son cevap (disclaimer dahil)")
    domain: Domain
    domain_confidence: float = Field(..., ge=0.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0, description="Genel güven skoru")
    verdict: Verdict
    citations: list[CitationSchema] = Field(default_factory=list)
    claims: list[ClaimSchema] = Field(default_factory=list)
    disclaimers: list[str] = Field(default_factory=list)
    debate_notes: str = ""
    retry_count: int = 0
    errors: list[str] = Field(default_factory=list)
    latency_ms: int = 0
    conversation_id: str | None = None
    audio_url: str | None = Field(
        None, description="want_tts=True ise sesli cevap URL'i (in-mem temp)",
    )
    trace_id: str | None = Field(
        None,
        description=(
            "Langfuse trace ID — debug/observability için. "
            "ENV ayarlı değilse None döner. Frontend bu ID ile dashboard linki üretebilir."
        ),
    )


class OCRUploadResponse(BaseModel):
    """POST /multimodal/ocr — belge fotoğrafı → metin."""

    text: str
    engine: str
    n_chars: int
    elapsed_ms: int
    error: str | None = None


class STTUploadResponse(BaseModel):
    """POST /multimodal/stt — sesli giriş → metin."""

    text: str
    language: str
    duration_s: float
    elapsed_ms: int
    error: str | None = None


class ErrorResponse(BaseModel):
    detail: str
    code: str = "ask_failed"


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"] = "ok"
    components: dict[str, str] = Field(default_factory=dict)
