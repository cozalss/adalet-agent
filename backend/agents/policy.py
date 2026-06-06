"""Policy engine — cevap-yolu kararı (deterministik, LLM YOK).

Bu modül 'cevaplayalım mı / netleştirelim mi / yönlendirelim mi' kararını
generation'dan ÖNCE, tek yerde verir. Önceden bu karar triaj/verify/debate/
finalize'a dağılmıştı; burada tek bir saf fonksiyona toplanır → unit-test
edilebilir, yan etkisiz, graph'tan bağımsız.

`decide_path` saf bir fonksiyondur: aynı state → aynı karar. case_facts upstream
(triaj LLM) stokastiktir ama bu modül onu yalnızca okur; test sınırı budur.
"""

from __future__ import annotations

from typing import Literal

from agents.state import AgentState

PolicyDecision = Literal["answer", "clarify", "chat", "redirect", "reject_sensitive", "smalltalk"]

# En fazla kaç tur netleştirme istenebilir. 1 → en çok bir clarify turu, sonra
# elde olanla best-effort cevapla (sonsuz soru-sorma döngüsünü kapatır).
MAX_CLARIFICATION_ROUNDS = 1

# Clarifier preamble'ına gömülen sentinel. Loop-guard bunu chat_history'deki son
# asistan turunda arar; varsa kullanıcının bu turu o sorulara cevap demektir.
# clarifier_node bu sabiti import eder (tek doğru kaynak — DRY).
CLARIFY_MARKER = "Daha doğru yardımcı olabilmem için"

# domain → netleştirme için GEREKLİ minimum olgu anahtarları. Anahtarlar triaj'ın
# _ALLOWED_FACT_KEYS evreninden (sure, isci_sayisi, tutar, olay, taraf, tarih).
# "olay" çoğu senaryoda zorunlu çekirdek: ne yaşandığı net değilse cevap güvensiz.
REQUIRED_FACTS: dict[str, tuple[str, ...]] = {
    "kira": ("olay",),
    "isHukuku": ("olay",),
    "tuketici": ("olay",),
    "icra": ("olay",),
    "trafik": ("olay",),
    "vergi": ("olay",),
    "tapu": ("olay",),
    "idari": ("olay",),
}

# Bir domain için kaç somut olgu varsa cevap güvenli sayılır. Kira/iş gibi
# eşik-bağımlı alanlarda 2; daha tek-eksenli alanlarda 1.
MIN_FACTS_FOR_ANSWER: dict[str, int] = {
    "kira": 2,
    "isHukuku": 2,
    "tuketici": 1,
    "icra": 1,
    "trafik": 1,
    "vergi": 1,
    "tapu": 1,
    "idari": 1,
}

# Genel/tanımsal soru kalıpları. Bunları içeren bir soru (örn. "kıdem tazminatı
# nasıl hesaplanır?", "ayıplı malda hakkım nedir?") bir BİLGİ sorusudur; olgu
# eksik olsa bile doğrudan cevaplanır — netleştirme istemek kötü UX olurdu.
# Bu kalıpları İÇERMEYEN, olgu-eksik sorular durumsal şikâyet kabul edilir
# (örn. "kira depozitomu alamıyorum") → clarify. tr-lowercase üzerinde substring.
_GENERAL_QUESTION_MARKERS: tuple[str, ...] = (
    "nedir", "ne demek", "ne anlama",
    "nasıl hesapla", "nasıl yapıl", "nasıl işl", "nasıl başvur", "nasıl açıl",
    "nasıl belirlen", "nasıl talep", "nasıl feshed", "nasıl öden", "nasıl alın",
    "kaç yıl", "kaç gün", "kaç ay", "kaç saat", "kaç gün", "ne kadar",
    "hangi durum", "hangi şart", "şartları", "şartlar ne", "koşulları",
    "koşullar ne", "kimler", "kimdir", "alabilir mi", "hak kazan",
    "hakkım ne", "hakları ne", "zamanaşımı", "süresi ne", "süresi kaç",
    "nelerdir", "gerekli mi", "mümkün mü", "yasal mı", "fark nedir",
    "itiraz edilir", "talep edilir", "kaldırılır", "feshedilir", "ödenir",
    "alınır", "verilir", "başlatılır", "kapatılır", "açılır", "nereye itiraz",
    "ne talep edebilir", "oran ne", "sınırları",
    # iter8 (ölçülen over-clarification): doğal "nasıl/ne olur/haklarım/edebilir miyim"
    # kalıpları clarify'a düşüyordu (markerlar eksikti). Bunlar BİLGİ/nasıl sorusu → cevapla.
    # Yalın durumsal şikâyetler ("depozitomu alamıyorum") bunları İÇERMEZ → hâlâ clarify.
    "haklarım", "hangi hak", "ne yapabilir", "ne yapmal", "ne olur", "ne olacak",
    "nasıl itiraz", "edebilir mi", "yapabilir mi", "açabilir mi", "dava aç",
    "talep edebil", "başvurabilir", "gerekir mi", "zorunda mı",
)


def _tr_lower(text: str) -> str:
    """Türkçe-güvenli küçült (İ→i, I→ı) — substring eşleşmesi için."""
    return text.replace("I", "ı").replace("İ", "i").lower()


def _is_general_question(question: str) -> bool:
    """Soru genel/tanımsal bir bilgi sorusu mu? (olgu-eksik olsa da cevaplanır)."""
    low = _tr_lower(question)
    return any(marker in low for marker in _GENERAL_QUESTION_MARKERS)


def decide_path(state: AgentState) -> PolicyDecision:
    """Generation öncesi tek karar noktası — erken-return merdiveni.

    Sıra (en spesifik → en genel):
      1. smalltalk / out_of_scope_sensitive → triaj zaten kesin niyet verdi
      2. unknown domain → redirect
      3. loop-guard: zaten N tur netleştirildi → answer (best-effort)
      4. kullanıcı önceki turda netleştirmeye cevap verdi (marker) → answer
      5. olgular yeterli → answer
      6. soru genel/tanımsal (bilgi sorusu) → answer
      7. aksi (olgu-eksik durumsal şikâyet) → clarify
    """
    intent = state.get("response_intent", "legal_answer")
    # Hukuki-OLMAYAN her şey (selam, kapsam-dışı ceza/aile, belirsiz/genel soru) →
    # genel sohbet: chat node, Qwen'in gerçek-beyni ile doğal akan cevap (ChatGPT gibi).
    # Net hukuki domain (8 sivil alan) DOĞRULAMALI boruya gider (sıfır-halüsinasyon korunur).
    if intent in ("smalltalk", "out_of_scope_sensitive"):
        return "chat"

    domain = state.get("domain", "unknown")
    if domain == "unknown":
        return "chat"

    if state.get("clarification_round", 0) >= MAX_CLARIFICATION_ROUNDS:
        return "answer"
    if _user_already_answered_clarifier(state):
        return "answer"
    # ÖNCE olgu-yeterlilik: triaj case_facts'i doldurduysa (ör. trafik/vergi/idari
    # MIN_FACTS=1 karşılanır) doğrudan cevapla. Aksi halde spesifik sorular gereksiz
    # netleştirmeye düşüyordu (2026-06-04: "park halinde çarpıp kaçtılar" → clarify).
    if _facts_sufficient(domain, state.get("case_facts") or {}):
        return "answer"
    # Olgu eksik AMA soru genel/tanımsal ise yine doğrudan cevapla.
    if _is_general_question(state.get("question", "")):
        return "answer"
    # Olgu EKSİK ve durumsal görünüyorsa → netleştir (yalnız gerçekten eksik-bilgide).
    if _looks_situational(state.get("question", "")) and not _is_general_question(state.get("question", "")):
        return "clarify"
    return "clarify"


def _facts_sufficient(domain: str, facts: dict[str, object]) -> bool:
    """Domain şemasına göre olgular cevap için yeterli mi? Saf, test edilebilir."""
    present = {key for key, val in facts.items() if str(val).strip()}
    required = set(REQUIRED_FACTS.get(domain, ()))
    if not required <= present:
        return False
    return len(present) >= MIN_FACTS_FOR_ANSWER.get(domain, 1)


_SITUATIONAL_MARKERS: tuple[str, ...] = (
    "alamıyorum", "alamadım", "vermiyor", "ödemiyor", "ödenmedi", "reddedildi",
    "çıkarıldım", "kesildi", "geldi", "başlatılmış", "yaşıyorum", "sorunum var",
    "sorum var", "yedim", "yaptım", "konuldu", "el konuldu", "iptal etti",
    "çıkarmak istiyor", "yüksek geldi",
)


def _looks_situational(question: str) -> bool:
    """Kullanıcının somut olayı anlattığı, netleştirme isteyen kısa şikayet mi?"""
    low = _tr_lower(question)
    return any(marker in low for marker in _SITUATIONAL_MARKERS)


def _user_already_answered_clarifier(state: AgentState) -> bool:
    """Son asistan turu netleştirme sorusu muydu? (chat_history marker)."""
    history = state.get("chat_history") or []
    for turn in reversed(history):
        if turn.get("role") == "assistant":
            return CLARIFY_MARKER in (turn.get("content") or "")
    return False


__all__ = (
    "CLARIFY_MARKER",
    "MAX_CLARIFICATION_ROUNDS",
    "MIN_FACTS_FOR_ANSWER",
    "REQUIRED_FACTS",
    "PolicyDecision",
    "decide_path",
)
