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

import json
import math
import re
from pathlib import Path

import structlog

from agents.config import MIN_DOMAIN_CONFIDENCE, OUT_OF_SCOPE_KEYWORDS
from agents.llm import ChatMessage, get_llm
from agents.smalltalk import detect_smalltalk, smalltalk_reply
from agents.state import AgentState, ConversationTurn, Domain
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


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _is_out_of_scope(question: str) -> bool:
    """Kapsam-dışı keyword tespiti — kelime sınırı bilinçli.

    Substring kontrolü "vergi cezası" gibi yasal terimlerde yanlış pozitif
    verir ("ceza" ⊂ "cezası"). Bu yüzden \\b kelime sınırı ile match yapıyoruz.
    Ayrıca "ceza" tek başına değil, "ceza hukuku / ceza davası / ceza yargılaması"
    bağlamında match etmeli — bu yüzden multi-token form'lar tercih edilir.
    """
    import re as _re
    q_low = question.lower()
    for kw in OUT_OF_SCOPE_KEYWORDS:
        # Çok-token ise (örn "ceza hukuku") aynen aranır; tek token ise \b ile
        if " " in kw:
            if kw in q_low:
                return True
        else:
            if _re.search(rf"\b{_re.escape(kw)}\b", q_low):
                return True
    return False


def _is_continuation(question: str) -> bool:
    q_low = question.lower().strip()
    return any(q_low.startswith(m) or f" {m}" in q_low[:30] for m in _CONTINUATION_MARKERS)


def _format_history(history: list[ConversationTurn]) -> str:
    """Son N turu prompt'a uygun string'e dök."""
    if not history:
        return "(geçmiş yok — bu ilk soru)"
    recent = history[-MAX_HISTORY_TURNS_IN_PROMPT:]
    lines = []
    for turn in recent:
        role = "KULLANICI" if turn["role"] == "user" else "ASİSTAN"
        content = turn["content"][:400]  # token tasarrufu
        domain_hint = ""
        if turn.get("domain") and turn["domain"] != "unknown":
            domain_hint = f"  [domain: {turn['domain']}]"
        lines.append(f"{role}{domain_hint}:\n{content}\n")
    return "\n".join(lines)


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
    # Yalnız ilk turda (geçmiş yoksa): konuşma ortasındaki "teşekkürler" yeni soru
    # akışını kesmesin diye chat_history varsa atla.
    if not (state.get("chat_history") or []):
        category = detect_smalltalk(question)
        if category is not None:
            log.info("triaj_smalltalk", category=category, question=question[:60])
            return {
                "domain": "unknown",
                "domain_confidence": 0.0,
                "triage_reasoning": f"Sohbet girdisi ({category}) — hukuki akış atlandı.",
                "smalltalk_response": smalltalk_reply(category),
            }

    if _is_out_of_scope(question):
        log.info("triaj_out_of_scope", question=question[:60])
        return {
            "domain": "unknown",
            "domain_confidence": 0.0,
            "triage_reasoning": "Kapsam dışı: ceza/aile hukuku desteklenmiyor.",
            "smalltalk_response": _out_of_scope_reply(question),
        }

    history: list[ConversationTurn] = state.get("chat_history", []) or []

    # Devam-sorusu kısa-yolu: önceki turun domain'ini koru, LLM çağrısı atlanmaz
    # ama hint olarak prompt'a girer.
    inherited_domain = _last_user_domain(history) if _is_continuation(question) else None

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

    # Salvage olduğunda facts kayboldu (JSON kesildi) → eligibility atlanır → draft
    # zayıf çıkar (tk-01 vakası). Ayrı kısa çağrı ile facts'ı kurtar; domain
    # zaten regex'le kurtarılmıştı, bu sadece olguları geri getirir.
    if reasoning == _SALVAGE_REASONING and not facts and domain != "unknown":
        log.info("triaj_facts_retry", domain=domain)
        facts = await _recover_facts(question)

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
        "case_facts": facts,
    }


# facts dict'inde kabul edilen anahtarlar — LLM serbest anahtar üretse de
# yalnız bunları tutarız (gürültü/halüsinasyon anahtar sızıntısını engeller).
_ALLOWED_FACT_KEYS = {"sure", "isci_sayisi", "tutar", "olay", "taraf", "tarih"}
_MAX_FACT_VALUE_LEN = 120


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
