"""Triaj ajanı — soruyu 8 hukuk domain'ine ata.

Strateji:
  1. Hızlı keyword filter (kapsam dışı: ceza/aile) → unknown
  2. Multi-turn: chat_history varsa son turun domain'ini hint olarak ekle
  3. LLM JSON-mode classify (system prompt: triaj.tr.txt)
  4. Düşük güven (< MIN_DOMAIN_CONFIDENCE) → unknown

Sprint-5: chat_history support. Önceki turun domain'i "hint" olarak verilir,
ama LLM yine de yeni soruyu kendi başına değerlendirir. "Devam soruları"
(pronominal referans: "o zaman", "bu durumda") önceki domain'i korur.

Çıkış: state["domain"], state["domain_confidence"], state["triage_reasoning"]
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
from pathlib import Path

import structlog

from agents.config import MIN_DOMAIN_CONFIDENCE, OUT_OF_SCOPE_KEYWORDS
from agents.llm import ChatMessage, get_llm
from agents.policy import CLARIFY_MARKER
from agents.smalltalk import detect_smalltalk, smalltalk_reply
from agents.state import AgentState, ConversationTurn, Domain, ImageAttachment
from agents.triage_classifier import classify_domain
from core.observability import observe_node

log = structlog.get_logger()

VALID_DOMAINS: set[str] = {
    "tuketici", "isHukuku", "kira", "icra",
    "trafik", "vergi", "tapu", "idari", "unknown",
}

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "triaj.tr.txt"

# Devam-sorusu işaretleri (pronominal / contextual) — önceki domain'i koru
_CONTINUATION_MARKERS = (
    "peki", "o zaman", "bu durumda", "böyle", "şöyle", "öyleyse",
    "ya da", "bunun için", "buna göre", "o halde",
)

MAX_HISTORY_TURNS_IN_PROMPT = 5

# Türkçe ek alan, false-positive riski düşük kapsam-dışı çekirdek kelimeler.
# "cinayetten", "nafakaya", "velayeti" gibi formlar \b tam-eşleşmeye takılmaz.
_OUT_OF_SCOPE_PREFIX_KEYWORDS = frozenset({
    "cinayet", "öldürme", "tutuklama", "tutuklu", "gözaltı",
    "hırsız", "dolandırıc", "savcılık", "suç", "darp",
    "nafaka", "velayet", "boşan",
    "hapis",   # hapis cezası/yatmak — ceza hukuku (sivil sözlükte geçmez)
    "dövdü",   # dövdüm/dövdü/dövdün — kasten yaralama ("dövdü"; "döv" döviz'i de yakalardı)
})

_FAST_DOMAIN_KEYWORDS: dict[Domain, tuple[str, ...]] = {
    "tuketici": (
        "tüketici", "ayıplı", "bozuk ürün", "bozuk mal", "garanti",
        "mesafeli satış", "internetten ald", "iade", "değişim", "satıcı",
        "cayma hakkı", "abonelik", "taksitli satış", "haksız şart",
        "tüketici kredisi", "erken ödeme", "hakem heyeti", "ürün",
        "hizmet", "arızalı", "ayıplı hizmet",
    ),
    "isHukuku": (
        "işten çıkar", "kıdem", "ihbar", "fazla mesai", "maaş", "ücret",
        "mobbing", "işçi", "işveren", "sgk", "yıllık izin", "deneme süresi",
        "doğum izni", "genel tatil", "iş kazası", "haklı fesih", "işe iade",
    ),
    "kira": (
        "kira", "kiracı", "ev sahibi", "depozito", "tahliye",
        "konut", "işyeri kir", "kira artış",
    ),
    "icra": (
        "icra", "haciz", "ödeme emri", "takip", "borçlu", "alacaklı",
        "itirazın kaldırılması", "itirazın iptali", "ilamsız", "kambiyo",
        "senet", "maaş haczi", "haczedilemeyen", "borca itiraz", "imzaya itiraz",
        "satış talebi",
    ),
    "trafik": (
        "trafik", "kaza", "sigorta", "kasko", "ehliyet", "plaka",
        "araç değer kaybı", "değer kaybı", "trafik cezası", "hız ihlali",
        "pert araç", "zorunlu trafik", "tespit tutanağı",
        # Ölçüldü (iter7 sweep): "kırmızı ışık cezasına itiraz" → unknown'a düşüyordu
        # (DistilBERT trafik@0.36 eşik-altı, LLM unknown dedi). Yüksek-kesinlikli terimler
        # (mtv EKLENMEDİ — vergi domain'inde, çakışırdı):
        "kırmızı ışık", "ışık ihlali", "hız cezası", "radar", "araç muayene", "ceza puanı",
    ),
    "vergi": (
        "vergi", "kdv", "ötv", "mtv", "gelir vergisi", "vergi cezası",
        "gecikme faizi", "uzlaşma", "vergi ziyaı", "usulsüzlük",
        "tarhiyat", "tecil", "taksitlendirme", "pişmanlık", "ıslah",
    ),
    "tapu": (
        "tapu", "mülkiyet", "kat mülkiyeti", "arsa", "imar",
        "site yönetimi", "apartman", "intifa", "ipotek", "muvazaalı",
        "geçit hakkı", "şufa", "ortaklığın giderilmesi", "tescil",
        "kat irtifakı",
    ),
    "idari": (
        "idari işlem", "idare mahkemesi", "kamulaştırma", "vatandaşlık",
        "ruhsat", "belediye", "iptal davası", "tam yargı", "yürütmeyi durdurma",
        "zımni ret", "disiplin cezası", "idari para cezası", "kamu görevlisi",
        "idari dava", "idareye başvuru", "istinaf", "temyiz",
    ),
}

_DURATION_UNIT_RE = r"(?:iş\s+günü|gün|hafta|ay|yıl|sene)"
_SURE_RE = re.compile(
    rf"\b\d+\s*{_DURATION_UNIT_RE}(?:\s+\d+\s*{_DURATION_UNIT_RE})*\b",
    re.IGNORECASE,
)
_TUTAR_RE = re.compile(
    r"(?:%\s*\d+|yüzde\s+\d+|\b\d+[.,]?\d*\s*(?:tl|lira)\b)",
    re.IGNORECASE,
)

_ISCI_SAYISI_RE = re.compile(r"\b\d+\s*(?:kişi|işçi|çalışan|personel)\b", re.IGNORECASE)


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _tr_lower(text: str) -> str:
    """Türkçe-güvenli küçült (İ→i, I→ı) — keyword eşleşmeleri için."""
    return text.replace("I", "ı").replace("İ", "i").lower()


def _is_out_of_scope(question: str) -> bool:
    """Kapsam-dışı keyword tespiti — kelime sınırı bilinçli.

    Substring kontrolü "vergi cezası" gibi yasal terimlerde yanlış pozitif
    verir ("ceza" ⊂ "cezası"). Bu yüzden \\b kelime sınırı ile match yapıyoruz.
    Ayrıca "ceza" tek başına değil, "ceza hukuku / ceza davası / ceza yargılaması"
    bağlamında match etmeli — bu yüzden multi-token form'lar tercih edilir.
    """
    import re as _re
    q_low = _tr_lower(question)
    tokens = _re.findall(r"[a-zçğıöşü]+", q_low)
    if any(
        token.startswith(prefix)
        for token in tokens
        for prefix in _OUT_OF_SCOPE_PREFIX_KEYWORDS
    ):
        return True
    for kw in OUT_OF_SCOPE_KEYWORDS:
        # Çok-token ise (örn "ceza hukuku") aynen aranır; tek token ise \b ile
        if " " in kw:
            if kw in q_low:
                return True
        else:
            if _re.search(rf"\b{_re.escape(kw)}\b", q_low):
                return True
    return False


# CLAUDE.md §4: çocuk (<18) özel filtresi. 1. TEKİL ŞAHIS odaklı — "kızım 15 yaşında"
# (ebeveyn, yetişkin kullanıcı) yanlış-pozitifini önler; yalnız kullanıcının KENDİSİNİN
# 18 yaş altı olduğunu söylediği kalıplar. "18 yaşındayım" eşleşmez (1[0-7] = 10-17).
_MINOR_RE = re.compile(
    r"(?:\b(?:1[0-7]|[1-9])\s*yaşındayım)"
    r"|reşit\s+değilim"
    r"|reşit\s+olmadım"
    r"|18\s*yaşımı\s*doldurmadım"
    r"|(?:18|on\s*sekiz)\s*yaşından\s*küçüğüm"
)
_MINOR_REPLY = (
    "Sistemimiz yalnızca 18 yaş ve üzeri kullanıcılar içindir; bu nedenle hukuki "
    "değerlendirme yapamıyorum. Bir sorun yaşıyorsan lütfen bir yetişkinden (veli veya "
    "vasinden) yardım iste; ciddi durumlarda bir avukata ya da ALO 183 Sosyal Destek "
    "Hattı'na başvurulabilir."
)


def _is_minor(question: str) -> bool:
    """Kullanıcının KENDİSİNİN 18 yaş altı olduğunu belirttiğini sezer (CLAUDE.md §4)."""
    return bool(_MINOR_RE.search(_tr_lower(question)))


def _is_continuation(question: str) -> bool:
    q_low = _tr_lower(question).strip()
    return any(q_low.startswith(m) or f" {m}" in q_low[:30] for m in _CONTINUATION_MARKERS)


def _fast_domain(question: str) -> Domain | None:
    """Açık anahtar kelimeli sorularda LLM triajını atla.

    Belirsiz/çakışmalı durumda None döner ve eski JSON-mode LLM triaj çalışır.
    """
    q_low = _tr_lower(question)
    scores: dict[Domain, int] = {}
    for domain, keywords in _FAST_DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in q_low)
        if score:
            scores[domain] = score
    if not scores:
        return None
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def _fast_facts(question: str, domain: Domain) -> dict[str, str]:  # noqa: C901
    """LLM'siz küçük olgu çıkarımı; eksik olursa draft yine sorudan anlar."""
    facts: dict[str, str] = {}
    q_low = _tr_lower(question)
    if m := _SURE_RE.search(question):
        facts["sure"] = m.group(0)
    if m := _TUTAR_RE.search(question):
        facts["tutar"] = m.group(0)
    if m := _ISCI_SAYISI_RE.search(question):
        facts["isci_sayisi"] = m.group(0)

    taraf_map = {
        "kirac": "kiracı",
        "ev sahibi": "ev sahibi",
        "işçi": "işçi",
        "işveren": "işveren",
        "tüketici": "tüketici",
        "borçlu": "borçlu",
        "alacaklı": "alacaklı",
    }
    for marker, label in taraf_map.items():
        if marker in q_low:
            facts["taraf"] = label
            break

    # Marker'lar domain-scoped (yalnız o domain seçiliyken bakılır) → geniş tutmak güvenli.
    # 2026-06-04: trafik/vergi/idari doğal-dil sorularda hiç eşleşmiyordu (gereksiz clarify);
    # marker'lar vatandaş diline genişletildi.
    olay_by_domain = {
        "kira": ("kira artış", "tahliye", "depozito", "güvence", "kira sözleşme", "ev sahib"),
        "tuketici": ("ayıplı", "bozuk", "iade", "değişim", "garanti", "satıcı", "internetten al"),
        "isHukuku": ("işten çıkar", "kıdem", "ihbar", "maaş", "fazla mesai", "tazminat", "istifa"),
        "icra": ("icra", "haciz", "ödeme emri", "itiraz", "borç", "alacaklı", "takip"),
        "trafik": ("trafik kaz", "sigorta", "değer kaybı", "çarp", "kaza", "park", "kasko",
                   "hasar", "ehliyet", "plaka", "kaçtı", "tutanak"),
        "vergi": ("vergi cezası", "kdv", "ötv", "mtv", "emlak vergisi", "itiraz", "tarhiyat",
                  "tahakkuk", "beyanname", "matrah", "ihbarname", "ödeme emri"),
        "tapu": ("tapu", "kat mülkiyeti", "mülkiyet", "devir", "tescil", "satış", "daire", "arsa"),
        "idari": ("idari işlem", "kamulaştırma", "ruhsat", "disiplin", "memur", "görevden",
                  "soruşturma", "atama", "ihraç", "kamu görevlis"),
    }
    for marker in olay_by_domain.get(domain, ()):
        if marker in q_low:
            facts["olay"] = marker
            break
    if domain == "isHukuku":
        unpaid = []
        if "kıdem" in q_low:
            unpaid.append("kıdem tazminatı")
        if "ihbar" in q_low:
            unpaid.append("ihbar tazminatı")
        if unpaid and any(x in q_low for x in ("ödenmedi", "ödenmedi.", "ödemedi", "yatmadı")):
            facts["odenmeyen_haklar"] = ", ".join(unpaid)
        if any(x in q_low for x in ("yazılı gerekçe göstermeden", "gerekçe göstermeden", "sebep göstermeden")):
            facts["fesih_bildirimi"] = "yazılı gerekçe gösterilmedi"
        if any(x in q_low for x in ("işe iade", "ise iade")):
            facts["olay"] = "işe iade"
    if domain == "kira":
        if any(x in q_low for x in ("sözleşme bitti", "sözleşme sona erdi", "sona erdi")):
            facts["sozlesme_durumu"] = "sona erdi"
        elif "sözleşme devam" in q_low:
            facts["sozlesme_durumu"] = "devam ediyor"
        if any(x in q_low for x in ("teslim ettim", "evi teslim", "tahliye ettim")):
            facts["teslim"] = "evi teslim etti"
        if any(x in q_low for x in ("gerekçe göstermiyor", "gerekçe sunmuyor", "hiçbir gerekçe")):
            facts["gerekce"] = "gerekçe gösterilmedi"
    return facts


# OCR belge metninden olgu çıkarımı sınırları.
_DOC_FACTS_MAX_CHARS = 6000   # birleşik belge metni tavanı (LLM token + DoS guard)
_DOC_LLM_MIN_CHARS = 80       # bu uzunluğun altında yalnız regex (LLM gereksiz)

_DOC_TARAF_MAP = {
    "kirac": "kiracı", "ev sahibi": "ev sahibi", "işçi": "işçi",
    "işveren": "işveren", "tüketici": "tüketici", "satıcı": "satıcı",
    "borçlu": "borçlu", "alacaklı": "alacaklı", "davacı": "davacı", "davalı": "davalı",
}


def _doc_regex_facts(text: str) -> dict[str, str]:
    """Belge metninden domain-AGNOSTİK regex olguları (süre/tutar/işçi/taraf).

    Mevcut module-level regex'leri (_SURE_RE, _TUTAR_RE, _ISCI_SAYISI_RE) belge
    metnine uygular — soru metnine uygulandığı gibi. Deterministik, LLM'siz.
    """
    facts: dict[str, str] = {}
    if m := _SURE_RE.search(text):
        facts["sure"] = m.group(0)
    if m := _TUTAR_RE.search(text):
        facts["tutar"] = m.group(0)
    if m := _ISCI_SAYISI_RE.search(text):
        facts["isci_sayisi"] = m.group(0)
    low = _tr_lower(text)
    for marker, label in _DOC_TARAF_MAP.items():
        if marker in low:
            facts["taraf"] = label
            break
    return facts


async def _facts_from_documents(
    attachments: list[ImageAttachment], *, llm_extract: bool = True,
) -> dict[str, str]:
    """OCR belge metinlerinden case_facts çıkar (regex + opsiyonel LLM).

    Hibrit: kısa belge → yalnız regex (ucuz); yeterince uzun belge → ek olarak
    _recover_facts (mevcut _FACTS_RETRY_USER prompt'u, belge metnine uygulanır)
    ile tarih/olay gibi regex'in kaçırdığı olgular. Tüm çıktı _sanitize_facts'ten
    geçer (izinli anahtar whitelist). Hata → boş dict (belge akışı bozulmaz).
    """
    if not attachments:
        return {}
    texts = [a.get("text", "") for a in attachments if a.get("text", "").strip()]
    if not texts:
        return {}
    joined = "\n\n".join(texts)[:_DOC_FACTS_MAX_CHARS]
    facts = _doc_regex_facts(joined)
    if llm_extract and len(joined) >= _DOC_LLM_MIN_CHARS:
        try:
            llm_facts = await _recover_facts(joined)  # _FACTS_RETRY_USER yeniden kullanım
            facts = _merge_case_facts(facts, llm_facts)
        except Exception as exc:
            log.warning("triaj_doc_facts_llm_failed", error=str(exc) or type(exc).__name__)
    return facts


def _history_case_facts(history: list[ConversationTurn]) -> dict[str, str]:
    """Önceki user turn'lerinden structured facts'i taşı."""
    merged: dict[str, str] = {}
    for turn in history:
        raw = turn.get("case_facts") or {}
        if isinstance(raw, dict):
            for key, val in raw.items():
                if val is not None and str(val).strip():
                    merged[str(key)] = str(val)[:_MAX_FACT_VALUE_LEN]
    return merged


def _merge_case_facts(*parts: dict[str, str]) -> dict[str, str]:
    """Soldan sağa merge: sayısal olgular (süre/tutar/işçi sayısı) yeni değerle ÜZERİNE
    yazılır; anlatı olgusu 'olay' BİRİKİR — multi-turn'de önceki turun durumu kaybolmasın
    ("4 aydır kiracıyım" + sonraki tur "ev sahibi artış yaptı" → ikisi de korunur)."""
    merged: dict[str, str] = {}
    for part in parts:
        for key, val in part.items():
            sval = str(val).strip()
            if not sval:
                continue
            if key in _ACCUMULATE_FACT_KEYS and merged.get(key):
                prior = merged[key]
                if sval.lower() not in prior.lower():  # yeni anlatı zaten yoksa birleştir
                    sval = f"{prior}; {sval}"
                merged[key] = sval[:_MAX_NARRATIVE_FACT_LEN]
            else:
                merged[key] = sval[:_MAX_FACT_VALUE_LEN]
    return merged


def _format_history(history: list[ConversationTurn]) -> str:
    """Son N turu prompt'a uygun string'e dök."""
    if not history:
        return "(geçmiş yok — bu ilk soru)"
    # Güvenlik (stored prompt injection): session'a yazılmış geçmiş içerik sistem-prompt'a
    # girmeden ÖNCE delimiter-escape kalıplarından arındırılır (sanitize_question kapsamı dışı).
    from api.middleware.sanitize import strip_injection_delimiters

    recent = history[-MAX_HISTORY_TURNS_IN_PROMPT:]
    lines = []
    for turn in recent:
        role = "KULLANICI" if turn["role"] == "user" else "ASİSTAN"
        content = strip_injection_delimiters(turn["content"][:400])  # token tasarrufu + injection guard
        domain_hint = ""
        if turn.get("domain") and turn["domain"] != "unknown":
            domain_hint = f"  [domain: {turn['domain']}]"
        lines.append(f"{role}{domain_hint}:\n{content}\n")
    return "\n".join(lines)


def _answered_clarifier(history: list[ConversationTurn]) -> bool:
    """Son asistan turu bir clarifier sorusu muydu? (CLARIFY_MARKER).

    Öyleyse mevcut kullanıcı turu o sorulara CEVAPTIR → konuşma önceki domain'de
    devam ediyordur. Bu turun metni ("evet evi teslim ettim") tek başına net
    domain sinyali taşımayabilir; bu yüzden continuation-marker'ı beklemeden
    önceki domain'i devralırız (yoksa triaj `unknown` → redirect → t2 cevap
    veremez; multiturn t2-answer bug'ının kök nedeni buydu).
    """
    for turn in reversed(history):
        if turn.get("role") == "assistant":
            return CLARIFY_MARKER in (turn.get("content") or "")
    return False


def _last_user_domain(history: list[ConversationTurn]) -> Domain | None:
    """Son user-turda atanmış domain — devam-sorusu inheritance için."""
    for turn in reversed(history):
        if turn["role"] == "user" and turn.get("domain") and turn["domain"] != "unknown":
            return turn["domain"]  # type: ignore[return-value]
    return None


@observe_node(name="triaj")
async def triaj_node(state: AgentState) -> dict:
    question = state["question"]

    # Sohbet kısa-yolu: selamlaşma/teşekkür/"ne yaparsın" → LLM'siz anında dostça
    # yanıt. Hukuki iddia yok (SIFIR HALÜSİNASYON güvenli); finalize bu metni basar.
    # GEÇMİŞTEN BAĞIMSIZ çalışır: "merhaba"/"teşekkürler" konuşma ortasında da anında
    # dostça yanıt almalı. detect_smalltalk zaten KISA + hukuki-ipuçsuz girdiyle sınırlı
    # → güvenli (clarifier yanıtları olgu/rakam içerir, smalltalk kalıbına UYMAZ).
    category = detect_smalltalk(question)
    if category is not None:
        log.info("triaj_smalltalk", category=category, question=question[:60])
        return {
            "domain": "unknown",
            "domain_confidence": 0.0,
            "triage_reasoning": f"Sohbet girdisi ({category}) — hukuki akış atlandı.",
            "response_intent": "smalltalk",
            "smalltalk_response": smalltalk_reply(category),
        }

    if _is_minor(question):
        log.info("triaj_minor_user")
        return {
            "domain": "unknown",
            "domain_confidence": 0.0,
            "triage_reasoning": "Kullanıcı 18 yaş altı — kapsam dışı (CLAUDE.md §4 çocuk koruması).",
            "response_intent": "out_of_scope_sensitive",
            "smalltalk_response": _MINOR_REPLY,
        }

    if _is_out_of_scope(question):
        log.info("triaj_out_of_scope", question=question[:60])
        return {
            "domain": "unknown",
            "domain_confidence": 0.0,
            "triage_reasoning": "Kapsam dışı: ceza/aile hukuku desteklenmiyor.",
            "response_intent": "out_of_scope_sensitive",
            "smalltalk_response": _out_of_scope_reply(question),
        }

    history: list[ConversationTurn] = state.get("chat_history", []) or []
    prior_facts = _merge_case_facts(
        _history_case_facts(history),
        {str(k): str(v) for k, v in (state.get("case_facts") or {}).items() if str(v).strip()},
    )
    # OCR belge ekleri → case_facts'e karışır (fast-path + LLM-path ikisi de kullanır).
    # Clarifier yükünü azaltır: belgede "2 yıl", "30000 TL" varsa kullanıcıya sorulmaz.
    doc_facts = await _facts_from_documents(state.get("image_attachments") or [])
    if doc_facts:
        prior_facts = _merge_case_facts(prior_facts, doc_facts)
        log.info("triaj_doc_facts", n=len(doc_facts), keys=sorted(doc_facts))
    # Domain devralma: ya pronominal devam sorusu ("peki, o zaman...") ya da
    # önceki turun bir clarifier sorusu olması (kullanıcı şimdi onu yanıtlıyor).
    inherited_domain = (
        _last_user_domain(history)
        if (_is_continuation(question) or _answered_clarifier(history))
        else None
    )
    if (
        not history
        and os.getenv("TRIAJ_FAST_PATH", "1").lower() in {"1", "true", "yes"}
        and (domain := _fast_domain(question))
    ):
        facts = _merge_case_facts(prior_facts, _fast_facts(question, domain))
        log.info("triaj_fast_path", domain=domain, n_facts=len(facts))
        return {
            "domain": domain,
            "domain_confidence": 0.90,
            "triage_reasoning": "Anahtar kelime hızlı triajı.",
            "response_intent": "legal_answer",
            "case_facts": facts,
        }

    # DistilBERT-TR kademesi: keyword belirsiz kaldıysa ama fine-tuned model EMİNSE,
    # pahalı LLM triajını atla (~50ms vs ~3-5s). Model yoksa/güven düşükse classify_domain
    # None döner → mevcut LLM yolu aynen korunur (graceful). Yalnız ilk turda (geçmişsiz).
    if (
        not history
        and os.getenv("TRIAJ_FAST_PATH", "1").lower() in {"1", "true", "yes"}
        and (model_result := await asyncio.to_thread(classify_domain, question))
    ):
        model_domain, model_conf = model_result
        facts = _merge_case_facts(prior_facts, _fast_facts(question, model_domain))
        log.info("triaj_model_path", domain=model_domain,
                 confidence=round(model_conf, 3), n_facts=len(facts))
        return {
            "domain": model_domain,
            "domain_confidence": round(model_conf, 3),
            "triage_reasoning": "DistilBERT-TR domain sınıflandırması.",
            "response_intent": "legal_answer",
            "case_facts": facts,
        }

    # Devam-sorusu kısa-yolu: önceki turun domain'ini koru, LLM çağrısı atlanmaz
    # ama hint olarak prompt'a girer.

    llm = get_llm()
    system_prompt = _load_prompt()
    if history:
        # Multi-turn prompt'u eklenti olarak append et (yeni prompt dosyası
        # değil — triaj.tr.txt'ye context bloğu ekliyoruz)
        history_block = _format_history(history)
        hint = f"\n[GEÇMİŞ DOMAIN HINT: {inherited_domain}]" if inherited_domain else ""
        system_prompt = (
            f"{system_prompt}\n\n"
            f"--- KONUŞMA BAĞLAMI ---\n{history_block}{hint}\n"
            f"--- /KONUŞMA BAĞLAMI ---"
        )

    # max_tokens=512: 400'dü; facts objesi JSON'a eklenince reasoning+facts birlikte
    # sığsın diye artırıldı (Qwen Türkçe reasoning ortasında kesilirse parse fail).
    response = await llm.chat(
        messages=[
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=question),
        ],
        temperature=0.0,
        max_tokens=512,
        json_mode=True,
    )

    domain, confidence, reasoning, facts = _parse_triage_json(response.content)
    facts = _merge_case_facts(prior_facts, facts)
    if inherited_domain:
        facts = _merge_case_facts(facts, _fast_facts(question, inherited_domain))

    # Salvage olduğunda facts kayboldu (JSON kesildi) → eligibility atlanır → draft
    # zayıf çıkar (tk-01 vakası). Ayrı kısa çağrı ile facts'ı kurtar; domain
    # zaten regex'le kurtarılmıştı, bu sadece olguları geri getirir.
    if reasoning == _SALVAGE_REASONING and not facts and domain != "unknown":
        log.info("triaj_facts_retry", domain=domain)
        facts = _merge_case_facts(prior_facts, await _recover_facts(question))

    # Devam sorusunda LLM unknown derse, inherited'i fallback olarak kullan
    if domain == "unknown" and inherited_domain:
        log.info("triaj_inherited_from_history", inherited=inherited_domain)
        domain = inherited_domain
        confidence = max(confidence, 0.65)
        reasoning = f"Devam sorusu, önceki domain ({inherited_domain}) korundu."

    # Düşük güven veya geçersiz domain → unknown
    if domain not in VALID_DOMAINS or confidence < MIN_DOMAIN_CONFIDENCE:
        log.warning("triaj_low_confidence", domain=domain, confidence=confidence)
        domain, confidence = "unknown", confidence

    log.info(
        "triaj_done",
        domain=domain, confidence=confidence,
        history_turns=len(history), continuation=inherited_domain is not None,
        n_facts=len(facts),
    )
    return {
        "domain": domain,
        "domain_confidence": confidence,
        "triage_reasoning": reasoning,
        "response_intent": "redirect_to_scope" if domain == "unknown" else "legal_answer",
        "case_facts": facts,
    }


# facts dict'inde kabul edilen anahtarlar — LLM serbest anahtar üretse de
# yalnız bunları tutarız (gürültü/halüsinasyon anahtar sızıntısını engeller).
_ALLOWED_FACT_KEYS = {
    "sure",
    "isci_sayisi",
    "tutar",
    "olay",
    "taraf",
    "tarih",
    "sozlesme_durumu",
    "teslim",
    "gerekce",
    "fesih_bildirimi",
    "odenmeyen_haklar",
}
_MAX_FACT_VALUE_LEN = 120
# 'olay' (serbest-metin durum anlatısı) multi-turn'de BİRİKİR (override değil) → daha geniş
# cap. Sayısal olgular (sure/tutar/isci_sayisi) yeni değerle override → 120'de kalır.
_ACCUMULATE_FACT_KEYS = frozenset({"olay"})
_MAX_NARRATIVE_FACT_LEN = 300


def _parse_triage_json(raw: str) -> tuple[Domain, float, str, dict[str, str]]:
    """Sağlam JSON parser — markdown fence vs. fallback. facts tolere edilir.

    facts eksik/bozuk olursa boş dict döner — domain sınıflandırması bundan
    ETKİLENMEZ (additive alan). Yalnız izinli anahtarlar + string değerler tutulur.
    """
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.startswith("```"))

    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # Qwen 2.5 zaman zaman Çince talimat sızdırıyor (kira/tk-01 vakası:
        # "garanti期内请不要使用换行..."), JSON tamamlanmadan kesiliyor. Bozuk
        # çıktıdan domain + confidence'ı regex ile kurtar — sıfır halüsinasyon
        # ihlali yok (LLM domain'i zaten string olarak yazmıştı). Sınıflandırma
        # kaybolmasın diye salvage; eğer regex de bulamazsa unknown fallback.
        log.warning("triaj_json_parse_failed", raw=raw[:200])
        salvaged = _salvage_triage_fields(raw)
        if salvaged is not None:
            d, c, r = salvaged
            log.info("triaj_json_salvaged", domain=d, confidence=c)
            return d, c, r, {}
        return "unknown", 0.0, f"JSON parse hatası: {raw[:80]}", {}

    domain = str(obj.get("domain", "unknown")).strip()
    try:
        confidence = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    if not math.isfinite(confidence):
        confidence = 0.0
    confidence = min(max(confidence, 0.0), 1.0)
    reasoning = str(obj.get("reasoning", "")).strip()
    facts = _sanitize_facts(obj.get("facts"))
    return domain, confidence, reasoning, facts  # type: ignore[return-value]


# Bozuk JSON'dan domain string'ini çek (Çince/karışık çıktı, kesilmiş yanıt).
# "domain": "tuketici" deseni — case-insensitive, snake/camel arası fark gözetmez.
_SALVAGE_DOMAIN_RE = re.compile(
    r'["\']domain["\']\s*:\s*["\']([a-zA-Z_]+)["\']',
    re.IGNORECASE,
)
_SALVAGE_CONFIDENCE_RE = re.compile(
    r'["\']confidence["\']\s*:\s*([0-9]*\.?[0-9]+)',
    re.IGNORECASE,
)


def _salvage_triage_fields(raw: str) -> tuple[Domain, float, str] | None:
    """Bozuk JSON'dan (domain, confidence, reasoning) regex ile kurtar.

    Qwen 2.5 Türkçe-Çince karışık çıktı zaman zaman üretiyor (training data
    contamination). Yanıt bozulsa bile domain "tuketici" string'i çoğu zaman
    bütün hâlinde yazılmış oluyor — atmak yerine kurtarıyoruz. Sıfır-halüsinasyon
    ihlali değil: LLM domain string'ini ZATEN yazdı, biz sadece JSON parser
    yerine regex ile okuyoruz.
    """
    m_dom = _SALVAGE_DOMAIN_RE.search(raw)
    if not m_dom:
        return None
    domain = m_dom.group(1).strip()
    if domain not in VALID_DOMAINS:
        return None
    m_conf = _SALVAGE_CONFIDENCE_RE.search(raw)
    confidence = 0.5  # Salvage olduğu için muhafazakar baz; LLM yazdıysa kullan
    if m_conf:
        try:
            c = float(m_conf.group(1))
            if math.isfinite(c):
                confidence = min(max(c, 0.0), 1.0)
        except ValueError:
            pass
    return domain, confidence, _SALVAGE_REASONING  # type: ignore[return-value]


# Salvage tetiklendiğinde reasoning bu sentinel olur — triaj_node "facts retry"
# yolunu açmak için bunu kontrol eder. Public sabit (test'lerden de okunur).
_SALVAGE_REASONING = "JSON kesildi, domain regex ile kurtarıldı."

# Sadece facts isteyen ikinci-çağrı prompt'u — salvage sonrası eligibility'nin
# atlanmasını önlemek için minimal, sıkı, Türkçe-only.
_FACTS_RETRY_SYSTEM = (
    "Sen Türk hukuk sorularından SOMUT OLGULARI çıkaran bir asistansın. "
    "ÇIKTI YALNIZCA Türkçe ve geçerli JSON olmalı — Çince/İngilizce tek karakter yazma."
)
_FACTS_RETRY_USER = (
    "Aşağıdaki sorudan soruda AÇIKÇA geçen somut olguları çıkar. Uydurma; yoksa boş bırak.\n"
    "İzinli anahtarlar: sure, isci_sayisi, tutar, olay, taraf, tarih.\n"
    "Çıktı yalnız JSON: {{\"facts\": {{\"<anahtar>\": \"<deger>\"}}}}\n\n"
    "Soru: {question}"
)


async def _recover_facts(question: str) -> dict[str, str]:
    """Triaj JSON kesilirse facts'ı ayrı kısa çağrı ile kurtar.

    Salvage path'inde domain regex'le kurtarıldı ama facts tamamen kayboldu →
    eligibility node atlandı → draft zayıf çıktı (tk-01 vakası). Bu kısa çağrı
    yalnız facts ister, çıktı küçük olduğu için Çince sızıntı olasılığı çok
    düşüktür. Hata olursa boş dict.
    """
    try:
        llm = get_llm()
        resp = await llm.chat(
            messages=[
                ChatMessage(role="system", content=_FACTS_RETRY_SYSTEM),
                ChatMessage(role="user", content=_FACTS_RETRY_USER.format(question=question)),
            ],
            temperature=0.0,
            max_tokens=200,
            json_mode=True,
        )
        data = json.loads(resp.content)
        return _sanitize_facts(data.get("facts") if isinstance(data, dict) else None)
    except (json.JSONDecodeError, Exception) as exc:
        log.warning("triaj_facts_retry_failed", error=str(exc) or type(exc).__name__)
        return {}


_CEZA_KEYWORDS = frozenset({
    "ceza hukuku", "ceza davası", "ceza yargılaması", "ceza muhakemesi",
    "ağır ceza", "asliye ceza", "ceza mahkemesi", "cinayet", "öldürme",
    "kasten öldürme", "suç işle", "suç eylem", "tutuklama", "tutuklu", "gözaltı",
})
_AILE_KEYWORDS = frozenset({
    "boşanma davası", "nafaka", "velayet", "evlat edinme",
    "aile hukuku", "aile mahkemesi",
})


def _out_of_scope_reply(question: str) -> str:
    """Kapsam-dışı soru için sıcak, yönlendirici yanıt.

    Hangi kapsam-dışı alan olduğunu tespit eder (ceza/aile) ve kullanıcıya
    neden yardım edemediğini insanca açıklar. Somut hukuki iddia içermez.
    """
    q_low = question.lower()
    is_ceza = any(kw in q_low for kw in _CEZA_KEYWORDS)
    is_aile = any(kw in q_low for kw in _AILE_KEYWORDS)

    if is_ceza:
        return (
            "Ceza hukuku konularında yardımcı olamıyorum — bu alan uzmanlık ve "
            "bireysel değerlendirme gerektirdiğinden sistemimizin kapsamı dışında. "
            "Bu tür davalarda bir ceza avukatına başvurmanızı kesinlikle öneririm. "
            "Baro'nun avukat bulma hizmetinden ya da adli yardım bürosundan "
            "ücretsiz bilgi alabilirsiniz.\n\n"
            "Tüketici hakları, iş hukuku, kira uyuşmazlıkları, icra, trafik, "
            "vergi, tapu veya idari hukuk konularında sormak istediğiniz başka "
            "bir şey var mı?"
        )
    if is_aile:
        return (
            "Boşanma, nafaka, velayet gibi aile hukuku konuları hem hukuken hem "
            "insani açıdan hassas olduğundan sistemimizin kapsamı dışında tutuyoruz. "
            "Bu tür davalarda bir aile hukuku avukatına danışmanız en sağlıklısı olacaktır; "
            "Baro'dan ücretsiz ilk danışmanlık alabilirsiniz.\n\n"
            "Tüketici hakları, iş hukuku, kira uyuşmazlıkları veya diğer sivil hukuk "
            "konularında yardımcı olabilirim — sormak istediğiniz başka bir şey var mı?"
        )
    # Genel kapsam-dışı (keyword eşleşmedi ama domain unknown çıktı)
    return (
        "Bu konuda yardımcı olabilecek yetkinlikte olduğumdan emin değilim. "
        "Tüketici, iş, kira, icra, trafik, vergi, tapu veya idari hukuk "
        "konularında soru sormayı deneyebilirsiniz; bu alanlarda gerçek mevzuat "
        "ve Yargıtay kararlarıyla destek olabilirim."
    )


def _sanitize_facts(raw: object) -> dict[str, str]:
    """LLM facts çıktısını izinli anahtar + kısa string değerlere indir."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, val in raw.items():
        if key not in _ALLOWED_FACT_KEYS:
            continue
        if val is None:
            continue
        sval = str(val).strip()
        if sval and sval.lower() not in {"null", "none", "yok", "-"}:
            out[key] = sval[:_MAX_FACT_VALUE_LEN]
    return out
