"""Genel sohbet node'u — hukuki-OLMAYAN sorulara Qwen'in 'gerçek beyni' ile doğal,
akan, ChatGPT-kalitesinde cevap. retrieval/verify YOK (hukuki iddia üretilmez →
sıfır-halüsinasyon kalkanı bu yola gerekmez).

ROUTING: policy.decide_path() smalltalk / out_of_scope_sensitive / unknown-domain
için "chat" döndürür → bu node. Net hukuki domain (8 sivil alan) DOĞRULAMALI boruya
gider (değişmez). Hukuki bir soru yanlışlıkla buraya düşerse, system-prompt somut
madde/karar UYDURMASINI engeller: model kullanıcıyı doğrulamalı akışa yönlendirir
(durumu anlat → kaynaklı cevap). Böylece ChatGPT-akıcılığı + hukukta güvenlik birlikte.

Akış: draft_token_sink set ediliyse (SSE) token'ları canlı yayar (frontend yazıyor görür).
"""

from __future__ import annotations

import re

import structlog

from agents.draft_stream import draft_token_sink
from agents.llm import ChatMessage, get_llm
from agents.risk_guard import verify_risk_veto
from agents.smalltalk import smalltalk_reply
from agents.state import AgentState
from core.observability import observe_node

log = structlog.get_logger()

# Düşük-güven hukuki soru (triaj domain=unknown) verify/veto hattını atlayıp chat'e
# düşebilir. Serbest-form Qwen bir SPESİFİK hukuki iddiaya girerse (uydurma kanun adı,
# imkânsız mahkeme dairesi, süre-eşik gerekçeli hak-reddi) bu deterministik yönlendirme
# devreye girer → uydurma madde/eşik final cevaba/persist'e ULAŞMAZ. Genel sohbet ve
# kavram-açıklamaları bu kalıpları taşımaz → vetolanmaz, akıcılık korunur.
_LEGAL_REDIRECT = (
    "Bu soruya kesin ve güvenilir bir hukuki cevap verebilmem için durumunuzu biraz "
    "daha açmanız gerekiyor — ne olduğunu, tarafları ve varsa süre/tutar bilgisini "
    "birkaç cümleyle yazarsanız, gerçek mevzuat ve Yargıtay kararlarıyla DOĞRULANMIŞ "
    "bir yanıt hazırlarım. Çalıştığım alanlar: tüketici, iş, kira, icra, trafik, vergi, "
    "tapu ve idari hukuk."
)


def _safe_or_redirect(text: str) -> str:
    """Chat çıktısı deterministik içerik-risk veto'sunu tetiklerse (uydurma kanun/daire/
    süre-eşik hak-reddi) güvenli yönlendirme döndür; aksi halde metni aynen geçir.

    Saf fonksiyon (LLM'siz, test edilebilir). source_texts VERİLMEZ → muhafazakâr:
    chat yolunda kaynak getirilmediğinden her doğrulanmamış hukuki iddia riskli sayılır
    (fail-closed; kırmızı çizgi serbest-form yola da uygulanır)."""
    blocked, reasons = verify_risk_veto(text)
    if blocked:
        log.info("chat_risky_redirect", n_reasons=len(reasons))
        return _LEGAL_REDIRECT
    return text

_CHAT_SYSTEM = (
    "Sen ADALET'sin — Türkçe, samimi ve yardımcı bir yapay zeka asistanısın. "
    "Avukata kolay erişemeyen vatandaşlara Türk hukukunda yardımcı olmak için "
    "geliştirildin; ama genel sohbet, günlük konular ve genel bilgi sorularını da "
    "(selam, nasılsın, ne yapabilirsin, genel kültür, tanım soruları) doğal ve "
    "akıcı biçimde yanıtlarsın.\n\n"
    "KURALLAR:\n"
    "- Kısa, sıcak, doğal konuş; soruya doğrudan cevap ver, gereksiz uzatma.\n"
    "- SPESİFİK HUKUKİ soru gelirse (belirli kanun maddesi, dava/Yargıtay kararı, "
    "somut hak/tazminat tutarı, 'şu olayda ne yapmalıyım', kesin süre/eşik): ASLA "
    "madde numarası, karar referansı veya kesin hukuki sonuç UYDURMA. Bunun yerine "
    "kullanıcıdan durumunu birkaç cümleyle anlatmasını iste ki gerçek mevzuat ve "
    "Yargıtay kararlarıyla DOĞRULANMIŞ yanıt hazırlayabilesin. Genel bir hukuk "
    "kavramını sade dille açıklayabilirsin ama somut atıf/numara verme.\n"
    "- Ceza ve aile hukukunda detaylı tavsiye verme; bir avukata danışmayı öner.\n"
    "- Zararlı, yasadışı, nefret içeren veya tehlikeli içerik üretme.\n"
    "- ÇOK ÖNEMLİ: Yanıtının TAMAMI Türkçe olsun — tek bir kelime, harf veya cümle "
    "bile başka dilde (Çince, İngilizce, Japonca vb.) OLMASIN."
)

# Bağlam için eklenecek son tur sayısı (sohbet sürekliliği).
_HISTORY_TURNS = 4
_HISTORY_CHARS = 800

# Qwen ara sıra Çince/Japonca/Korece'ye kayar (bilinen davranış). Yabancı-script
# görülürse cevabı oradan ÖNCEKİ son tam cümleye kırp → temiz Türkçe kalır.
_FOREIGN_SCRIPT_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")


def _strip_foreign_drift(text: str) -> str:
    m = _FOREIGN_SCRIPT_RE.search(text)
    if not m:
        return text
    head = text[: m.start()]
    cut = max(head.rfind("."), head.rfind("!"), head.rfind("?"), head.rfind("\n"))
    return (head[: cut + 1] if cut > 0 else head).strip()


@observe_node(name="chat")
async def chat_node(state: AgentState) -> dict[str, object]:
    """Hukuki-olmayan soruya Qwen ile doğal cevap. response_intent='chat' set eder;
    finalize bunu disclaimer'sız doğrudan basar. retrieval/verify/tahmin YOK."""
    # KIRMIZI ÇİZGİ (CLAUDE.md §4): ceza/aile hukuku LLM'e BIRAKILMAZ — triaj'ın
    # ürettiği deterministik 'avukata danışın' yönlendirmesi kullanılır. Böylece
    # serbest-form LLM bir ceza/aile sorusuna asla detaylı tavsiye veremez (mock'ta
    # bile garanti). Smalltalk/genel sohbet aşağıda Qwen'in gerçek beynine gider.
    if state.get("response_intent") == "out_of_scope_sensitive":
        text = (state.get("smalltalk_response") or "").strip() or (
            "Bu konu sistemimizin kapsamı dışında; bu alanda bir avukata "
            "danışmanızı öneririm. Tüketici, iş, kira, icra, trafik, vergi, tapu "
            "veya idari hukuk konularında yardımcı olabilirim."
        )
        sink = draft_token_sink.get()
        if sink is not None:
            sink(text)  # SSE: deterministik mesajı da 'yazılıyor' gibi akıt
        log.info("chat_out_of_scope_deterministic", n_chars=len(text))
        return {
            "response": text,
            "response_intent": "chat",
            "confidence": 1.0,
            "disclaimers": [],
            "prediction": None,
        }

    question = state.get("question", "")
    messages = [ChatMessage(role="system", content=_CHAT_SYSTEM)]
    for turn in (state.get("chat_history") or [])[-_HISTORY_TURNS:]:
        role = turn.get("role")
        content = (turn.get("content") or "")[:_HISTORY_CHARS]
        if role in ("user", "assistant") and content:
            messages.append(ChatMessage(role=role, content=content))
    messages.append(ChatMessage(role="user", content=question))

    llm = get_llm()
    sink = draft_token_sink.get()
    text = ""
    try:
        if sink is not None and hasattr(llm, "chat_stream"):
            resp = await llm.chat_stream(
                messages=messages, temperature=0.4, max_tokens=512, on_token=sink,
            )
        else:
            resp = await llm.chat(
                messages=messages, temperature=0.4, max_tokens=512, json_mode=False,
            )
        text = _strip_foreign_drift((resp.content or "").strip())
    except Exception as exc:
        # Qwen patlarsa sohbeti bloke etme — basit dostça fallback (hardcode son çare).
        log.warning("chat_llm_failed_fallback", error=str(exc) or type(exc).__name__)

    if not text:
        text = smalltalk_reply("greeting")

    text = _safe_or_redirect(text)  # kırmızı-çizgi backstop (uydurma hukuki iddia → yönlendir)
    log.info("chat_done", n_chars=len(text))
    return {
        "response": text,
        "response_intent": "chat",  # finalize bunu görür → doğrudan basar (şemada)
        "confidence": 1.0,
        "disclaimers": [],
        "prediction": None,
    }


__all__ = ("chat_node",)
