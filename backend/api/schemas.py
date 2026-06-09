"""Pydantic şemaları — /ask request/response.

Sıfır halüsinasyon promise gereği response her zaman:
  - citation listesi (kaynak + URL)
  - güven skoru (0..1)
  - disclaimer (her cevap altında)
  - verdict (pass / retry / reject)

Reject durumunda answer = boilerplate "avukata danışın" template.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# user_meta sınırları — sınırsız nested dict DoS'unu önle (deserializasyon
# bellek/CPU baskısı). Opsiyonel metadata; küçük key:value beklenir.
_MAX_USER_META_KEYS = 20
_MAX_USER_META_BYTES = 4096

# OCR belge eki sınırları — istemci /multimodal/ocr ile metni önceden alır,
# burada yapılandırılmış olarak gönderir. DoS guard: belge sayısı + metin boyu.
_MAX_ATTACHMENTS = 5
_MAX_ATTACHMENT_TEXT = 10000   # ~10K char/belge (uzun sözleşme/tebligat)


class ImageAttachmentInput(BaseModel):
    """OCR'lanmış belge — istemci POST /multimodal/ocr çıktısını buraya koyar.

    Yalnız metin + meta; ham görüntü /ask'a gelmez (OCR ayrı endpoint'te yapılır,
    sonuç metni burada case_facts çıkarımına beslenir).
    """

    filename: str = Field("belge", max_length=256)
    ocr_engine: str = Field("tesseract", max_length=32)
    text: str = Field(..., max_length=_MAX_ATTACHMENT_TEXT)
    n_chars: int = Field(0, ge=0)

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
        None, max_length=128,
        # Güvenlik (denetim 2026-06-04): char-sınıfı kısıtı → ':'/'*' gibi Redis özel
        # karakterleri session key'ine (adalet:session:{id}) sızamaz (key injection /
        # namespace kirliliği). DELETE /ask/session/{id} ve frontend ile aynı pattern.
        pattern=r"^[A-Za-z0-9_-]+$",
        description="Multi-turn için session anahtarı (yalnız harf/rakam/_-)",
    )
    user_meta: dict[str, Any] | None = Field(None, description="Şehir, taraf, vb. opsiyonel metadata")
    stream: bool = Field(False, description="True → SSE stream'le aşama aşama dön")
    image_attachments: list[ImageAttachmentInput] | None = Field(
        None, description="OCR'lanmış belge metinleri (case_facts çıkarımına beslenir)",
    )

    @field_validator("image_attachments")
    @classmethod
    def _bound_attachments(
        cls, v: list[ImageAttachmentInput] | None,
    ) -> list[ImageAttachmentInput] | None:
        """Belge sayısını sınırla (DoS guard)."""
        if v and len(v) > _MAX_ATTACHMENTS:
            raise ValueError(f"En fazla {_MAX_ATTACHMENTS} belge eklenebilir")
        return v

    @field_validator("user_meta")
    @classmethod
    def _bound_user_meta(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        """Anahtar sayısı + serileştirilmiş boyutu sınırla (DoS guard)."""
        if v is None:
            return v
        if len(v) > _MAX_USER_META_KEYS:
            raise ValueError(f"user_meta en fazla {_MAX_USER_META_KEYS} anahtar içerebilir")
        if len(json.dumps(v, ensure_ascii=False)) > _MAX_USER_META_BYTES:
            raise ValueError(f"user_meta çok büyük (max {_MAX_USER_META_BYTES} bayt)")
        return v


# Güvenlik: citation URL'leri yalnız bilinen TR-hukuk kaynak domain'lerinden olabilir.
# Qdrant payload'ı zehirlense (source_url='http://evil/...') kullanıcıya sahte 'Yargıtay
# linki' sunulmaz — open-redirect/phishing guard. Subdomain'ler endswith ile kapsanır.
_ALLOWED_CITATION_DOMAINS = (
    "mevzuat.gov.tr", "yargitay.gov.tr", "danistay.gov.tr",
    "resmigazete.gov.tr", "adalet.gov.tr", "uyap.gov.tr",
)


class CitationSchema(BaseModel):
    """API yanıtındaki tek bir kaynak."""

    source_id: str
    doc_type: Literal["law", "case"]
    title: str
    snippet: str
    url: str
    score: float = Field(..., ge=0.0, le=1.0)

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        """Tanınmayan/zararlı host → boş string (link gösterilmez). javascript:/data: de düşer."""
        if not v:
            return ""
        from urllib.parse import urlparse
        try:
            parsed = urlparse(v)
        except ValueError:
            return ""
        if parsed.scheme not in {"http", "https"}:
            return ""
        host = (parsed.hostname or "").lower()
        if any(host == d or host.endswith("." + d) for d in _ALLOWED_CITATION_DOMAINS):
            return v
        return ""


class ClaimSchema(BaseModel):
    """Verify'dan geçmiş iddia (transparency panel için)."""

    text: str
    cite_ids: list[str] = Field(default_factory=list)
    verified: bool
    verify_score: float
    verify_reason: str


class PredictionSchema(BaseModel):
    """Dava sonucu tahmini — opsiyonel 8. ajan (tahmin_node) çıktısı.

    KRİTİK: Bu bir TAHMİN, mahkeme garantisi değildir. `confidence` ≤ 0.85
    (kesinlik ima etmez). 'belirsiz' = yeterli/uyumlu emsal sinyali yok.
    """

    verdict_class: Literal["kazandi", "kaybetti", "kismi", "belirsiz"]
    confidence: float = Field(..., ge=0.0, le=1.0)
    similar_case_ids: list[str] = Field(default_factory=list)
    reasoning: str = ""
    disclaimer: str = (
        "Bu tahmin geçmiş Yargıtay kararlarından türetilmiş istatistiksel bir "
        "tahmindir; mahkeme sonucu garantisi DEĞİLDİR. Kesin değerlendirme için "
        "bir avukata danışın."
    )


class AskResponse(BaseModel):
    """Tam yanıt — UI buradan render eder."""

    answer: str = Field(..., description="Markdown formatlı son cevap (disclaimer dahil)")
    domain: Domain
    domain_confidence: float = Field(..., ge=0.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0, description="Genel güven skoru")
    confidence_label: str | None = Field(
        None,
        description=(
            "İnsan-okunur güven etiketi: 'Yüksek güven' / 'Orta güven' / 'Dikkatli olun'. "
            "Hukuki yanıt yoksa (sohbet/yönlendirme/reddedildi) None."
        ),
    )
    n_verified_claims: int = Field(
        0, ge=0, description="Doğrulanmış iddia sayısı (halüsinasyon kalkanını geçti).",
    )
    n_total_claims: int = Field(
        0, ge=0, description="Toplam iddia sayısı. UI 'n_verified/n_total iddia doğrulandı' gösterir.",
    )
    verdict: Verdict
    response_intent: str | None = Field(
        None,
        description=(
            "Yanıt türü: legal_answer / smalltalk / redirect / out_of_scope_sensitive / "
            "needs_clarification. Frontend ton seçer (smalltalk/redirect → hafif baloncuk, "
            "soğuk RejectCard değil)."
        ),
    )
    citations: list[CitationSchema] = Field(default_factory=list)
    claims: list[ClaimSchema] = Field(default_factory=list)
    disclaimers: list[str] = Field(default_factory=list)
    debate_notes: str = ""
    retry_count: int = 0
    prediction: PredictionSchema | None = Field(
        None, description="Opsiyonel dava sonucu tahmini (PREDICTIVE_ENABLED).",
    )
    errors: list[str] = Field(default_factory=list)
    latency_ms: int = 0
    conversation_id: str | None = None
    has_dilekce: bool = Field(
        False,
        description=(
            "Dilekçe Ajanı bu yanıt için PDF/DOCX üretti mi? Frontend indirme "
            "barını yalnız True iken gösterir (want_dilekce=True istendiğinde)."
        ),
    )
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
    """POST /multimodal/ocr — belge fotoğrafı → metin.

    KVKK: `text` kullanıcının kendi belgesinin metnidir (kendisine döner, sızıntı
    değil) ama içinde TCKN/IBAN/telefon olabilir. `pii_detected` bayrağı istemciyi
    uyarır; `pii_counts` tespit edilen tür sayılarını verir. Metin BOZULMAZ
    (kullanıcı soruyu sormak için tam metne ihtiyaç duyar).
    """

    text: str
    engine: str
    n_chars: int
    elapsed_ms: int
    error: str | None = None
    pii_detected: bool = False
    pii_counts: dict[str, int] = Field(default_factory=dict)
    # OCR kalite sinyali (#20): ortalama word-confidence 0..1 (Tesseract; Qwen-VL'de None).
    # low_confidence True → istemci "metni kontrol edin" uyarısı gösterebilir; bozuk taramada
    # ajanların kesin hukuki çıkarım yapması riskini azaltır.
    confidence: float | None = None
    low_confidence: bool = False


class STTUploadResponse(BaseModel):
    """POST /multimodal/stt — sesli giriş → metin.

    PII: kullanıcı 'TC kimliğim 123…, telefonum 0555…' diye sesli okuyabilir. OCR ile
    SİMETRİK olarak `pii_detected`/`pii_counts` bayrakları transkriptteki TCKN/telefon/
    IBAN'ı istemciye uyarır (metin BOZULMAZ — kullanıcının kendi girdisi).
    """

    text: str
    language: str
    duration_s: float
    elapsed_ms: int
    error: str | None = None
    pii_detected: bool = False
    pii_counts: dict[str, int] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    detail: str
    code: str = "ask_failed"


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"] = "ok"
    components: dict[str, str] = Field(default_factory=dict)
