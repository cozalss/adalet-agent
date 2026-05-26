"""LangGraph AgentState — 7-ajan zincirinin paylaşılan durum modeli.

`Annotated[list, operator.add]` reducer'ları sayesinde paralel ajanlar
(Mevzuat + Emsal) aynı state'e fan-in yapabilir; LangGraph listeleri birleştirir.

Sprint-5 ekleri:
  - conversation_id, chat_history (multi-turn)
  - image_attachments (OCR'lanan belge metinleri)
  - audio_transcript (STT çıktısı)
  - want_tts (cevabı sesli istemiş mi?)

Referans: docs/architecture.md (LangGraph topology).
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, NotRequired, TypedDict

# 8 domain + unknown — CLAUDE.md kapsamı (ceza/aile YOK)
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

DocType = Literal["law", "case"]
DebateVerdict = Literal["pass", "retry", "reject"]
Role = Literal["user", "assistant"]


class Citation(TypedDict):
    """Tek bir kaynak referansı — mevzuat maddesi veya emsal karar."""

    source_id: str          # Qdrant point id
    doc_type: DocType
    title: str              # "TKHK Madde 11" veya "Yargıtay 13.HD 2019/1234"
    snippet: str            # ilk eşleşen pasaj (chunk text)
    url: str                # mevzuat.gov.tr veya yargi-mcp link
    score: float            # rerank / hybrid skoru


class Claim(TypedDict):
    """LLM'in ürettiği tek bir hukuki iddia."""

    text: str                  # "Tüketici 30 gün içinde iade hakkına sahiptir"
    cite_ids: list[str]        # destekleyici Citation.source_id listesi
    verified: bool
    verify_score: float        # NLI entailment skoru (0-1)
    verify_reason: str


class ConversationTurn(TypedDict):
    """Geçmiş konuşma turu — multi-turn context için.

    Sprint-5: API katmanı conversation_id ile bu listeyi session store'dan
    yükler ve initial state'e enjekte eder.
    """

    role: Role
    content: str
    timestamp: NotRequired[str]   # ISO8601, opsiyonel
    domain: NotRequired[Domain]   # önceki turda triaj kararı (debug)


class ImageAttachment(TypedDict):
    """OCR'lanan kullanıcı belgesi (kira sözleşmesi fotoğrafı, vs.).

    `text` chunker'dan geçmiş + Türkçe normalize edilmiş hâli içerir.
    `ocr_engine` debug ve kalite izleme için.
    """

    filename: str
    ocr_engine: str               # "tesseract" | "qwen-vl"
    text: str                     # max ~10000 char önerilir
    n_chars: int
    ocr_error: NotRequired[str]


class AgentState(TypedDict):
    # --- Giriş ---
    question: str
    want_dilekce: bool
    user_meta: NotRequired[dict[str, Any]]   # sehir, taraf, vs. (opsiyonel)

    # --- Multi-turn / Multi-modal (Sprint-5) ---
    conversation_id: NotRequired[str]
    chat_history: NotRequired[list[ConversationTurn]]    # son ~5 tur, oldest first
    image_attachments: NotRequired[list[ImageAttachment]]
    audio_transcript: NotRequired[str]                    # STT çıktısı, varsa
    want_tts: NotRequired[bool]                           # cevabı sesli üret

    # --- Triaj ---
    domain: Domain
    domain_confidence: float
    triage_reasoning: str

    # --- Retrieval (paralel fan-in) ---
    mevzuat_refs: Annotated[list[Citation], operator.add]
    emsal_refs: Annotated[list[Citation], operator.add]
    # Sprint-4 W3.4: GraphRAG k-hop neighbor node id'leri (transparency için).
    # emsal_refs citation title'larından çıkarılıp graph_rag.expand() ile alınır.
    emsal_graph_neighbors: NotRequired[list[str]]

    # --- Üretim ---
    draft_response: str
    claims: list[Claim]
    verified_claims: list[Claim]
    dilekce_md: NotRequired[str]

    # --- Hakemlik / kalite döngüsü ---
    debate_verdict: DebateVerdict
    debate_notes: str
    retry_count: int               # max 3 (config.MAX_RETRY)

    # --- Çıkış ---
    response: str
    confidence: float              # 0..1
    disclaimers: list[str]
    errors: Annotated[list[str], operator.add]
