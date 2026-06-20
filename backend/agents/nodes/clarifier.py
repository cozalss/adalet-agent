"""Clarifier node — eksik bilgide 2-4 SABİT Türkçe takip sorusu sor, dur.

Policy engine "clarify" derse graph bu node'a girer; retrieval/draft/verify'a
HİÇ dokunmadan finalize'a akar (finalize bu metni doğrudan basar). Sorular
domain başına önceden yazılmış SABİT bir bankadan gelir → sıfır halüsinasyon
yüzeyi (hiçbir madde/karar numarası, hiçbir hukuki iddia yok; smalltalk._REPLIES
deseni).

Loop-guard: render edilen metin CLARIFY_MARKER ile başlar; bir sonraki turda
policy bu marker'ı chat_history'de görüp kullanıcının cevap verdiğini anlar
(sonsuz soru-sorma döngüsü kapanır).
"""

from __future__ import annotations

import structlog

from agents.clarify_slots import (
    discriminator_followup_questions,
    discriminator_options,
    discriminator_questions,
)
from agents.policy import CLARIFY_MARKER
from agents.state import AgentState
from core.observability import observe_node

log = structlog.get_logger()

# Bir clarify turunda kullanıcıya sorulacak azami soru sayısı (bilişsel yük).
_MAX_QUESTIONS = 4

# domain → ((fact_key | None, soru), ...). fact_key verilmişse ve o olgu zaten
# case_facts'te varsa soru ATLANIR (kullanıcıya bildiğimiz şeyi tekrar sormayız).
# fact_key=None → her zaman sorulur. Sorular vatandaş diliyle, SOMUT hukuki iddia
# içermez (madde/karar/kanun numarası yok).
QUESTION_BANK: dict[str, tuple[tuple[str | None, str], ...]] = {
    "kira": (
        ("olay", "Yaşadığınız sorunu (depozito, tahliye, kira artışı vb.) kısaca anlatır mısınız?"),
        (None, "Kira sözleşmesi sona erdi mi, yoksa hâlâ devam ediyor mu?"),
        (None, "Evi tahliye edip ev sahibine teslim ettiniz mi?"),
        (None, "Ev sahibi bir gerekçe (hasar, ödenmemiş kira vb.) sundu mu?"),
    ),
    "isHukuku": (
        ("olay", "Yaşadığınız durumu (işten çıkarılma, ücret, fazla mesai vb.) kısaca anlatır mısınız?"),
        ("sure", "Bu işyerinde ne kadar süredir çalışıyorsunuz?"),
        (None, "İşten siz mi ayrıldınız, yoksa işveren mi çıkardı?"),
        ("isci_sayisi", "İşyerinde yaklaşık kaç kişi çalışıyor?"),
    ),
    "tuketici": (
        ("olay", "Yaşadığınız sorunu (ayıplı ürün, iade, garanti vb.) kısaca anlatır mısınız?"),
        ("tarih", "Ürünü/hizmeti ne zaman aldınız?"),
        (None, "Satıcıya durumu bildirip çözüm istediniz mi? Yanıtları ne oldu?"),
    ),
    "icra": (
        ("olay", "İcra sürecinde yaşadığınız sorunu kısaca anlatır mısınız?"),
        (None, "Size bir ödeme emri veya tebligat ulaştı mı? Ne zaman?"),
        (None, "Borcu kabul ediyor musunuz, yoksa itirazınız mı var?"),
    ),
    "trafik": (
        ("olay", "Trafikle ilgili sorununuzu (kaza, ceza, sigorta vb.) kısaca anlatır mısınız?"),
        (None, "Olayda tutanak tutuldu mu ya da bir ceza yazıldı mı?"),
        (None, "Karşı tarafla aranızda hasar/kusur konusunda anlaşmazlık var mı?"),
    ),
    "vergi": (
        ("olay", "Vergiyle ilgili sorununuzu (tarhiyat, ceza, itiraz vb.) kısaca anlatır mısınız?"),
        (None, "Size bir vergi/ceza ihbarnamesi tebliğ edildi mi? Ne zaman?"),
        (None, "Tebliğ edilen tutara itiraz mı etmek istiyorsunuz?"),
    ),
    "tapu": (
        ("olay", "Tapuyla ilgili sorununuzu (devir, miras, şerh vb.) kısaca anlatır mısınız?"),
        (None, "Taşınmazın tapu kaydı kimin üzerine görünüyor?"),
        (None, "Diğer taraflarla (ortak, mirasçı, satıcı) bir anlaşmazlık var mı?"),
    ),
    "idari": (
        ("olay", "İdareyle (belediye, kurum vb.) yaşadığınız sorunu kısaca anlatır mısınız?"),
        (None, "Size yazılı bir idari işlem/karar tebliğ edildi mi? Ne zaman?"),
        (None, "İdareye başvurdunuz mu, yanıt aldınız mı?"),
    ),
}


def _pick_questions(domain: str, case_facts: dict[str, object]) -> list[str]:
    """Domain bankasından, bilinen olguların sorusunu atlayarak 2-4 soru seç."""
    pairs = QUESTION_BANK.get(domain)
    if not pairs:
        return []
    known = {key for key, val in case_facts.items() if str(val).strip()}
    filtered = [q for fact_key, q in pairs if fact_key is None or fact_key not in known]
    # Tümü atlandıysa (beklenmez — policy clarify dedi) güvenli geri-düşüş.
    if not filtered:
        filtered = [q for _key, q in pairs]
    return filtered[:_MAX_QUESTIONS]


def _select_questions(state: AgentState) -> list[str]:
    """Bağlama göre soru seç (CLAM 'generate' — policy ile AYNI yardımcılar, DRY):

    1. round-2 sebebe-özel follow-up (sebep zaten verildi) → en hedefli
    2. round-1 sebep sorusu (ayırt edici parametre eksik)
    3. domain bankasının jenerik soruları (ayırt edici senaryo yok)
    """
    domain = state.get("domain", "unknown")
    case_facts = state.get("case_facts") or {}
    question = state.get("question", "")
    targeted = discriminator_followup_questions(domain, question, case_facts) or discriminator_questions(
        domain, question, case_facts
    )
    if targeted:
        return targeted[:_MAX_QUESTIONS]
    return _pick_questions(domain, case_facts)


def _render(questions: list[str]) -> str:
    """Sıcak preamble (CLARIFY_MARKER) + numaralı sorular + kapanış."""
    numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, start=1))
    return (
        f"{CLARIFY_MARKER} birkaç bilgiye ihtiyacım var:\n\n"
        f"{numbered}\n\n"
        "Bu soruları yanıtlarsanız durumunuza uygun, kaynaklı bir cevap hazırlayabilirim."
    )


@observe_node(name="clarifier")
async def clarifier_node(state: AgentState) -> dict[str, object]:
    """Eksik bilgide takip soruları üret; banka'da domain yoksa no-op."""
    domain = state.get("domain", "unknown")
    questions = _select_questions(state)
    if not questions:
        log.info("clarifier_noop", domain=domain)
        return {}

    # Round-1 sebep-sorusunda tıklanabilir cevap-şıkları (sebep seçimi); round-2'de boş.
    options = discriminator_options(domain, state.get("question", ""), state.get("case_facts") or {}) or []

    log.info("clarifier_ask", domain=domain, n_questions=len(questions), n_options=len(options))
    return {
        "response_intent": "needs_clarification",
        "clarifying_questions": questions,
        "clarify_options": options,
        "clarify_response": _render(questions),
        "clarification_round": state.get("clarification_round", 0) + 1,
    }


__all__ = ("QUESTION_BANK", "clarifier_node")
