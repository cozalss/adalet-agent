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
ResponseIntent = Literal[
    "legal_answer",
    "needs_clarification",
    "redirect_to_scope",  # triaj iç-niyeti (unknown domain) — finalize'a varmadan chat'e dönüşür
    "redirect",           # finalize'ın EMİT ettiği dış değer; frontend bunu bekler (App.jsx/
                          # useChat/parseAnswer "redirect" arar) → yumuşak yönlendirme baloncuğu.
                          # Denetim 2026-06-04: finalize 'redirect' döndürüyordu ama Literal'da
                          # yoktu (tip ihlali). Frontend sözleşmesi 'redirect' → geçerli kılındı.
    "smalltalk",
    "chat",  # genel sohbet (chat node Qwen ile doğal cevap) — hukuki-olmayan
    "out_of_scope_sensitive",
    "reject_unverified",
]
Role = Literal["user", "assistant"]


class Citation(TypedDict):
    """Tek bir kaynak referansı — mevzuat maddesi veya emsal karar."""

    source_id: str          # Qdrant point id
    doc_type: DocType
    title: str              # "TKHK Madde 11" veya "Yargıtay 13.HD 2019/1234"
    snippet: str            # ilk eşleşen pasaj (chunk text)
    url: str                # mevzuat.gov.tr veya yargi-mcp link
    score: float            # rerank / hybrid skoru


def merge_citations(
    left: list[Citation], right: list[Citation],
) -> list[Citation]:
    """Citation listesi reducer — source_id'ye göre union-dedup.

    `operator.add` yerine kullanılır. İki davranışı birden sağlar:
    - Paralel fan-in (ilk koşu): mevzuat/emsal ayrı key'lere yazar; reducer
      [] + yeni = yeni (etkisiz, baseline korunur).
    - Retry re-retrieve (debate→mevzuat/emsal tekrar): mevcut + yeni, source_id
      tekrarları atılır → ref birikmesi/duplikasyon olmaz, yeni kaynaklar eklenir
      (architect A2 fix). HyDE/multi-query stokastik olduğu için retry yeni
      alakalı kaynak getirebilir; dedup bunu güvenle biriktirir.
    """
    if not left:
        return right
    if not right:
        return left
    seen = {c["source_id"] for c in left}
    return [*left, *(c for c in right if c["source_id"] not in seen)]


class Claim(TypedDict):
    """LLM'in ürettiği tek bir hukuki iddia."""

    text: str                  # "Tüketici 30 gün içinde iade hakkına sahiptir"
    cite_ids: list[str]        # destekleyici Citation.source_id listesi
    verified: bool
    verify_score: float        # NLI entailment skoru (0-1)
    verify_reason: str


# Tahmin ajanı (opsiyonel 8. ajan) sonuç sınıfları. "belirsiz" = heuristic
# baseline yeterli/uyumlu emsal sinyali bulamadı (dürüst düşüş — uydurma yok).
PredictionClass = Literal["kazandi", "kaybetti", "kismi", "belirsiz"]


class Prediction(TypedDict):
    """Dava sonucu tahmini — opsiyonel `tahmin_node` çıktısı.

    Heuristic baseline (emsal kararların sonuç-sinyali oylaması) veya Sprint-7/8
    fine-tuned BERT-TR üretir. `confidence` kalibrasyon-hedefli [0,1] — ASLA
    kesinlik ima etmez (≤0.85). Bu bir TAHMİN, mahkeme garantisi değildir
    (CLAUDE.md §2); verify/debate hard-gate'i bundan etkilenmez (yalnız display).
    """

    verdict_class: PredictionClass
    confidence: float
    similar_case_ids: list[str]
    reasoning: str


class ConversationTurn(TypedDict):
    """Geçmiş konuşma turu — multi-turn context için.

    Sprint-5: API katmanı conversation_id ile bu listeyi session store'dan
    yükler ve initial state'e enjekte eder.
    """

    role: Role
    content: str
    timestamp: NotRequired[str]   # ISO8601, opsiyonel
    domain: NotRequired[Domain]   # önceki turda triaj kararı (debug)
    case_facts: NotRequired[dict[str, Any]]  # o turdan çıkarılan/taşınan olgular


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
    # Cevabın davranış niyeti. Güvenlik/alan kararı deterministik node'larda verilir;
    # kullanıcıya görünen doğal dil metni gerekirse compose node'u tarafından yazılır.
    response_intent: NotRequired[ResponseIntent]
    # Sohbet (selamlaşma/teşekkür/"ne yaparsın") tespit edilirse hazır yanıt.
    # Set ise: triaj LLM atlandı, finalize bu metni doğrudan basar (hukuki akış yok).
    smalltalk_response: NotRequired[str]
    # Sorudan çıkarılan somut olgular (çalışma süresi, işçi sayısı, tutar, olay,
    # taraf, tarih). Draft ajanı hakların ŞART/EŞİK'lerini bu olgularla karşılaştırır
    # (örn. kıdem tazminatı için kaynaktaki 1 yıl eşiği vs. kullanıcının 3 ayı).
    # Anahtarlar serbest; LLM neyi bulursa onu doldurur, yoksa boş dict.
    case_facts: NotRequired[dict[str, Any]]
    # Clarifier (eksik bilgide takip sorusu): Policy engine "clarify" derse
    # clarifier_node 2-4 SABİT Türkçe soru üretir, retrieval/draft YOK, finalize
    # bu metni doğrudan basar. clarification_round loop-guard (max 1 tur).
    clarifying_questions: NotRequired[list[str]]
    clarify_response: NotRequired[str]
    clarification_round: NotRequired[int]
    # Uygunluk değerlendirmesi (yapılandırılmış akıl yürütme): retrieve edilen her
    # madde için {madde, hak, kosul, saglaniyor: evet|hayir|belirsiz, gerekce}.
    # Draft bu önceden-hesaplanmış kararları prose'a çevirir (eşik aritmetiğini
    # prose üretiminden ayırır → küçük modelde daha güvenilir).
    eligibility: NotRequired[list[dict[str, Any]]]

    # --- Retrieval (paralel fan-in) ---
    mevzuat_refs: Annotated[list[Citation], merge_citations]
    emsal_refs: Annotated[list[Citation], merge_citations]
    # Sprint-4 W3.4: GraphRAG k-hop neighbor node id'leri (transparency için).
    # emsal_refs citation title'larından çıkarılıp graph_rag.expand() ile alınır.
    emsal_graph_neighbors: NotRequired[list[str]]

    # --- Üretim ---
    draft_response: str
    composed_response: NotRequired[str]
    claims: list[Claim]
    verified_claims: list[Claim]
    dilekce_md: NotRequired[str]
    # --- Dilekçe (6. ajan, want_dilekce=True + verdict=pass yolu) ---
    # PDF in-memory bytes — API route base64-encode etmek yerine ayrı GET endpoint
    # üzerinden stream eder (KVKK: disk persist yok, request-scope GC'lenir).
    dilekce_pdf_bytes: NotRequired[bytes | None]
    dilekce_template_id: NotRequired[str]    # audit + A/B test (örn "tuketici_iade_v1")
    dilekce_filename: NotRequired[str]       # Content-Disposition için
    # DOCX editlenebilir Word çıktısı (vatandaş/avukat düzenler) — PDF ile paralel
    dilekce_docx_bytes: NotRequired[bytes | None]
    dilekce_docx_filename: NotRequired[str]

    # --- Hakemlik / kalite döngüsü ---
    debate_verdict: DebateVerdict
    debate_notes: str
    retry_count: int               # max 3 (config.MAX_RETRY)

    # --- Tahmin (opsiyonel 8. ajan, PREDICTIVE_ENABLED) ---
    prediction: NotRequired[Prediction | None]

    # --- Çıkış ---
    response: str
    confidence: float              # 0..1
    disclaimers: list[str]
    errors: Annotated[list[str], operator.add]
