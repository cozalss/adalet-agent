"""Finalize ajanı — son cevabı topla, disclaimer ekle, güven skorunu hesapla.

E2E baseline akış için verify/debate atlanabilir; bu node tek başına da çalışır.
"""

from __future__ import annotations

import re

import structlog

from agents.config import DISCLAIMER_TR, is_partial_answer_note_enabled
from agents.nodes.compose import redirect_to_scope_fallback
from agents.state import AgentState
from core.observability import observe_node

log = structlog.get_logger()

# Cümle ayraç + kaynak etiketi. Bölücü kısmen muhafazakar: "m. 11" gibi hukuk
# kısaltmalarında parçalamaz, ama cümle küçük harf/rakam/bullet ile devam etse de
# güvenlik filtresine daha küçük birim verir.
_SENT_BOUNDARY_RE = re.compile(r"(?<=[.!?\]])\s+")
_SRC_TAG_RE = re.compile(r"\[src:\s*([A-Za-z0-9_\-]+)\s*\]")
_NO_SPLIT_ABBREVIATIONS = {"m", "md", "no", "bkz", "vb", "vs", "dr", "av", "prof", "doç"}
# "Kısa cevap" başlık-kaybı guard'ı: verify filtresi ilk bölümü düşürürse gövde başka bir
# kalın-başlıkla başlar; zorunlu özet başlığı eklenir (hukuki iddia DEĞİL).
_KISACEVAP_RE = re.compile(r"^\s*\*\*\s*Kısa cevap", re.IGNORECASE)
_BOLD_HEADER_RE = re.compile(r"^\s*\*\*[^*\n]{1,80}:\*\*")
# Partial-answer dürüst notu — bazı iddialar kaynaklanamayıp düştüğünde eklenir (opt-in).
_PARTIAL_ANSWER_NOTE = (
    "*Not: Sorunuzdaki bazı noktaları güvenilir bir kaynakla doğrulayamadığım için yanıta "
    "yalnızca doğrulayabildiğim kısımları aldım. Eksik kalan konuları ayrı ayrı sorarsanız "
    "daha sağlıklı yardımcı olabilirim.*"
)


def _chat_needs_disclaimer(question: str, response: str) -> bool:
    """Chat yanıtı hukuki KAVRAM içeriyorsa (soru veya cevapta hukuki ipucu) True →
    disclaimer eklenir. Saf selam/teşekkür (ipuçsuz) → False, gereksiz disclaimer yok."""
    from agents.smalltalk import _has_legal_hint, _normalize
    return _has_legal_hint(_normalize(question)) or _has_legal_hint(_normalize(response))


_LEADING_ORPHAN_HEADER_RE = re.compile(
    # YALNIZ gövde başındaki, içeriği kalmamış bölüm başlığı (sonrası boş/yeni-başlık/son).
    # Gövde ilerisindeki "**Başlık:**\nsonraki-satırda-içerik" başlıklarına DOKUNMAZ.
    r"^[ \t]*\*\*[^*\n]{1,80}:\*\*[ \t]*(?:\n+(?=\*\*|\Z)|\Z)"
)


def _first_content_sentence(text: str) -> str | None:
    """İlk KAYNAĞA-BAĞLI ([src:] taşıyan) içerik cümlesini döndür.

    Yalnız [src:] etiketli cümle promote edilir → BLUF daima bir kaynağa bağlıdır;
    claim-çıkarıcının kaçırdığı dayanaksız çıkarım (ör. süre-uygunluk halüsinasyonu)
    en görünür konuma TAŞINMAZ (CLAUDE.md §1). Başlık öneki sökülür; Türkçe sıra/
    madde-no fragmanı ('342.') YALNIZ aynı bölüm içinde sonraki span'le birleştirilir
    (yeni başlıkta sıfırlanır → bölüm sınırını aşan var-olmayan birleşik cümle YOK). Yoksa None.
    """
    buf = ""
    for _start, _end, sent in _sentence_spans(text):
        raw = sent.strip()
        # Yeni bölüm başlığıyla başlayan span → biriken fragmanı sıfırla (bölüm
        # sınırını geçip var-olmayan birleşik cümle üretme — adversarial MEDIUM).
        if buf and _BOLD_HEADER_RE.match(raw):
            buf = ""
        content = raw
        while True:
            nxt = _BOLD_HEADER_RE.sub("", content, count=1).strip()
            if nxt == content:
                break
            content = nxt
        if not content:
            continue
        buf = f"{buf} {content}".strip() if buf else content
        if re.search(r"\d\.$", buf) and len(buf) < 240:
            continue  # sıra/madde-no fragmanı → bölüm İÇİNDE birleştir
        if "[src:" in buf:
            return buf            # yalnız kaynağa-bağlı cümle promote edilir
        buf = ""                  # [src:]'siz tam cümle (framing/çıkarım) → promote ETME, atla
    return None


def _promote_first_verified_as_bluf(text: str) -> str:
    """Gövde 'Kısa cevap' DIŞINDA bir kalın-başlıkla başlıyorsa (verify orijinal BLUF'u
    düşürdü veya model atladı) ilk KAYNAĞA-BAĞLI cümleyi 'Kısa cevap' olarak öne çek.

    Promote edilen cümle text'ten ([src:] etiketli, _filter_to_verified'dan geçmiş)
    VERBATIM alınır → grounding korunur (yeni/uydurma iddia ÜRETİLMEZ). Eski boilerplate
    placeholder'ın YERİNE geçer. No-op: BLUF zaten var / gövde düz metin / [src:]'li içerik
    cümlesi yok / cümle gövdede birebir bulunamıyor (graceful — tekrar ÜRETME)."""
    body = text.lstrip()
    if _KISACEVAP_RE.match(body):          # BLUF zaten var → dokunma (çift başlık olmaz)
        return text
    if not _BOLD_HEADER_RE.match(body):    # düz metin başı → yapısal boşluk yok
        return text
    first_sentence = _first_content_sentence(body)
    if not first_sentence or first_sentence not in body:
        # içerik yok VEYA birleştirme whitespace farkı (paragraf-arası) → no-op (tekrar ÜRETME)
        return text
    # Çift gösterimi önle: cümleyi gövdeden çıkar; arta kalan SADECE-BAŞTAKİ boş başlığı sil
    # (gövde ilerisindeki gerçek başlıkları KORU — adversarial HIGH).
    remainder = body.replace(first_sentence, "", 1)
    remainder = _LEADING_ORPHAN_HEADER_RE.sub("", remainder, count=1)
    remainder = re.sub(r"[ \t]{2,}", " ", re.sub(r"\n{3,}", "\n\n", remainder)).strip()
    if remainder:
        return f"**Kısa cevap:** {first_sentence}\n\n{remainder}"
    return f"**Kısa cevap:** {first_sentence}"


@observe_node(name="finalize")
async def finalize_node(state: AgentState) -> dict:
    import time as _time
    _t0 = _time.perf_counter()
    domain = state.get("domain", "unknown")
    verdict = state.get("debate_verdict", "pass")

    # Genel sohbet (chat node Qwen ile doğal cevap ürettiyse): doğrudan bas.
    # Hukuki iddia yok → hukuki disclaimer yok, reddetme yok. ChatGPT-akıcılığı.
    # Sinyal response_intent="chat" (chat_response şema-dışıydı → düşüyordu); response
    # ve response_intent şemada → güvenle merge olur.
    if state.get("response_intent") == "chat":
        log.info("finalize_chat")
        resp = state.get("response") or ""
        # CLAUDE.md §2: hukuki KAVRAM açıklaması içeren chat yanıtına disclaimer EKLE
        # (saf selam/teşekkür hariç). Aksi halde hukuki bilgi disclaimer'sız çıkıyordu.
        disc: list[str] = []
        if _chat_needs_disclaimer(state.get("question", ""), resp) and DISCLAIMER_TR not in resp:
            resp = resp.rstrip() + "\n\n" + DISCLAIMER_TR
            disc = [DISCLAIMER_TR]
        return {
            "response": resp,
            "confidence": 1.0,
            "disclaimers": disc,
            "prediction": None,
        }

    # Sohbet kısa-yolu (triaj set etti): hazır dostça yanıtı doğrudan bas.
    # Hukuki içerik yok → soğuk ret yerine sıcak karşılama, hukuki disclaimer yok.
    smalltalk = state.get("smalltalk_response")
    if smalltalk:
        if state.get("response_intent") == "out_of_scope_sensitive":
            log.info("finalize_out_of_scope_sensitive")
            return {
                "response": smalltalk,
                "confidence": 0.0,
                "disclaimers": [],
                "prediction": None,
                "debate_verdict": "reject",
            }
        log.info("finalize_smalltalk")
        return {
            "response": smalltalk,
            "confidence": 1.0,
            "disclaimers": [],
            "prediction": None,
        }

    # Netleştirme (clarifier set etti): hazır takip sorularını doğrudan bas.
    # Hukuki iddia yok → disclaimer yok. SIRA KRİTİK: clarify domaini geçerli +
    # verdict default "pass" olduğundan, bu dal aşağıdaki reject/legal-assembly
    # yolundan ÖNCE gelmeli; aksi halde boş draft'tan reject'e düşer.
    clarify = state.get("clarify_response")
    if state.get("response_intent") == "needs_clarification" and clarify:
        log.info("finalize_clarify")
        return {
            "response": clarify,
            "confidence": 0.0,
            "disclaimers": [],
            "prediction": None,
        }

    # Reddedildi → boilerplate avukat tavsiyesi
    if domain == "unknown" or verdict != "pass":
        return _reject_response(state)

    draft = state.get("draft_response", "").strip()
    claims = state.get("claims", []) or []
    verified_claims = state.get("verified_claims", []) or []
    if not verified_claims and claims:
        verified_claims = claims
    if not claims and verified_claims:
        claims = verified_claims

    if not draft:
        return _reject_response(state)

    n_claims = len(claims)
    n_verified = len([c for c in verified_claims if c.get("verified", False)])

    # İddia yoksa veya hiçbir iddia doğrulanmadıysa gösterilecek güvenli içerik yok.
    if n_claims == 0 or n_verified == 0:
        return _reject_response(state, _unverified_claims_reason(verified_claims))

    # Fail-closed ama kapsam-koruyan: doğrulanmamış iddiaların cümlelerini taslaktan
    # ÇIKAR, doğrulanmış içeriği göster. Halüsinasyon kullanıcıya gitmez (CLAUDE.md §1)
    # ama tüm cevabı reddetmeyiz — vatandaş doğrulanmış kısımdan yararlanır.
    filtered_draft, n_dropped = _filter_to_verified(draft, claims, verified_claims)
    filtered_draft = _remove_orphan_source_tags(filtered_draft)
    if not filtered_draft.strip():
        return _reject_response(state, _unverified_claims_reason(verified_claims))
    filtered_draft = _promote_first_verified_as_bluf(filtered_draft)
    # Citation bloğu — GÖSTERİLEN (filtrelenmiş) hukuki gövdeden, partial-NOT EKLENMEDEN ÖNCE
    # (MEDIUM-3 + ECC-sweep: not metni hiçbir koşulda kaynak çıkarımına karışmaz — phantom-source yalıtımı).
    citations_md = _format_citations(state, filtered_draft)
    # Dilekçe linki (6. ajan üretmişse) — sadece markdown atıfı, bytes API'den
    # GET /dilekce/{conversation_id} ile servis edilir (bkz. api/routes/dilekce).
    dilekce_md_block = _format_dilekce_link(state)
    # Proaktif eylem teklifi (deterministik, hukuki iddia YOK): dilekçe linki yoksa +
    # domain'e uygun anahtar gövdede geçiyorsa tek satır "...hazırlamamı ister misiniz?".
    # Partial-note EKLENMEDEN ÖNCE hesapla → boilerplate not metni keyword tetiklemesin (adversarial MEDIUM).
    offer_line = _next_step_offer(domain, filtered_draft, bool(dilekce_md_block))
    # Partial-answer ŞEFFAFLIĞI (opt-in): bazı iddialar kaynaklanamayıp DÜŞTÜYSE (çok-konulu
    # sorularda sık) sessiz-eksiltme yerine dürüstçe belirt. Grounding değişmez (ungrounded zaten yok).
    if n_dropped > 0 and is_partial_answer_note_enabled():
        filtered_draft = f"{filtered_draft}\n\n{_PARTIAL_ANSWER_NOTE}"
    final = (
        f"{filtered_draft}"
        f"{dilekce_md_block}"
        f"{offer_line}"
        f"\n\n---\n**Kaynaklar:**\n{citations_md}\n\n{DISCLAIMER_TR}"
    )

    confidence = _compute_confidence(state, verified_claims)

    log.info(
        "finalize_done",
        confidence=confidence, n_claims=len(verified_claims), dropped=n_dropped,
        elapsed_ms=round((_time.perf_counter() - _t0) * 1000),
    )
    return {
        "response": final,
        "confidence": confidence,
        # Güven ŞEFFAFLIĞI: çıplak skor yerine etiket + "n_verified/n_total iddia
        # doğrulandı" (anti-halüsinasyon kalkanını GÖRÜNÜR kılar). Yeni iddia ÜRETMEZ.
        "confidence_label": _confidence_label(confidence),
        "n_verified_claims": n_verified,
        "n_total_claims": n_claims,
        "disclaimers": [DISCLAIMER_TR],
        # Tahmin (8. ajan) hesapladıysa state'te var; pass cevapta gösterilir.
        "prediction": state.get("prediction"),
    }


def _normalize_sentence(text: str) -> str:
    """Karşılaştırma için normalize: kaynak etiketini sil, boşlukları sıkıştır, küçült."""
    return " ".join(_SRC_TAG_RE.sub("", text).split()).lower()


def _split_sentences(text: str) -> list[str]:
    """Cümleleri ayır; hukuk kısaltmalarındaki noktaları boundary sayma."""
    return [sent for _start, _end, sent in _sentence_spans(text)]


def _sentence_spans(text: str) -> list[tuple[int, int, str]]:
    """Cümleleri (start, end, text) olarak döndür; orijinal boşlukları korumaya yarar."""
    if not text.strip():
        return []
    out: list[tuple[int, int, str]] = []
    start = 0
    for match in _SENT_BOUNDARY_RE.finditer(text):
        if not _should_split_at(text, match.start()):
            continue
        end = match.start()
        chunk = text[start:end].strip()
        if chunk:
            out.append((start, end, chunk))
        start = match.end()
    tail = text[start:].strip()
    if tail:
        out.append((start, len(text), tail))
    return out


def _should_split_at(text: str, boundary_pos: int) -> bool:
    after = text[boundary_pos:].lstrip()
    if after.startswith("[src:"):
        return False
    prev = text[:boundary_pos].rstrip()
    if not prev:
        return False
    stem = prev[:-1].rstrip() if prev[-1] in ".!?" else prev
    token_match = re.search(r"([A-Za-zÇĞİÖŞÜçğıöşü]+)$", stem)
    token = token_match.group(1).lower() if token_match else ""
    return token not in _NO_SPLIT_ABBREVIATIONS


def _filter_to_verified(draft: str, claims: list, verified: list) -> tuple[str, int]:
    """Doğrulanmamış claim'lere karşılık gelen cümleleri taslaktan çıkar.

    claim["text"] (draft cümlesinden çıkarılmıştı) ile draft cümleleri normalize
    edilip eşleştirilir. Bir cümle doğrulanmamış bir claim'le eşleşiyor AMA aynı
    zamanda doğrulanmış bir claim'le eşleşmiyorsa atılır. İddia olmayan cümleler
    (giriş, disclaimer) ve doğrulanmış cümleler korunur.

    Returns:
        (filtrelenmiş taslak, atılan cümle sayısı)
    """
    verified_txt = {
        _normalize_sentence(c["text"]) for c in verified if c.get("verified", False)
    }
    verified_txt = {v for v in verified_txt if v}
    all_claims = {_normalize_sentence(c["text"]) for c in claims}
    all_claims = {c for c in all_claims if c}
    unverified = list(
        {_normalize_sentence(c["text"]) for c in verified if not c.get("verified", False)}
        | (all_claims - verified_txt)
    )
    unverified = [u for u in unverified if u]
    if not unverified:
        return draft, 0

    pieces: list[str] = []
    cursor = 0
    dropped = 0
    for start, end, sent in _sentence_spans(draft):
        norm = _normalize_sentence(sent)
        if not norm:
            pieces.append(draft[cursor:end])
            cursor = end
            continue
        # Yalnız tek yönlü substring: doğrulanmamış claim cümle İÇİNDE geçiyorsa
        # cümle atılır (halüsinasyon sızıntısı önlenir). Önceki çift-yönlü kural
        # ("norm in u" dahil) çok cömertti: yapısal cevapta kısa yan-cümleler
        # daha uzun unverified claim'in alt-parçası gibi görünüp atılıyordu
        # (16-soru testinde finalize 12 cümle düşürdü → cevap 1-2 cümleye indi).
        # "u in norm" yeterlidir; "norm in u" yanlış-pozitif kapsam silmesidir.
        is_unverified = any(u and u in norm for u in unverified)
        if is_unverified:
            dropped += 1
            cursor = end
            continue
        pieces.append(draft[cursor:start])
        pieces.append(draft[start:end])
        cursor = end
    pieces.append(draft[cursor:])
    filtered = "".join(pieces)
    filtered = re.sub(r"\n{3,}", "\n\n", filtered)
    filtered = re.sub(r"[ \t]{2,}", " ", filtered)
    return filtered.strip(), dropped


def _remove_orphan_source_tags(text: str) -> str:
    """Cümle silme sonrası tek başına kalan [src: ...] etiketlerini temizle."""
    text = re.sub(r"(^|\n)\s*\[src:\s*[A-Za-z0-9_\-]+\s*\]\s*(?=\n|$)", r"\1", text)
    text = re.sub(r"^\s*\[src:\s*[A-Za-z0-9_\-]+\s*\]\s*", "", text)
    return text.strip()


# Reject mesajı domain-aware yardımcı hint'leri — dead-end yerine "şunu paylaşın".
# Hukuki iddia YOK (sadece hangi olgu retrieval/grounding'i mümkün kılar) → kırmızı-çizgi güvenli.
_DOMAIN_READABLE: dict[str, str] = {
    "tuketici": "tüketici", "isHukuku": "iş", "kira": "kira", "icra": "icra",
    "trafik": "trafik", "vergi": "vergi", "tapu": "tapu", "idari": "idari",
}
_REJECT_HELP_HINTS: dict[str, str] = {
    "tuketici": "ürün/hizmeti, sorunu (ayıplı mal/iade/cayma) ve satın alma tarihini",
    "isHukuku": "çalışma sürenizi, işten ayrılma şeklini (istifa/fesih) ve tarihleri",
    "kira": "kiracı mı ev sahibi mi olduğunuzu, konuyu (depozito/tahliye/kira artışı) ve tutarı",
    "icra": "takibin türünü (ödeme emri/haciz), tarihini ve itiraz edip etmediğinizi",
    "trafik": "olayı (kaza/trafik cezası), tarihini ve tarafları",
    "vergi": "vergi/ceza türünü, tebliğ tarihini ve uzlaşma/itiraz durumunuzu",
    "tapu": "işlem türünü (devir/tescil/ipotek) ve taşınmaza dair bilgileri",
    "idari": "hangi idari işleme/karara karşı olduğunuzu ve tebliğ tarihini",
}


def _reject_help_body(domain: str, verdict: str) -> str:
    """Domain biliniyorsa actionable, ne-paylaşılmalı reject mesajı (dead-end değil).

    Hukuki iddia içermez — yalnız retrieval/grounding'i mümkün kılacak OLGULARI ister.
    Hint yoksa (beklenmez; 8 domain de tanımlı) jenerik mesaja düşer."""
    hint = _REJECT_HELP_HINTS.get(domain)
    readable = _DOMAIN_READABLE.get(domain, "")
    if not hint:
        return (
            "Bu soruya şu an net bir yanıt veremiyorum. Konuyu biraz daha ayrıntılı "
            "anlatırsanız yeniden deneyebilirim; karmaşık bir durumsa bir avukata danışmanızı öneririm."
        )
    alan = f"{readable} hukukunda " if readable else ""
    if verdict == "retry":
        return (
            f"Bu soruyu güvenilir kaynaklarla yanıtlayamadım. {alan}size daha sağlıklı yardımcı "
            f"olabilmem için {hint} yazarsanız tekrar deneyebilirim; karmaşık bir durumsa bir "
            f"avukata danışmanızı öneririm."
        )
    return (
        f"Bu soruya net bir yanıt verebilmem için biraz daha bilgiye ihtiyacım var. {alan}"
        f"{hint} paylaşırsanız size daha iyi yardımcı olabilirim."
    )


def _reject_response(state: AgentState, reason: str | None = None) -> dict:
    # Teknik iç nedeni kullanıcıya gösterme — yalnız logla (güven kırıcı jargon).
    internal_reason = reason or state.get("debate_notes") or state.get("triage_reasoning") or ""
    log.info("finalize_reject", internal_reason=internal_reason[:200])

    verdict = state.get("debate_verdict", "pass")
    domain = state.get("domain", "unknown")

    # Yanıt tonu: neyin neden olmadığını kısaca, insanca açıkla; kullanıcıyı yönlendir.
    if domain == "unknown":
        # Kapsam-dışı/belirsiz = dostça YÖNLENDİRME, gerçek "verify-reddi" DEĞİL.
        # response_intent="redirect" → frontend soğuk RejectCard yerine yumuşak
        # baloncuk gösterir. verdict "reject" kalır (hukuki cevap üretilmedi) ama
        # frontend response_intent'e bakıp tonu yumuşatır.
        body = state.get("composed_response") or redirect_to_scope_fallback()
        return {
            "response": body,
            "confidence": 0.0,
            "disclaimers": [],
            "prediction": None,
            "debate_verdict": "reject",
            "response_intent": "redirect",
        }
    # Domain biliniyor (unknown yukarıda döndü) → dead-end yerine actionable, domain-aware
    # "şunu paylaşın" mesajı (graceful refusal that still helps). Hukuki iddia yok.
    body = _reject_help_body(domain, verdict)

    return {
        "response": f"{body}\n\n{DISCLAIMER_TR}",
        "confidence": 0.0,
        "disclaimers": [DISCLAIMER_TR],
        "prediction": None,
        "debate_verdict": "reject",
    }


def _format_dilekce_link(state: AgentState) -> str:
    """Dilekçe Ajanı PDF üretmişse cevaba 'İndir' linki ekle.

    State'te `dilekce_pdf_bytes` ve `conversation_id` varsa public endpoint
    URL'i (kullanıcı klikleyince stream eder). Yoksa boş string (no-op).
    Bytes'ı response içine gömmeyiz (KVKK + bandwidth — bkz. ADR/architect).
    """
    if not state.get("dilekce_pdf_bytes"):
        return ""
    cid = state.get("conversation_id") or ""
    filename = state.get("dilekce_filename") or "dilekce.pdf"
    template_id = state.get("dilekce_template_id") or ""
    # conversation_id yoksa (eski client) placeholder — frontend nasıl alacağına
    # karar verir. KVKK: file_id veya token sunulmaz.
    url = f"/api/dilekce/{cid}" if cid else "(önizleme için conversation_id gerekli)"
    return (
        "\n\n---\n"
        f"📂 **Hazır dilekçe:** [{filename}]({url})  \n"
        f"*Şablon:* `{template_id}`"
    )


# Proaktif eylem teklifi tablosu — (anahtar-kelimeler, teklif) çiftleri, domain bazlı.
# SIRA = öncelik (ilk TEMİZ eşleşen kazanır). Teklif metni bir SORU/UI önerisidir —
# yasal referans/iddia/madde-no İÇERMEZ (kırmızı-çizgi güvenli). Türkçe sondan-eklemeli:
# kök-anahtarlar ("trafik cezas", "maaş alacağ") çekim eklerini de yakalar (cezası/cezasına).
# Anahtarlar OLABİLDİĞİNCE çok-kelimeli/spesifik (bare "ceza"/"zam"/"itiraz" → yanlış-pozitif).
_OfferRule = tuple[tuple[str, ...], str]  # (anahtar-kelimeler, teklif metni)
_NEXT_STEP_OFFERS: dict[str, tuple[_OfferRule, ...]] = {
    "tuketici": (
        (("ayıpl", "garanti", "onarım", "değişim"), "Ayıplı mal için şikayet/iade dilekçesi taslağı hazırlamamı ister misiniz?"),
        (("cayma", "mesafeli", "online sipariş"), "Cayma hakkı bildirimi taslağı hazırlamamı ister misiniz?"),
        (("hakem heyeti", "tüketici mahkemesi"), "Tüketici hakem heyeti başvuru dilekçesi taslağı hazırlamamı ister misiniz?"),
        (("iade", "geri ödeme", "ücret iadesi"), "İade talebi için dilekçe taslağı hazırlamamı ister misiniz?"),
    ),
    # kıdem önce: salt tazminat sorusu işe-iade sorusundan yaygın.
    "isHukuku": (
        (("kıdem",), "Kıdem tazminatı talep dilekçesi taslağı hazırlamamı ister misiniz?"),
        (("işe iade", "haksız fesih", "geçersiz fesih"), "İşe iade başvuru dilekçesi taslağı hazırlamamı ister misiniz?"),
        (("ihbar tazminat", "ihbar süre"), "İhbar tazminatı talep dilekçesi taslağı hazırlamamı ister misiniz?"),
        (("fazla mesai", "ödenmemiş ücret", "maaş alacağ"), "Ücret/fazla mesai alacağı için ihtarname taslağı hazırlamamı ister misiniz?"),
    ),
    "kira": (
        (("depozito", "güvence bedeli"), "Depozito iadesi için ihtarname taslağı hazırlamamı ister misiniz?"),
        (("tahliye",), "Tahliye süreci için dilekçe taslağı hazırlamamı ister misiniz?"),
        (("kira artış", "artış oran", "kira zam"), "Kira artışına itiraz için ihtarname taslağı hazırlamamı ister misiniz?"),
    ),
    "icra": (
        (("ödeme emri", "ödeme emrine"), "Ödeme emrine itiraz dilekçesi taslağı hazırlamamı ister misiniz?"),
        (("haciz",), "Hacze itiraz dilekçesi taslağı hazırlamamı ister misiniz?"),
    ),
    "trafik": (
        (("trafik cezas", "idari para cezas"), "Trafik cezasına itiraz dilekçesi taslağı hazırlamamı ister misiniz?"),
        (("kaza", "hasar", "tazminat"), "Tazminat talep dilekçesi taslağı hazırlamamı ister misiniz?"),
    ),
    "vergi": (
        (("uzlaşma", "vergi cezas"), "Vergi cezası uzlaşma/itiraz dilekçesi taslağı hazırlamamı ister misiniz?"),
        (("kdv iade", "vergi iade"), "Vergi iadesi başvuru dilekçesi taslağı hazırlamamı ister misiniz?"),
    ),
    "tapu": (
        (("ipotek", "şerh", "takyidat"), "İpotek/şerh kaldırma dilekçesi taslağı hazırlamamı ister misiniz?"),
        (("tescil", "tapu devri"), "Tapu işlemi için başvuru dilekçesi taslağı hazırlamamı ister misiniz?"),
    ),
    "idari": (
        (("iptal davası", "yürütmeyi durdurma"), "İdari iptal davası dilekçesi taslağı hazırlamamı ister misiniz?"),
        (("idari itiraz", "itiraz dilekçesi", "itiraz süre", "idari başvuru"), "İdari itiraz/başvuru dilekçesi taslağı hazırlamamı ister misiniz?"),
    ),
}

# Cevap bir HAKKI REDDEDİYORSA (anahtar yakınında olumsuzluk) teklif sunulmaz — çelişkili
# "dilekçe hazırlayayım mı?" önerisini engeller (adversarial HIGH: tone-deaf offer).
_NEG_TOKENS = (
    "değil", "yok", "bulunmamakta", "bulunmuyor", "olamaz", "olmaz", "edilemez",
    "edemez", "kalmamış", "kapan", "dolmuş", "düşmüş", "kazanamaz", "kazanmaz",
    "yapılamaz", "hakkınız bulunma",
)


def _tr_lower(s: str) -> str:
    """Türkçe-duyarlı küçük harf: İ→i, I→ı (Python .lower() İ'yi combining 'i̇' yapıp
    'i' ile başlayan anahtar eşleşmelerini bozar — adversarial HIGH)."""
    return s.replace("İ", "i").replace("I", "ı").lower()


def _has_negation_near(low: str, pos: int, window: int = 75) -> bool:
    """pos çevresinde (±window) olumsuzlama belirteci var mı (zaten _tr_lower'lı metin)."""
    seg = low[max(0, pos - window):pos + window]
    return any(neg in seg for neg in _NEG_TOKENS)


def _next_step_offer(domain: str, body: str, dilekce_shown: bool) -> str:
    """Tek-satır proaktif eylem teklifi — deterministik, LLM yok, hukuki iddia YOK.

    Teklif YALNIZCA: dilekçe linki yokken + domain biliniyor + yanıt gövdesinde ilgili
    anahtar geçiyor + o anahtarın YAKININDA olumsuzluk YOK (cevap hakkı reddetmiyorsa).
    Aksi halde "" → alakasız/çelişkili teklif İLİŞTİRİLMEZ (gürültüsüz). Metin bir SORU'dur
    (yasal referans/iddia içermez) → kırmızı-çizgi güvenli. Yalnız legal-answer path'inden çağrılır.
    """
    if dilekce_shown:
        return ""
    rules = _NEXT_STEP_OFFERS.get(domain)
    if not rules:
        return ""
    low = _tr_lower(body)
    for keywords, offer in rules:
        for kw in keywords:
            pos = low.find(kw)
            if pos != -1 and not _has_negation_near(low, pos):
                return f"\n\n💡 *{offer}*"   # ilk TEMİZ (olumsuzluksuz) eşleşme kazanır
    return ""


def _format_citations(state: AgentState, cited_text: str | None = None) -> str:
    # ECC review MEDIUM-3: kaynak listesini GÖSTERİLEN (filtrelenmiş) metinden çıkar — verify'da
    # düşen cümlenin [src:] etiketi "Kaynaklar"da listelenmesin (şeffaflık). cited_text verilmezse
    # ham draft_response (geriye-uyum: doğrudan çağıran testler).
    src_text = cited_text if cited_text is not None else (state.get("draft_response", "") or "")
    cited_ids = set(_SRC_TAG_RE.findall(src_text))
    raw_refs = list(state.get("mevzuat_refs", []) or []) + list(state.get("emsal_refs", []) or [])
    if cited_ids:
        cited_refs = [r for r in raw_refs if r.get("source_id") in cited_ids]
        if cited_refs:
            raw_refs = cited_refs

    refs = []
    seen: set[str] = set()
    for r in raw_refs:
        key = r.get("source_id") or f"{r.get('doc_type')}:{r.get('title')}:{r.get('url')}"
        if key in seen:
            continue
        seen.add(key)
        kind = "Mevzuat" if r.get("doc_type") == "law" else "Emsal"
        url = str(r.get("url") or "").strip()
        suffix = f" ({url})" if url else ""
        refs.append(f"- [{kind}] {r['title']}{suffix}")
        if len(refs) >= 8:
            break
    return "\n".join(refs) if refs else "(kaynak bulunamadı)"


def _compute_confidence(state: AgentState, verified: list) -> float:
    """Basit harman: domain güveni + doğrulanmış claim oranı + retrieval kalitesi."""
    dom_conf = state.get("domain_confidence", 0.0)
    n_claims = len(state.get("claims", []) or [])
    # Fail-closed: "verified" anahtarı yoksa (doğrulama atlanmış/eksik) iddiayı
    # doğrulanmamış say. Güven skorunu şişirmemek için varsayılan False.
    n_ver = len([c for c in verified if c.get("verified", False)])
    claim_ratio = (n_ver / n_claims) if n_claims else 1.0

    refs = (state.get("mevzuat_refs") or []) + (state.get("emsal_refs") or [])
    retrieval_score = min(1.0, sum(r["score"] for r in refs[:5]) / 5.0) if refs else 0.0

    return round(0.4 * dom_conf + 0.4 * claim_ratio + 0.2 * retrieval_score, 3)


# Güven etiketi — float skoru vatandaş-okunur etikete çevirir (çıplak %X anlamsız).
# Eşikler _compute_confidence formülünden (0.4*dom + 0.4*claim_ratio + 0.2*retrieval)
# türetildi: ~0.40 reddedilmeyen bir cevabın taban skoru; 0.70 hem domain net hem
# claim oranı yüksek demek ([[verify-calibration-harness]] NLI 0.70 ölçülmüş-optimal).
_LABEL_HIGH = "Yüksek güven"
_LABEL_MEDIUM = "Orta güven"
_LABEL_LOW = "Dikkatli olun"
_THRESHOLD_HIGH = 0.70
_THRESHOLD_MEDIUM = 0.45


def _confidence_label(confidence: float) -> str:
    """Float güven skorunu insan-okunur Türkçe etikete çevir (saf fonksiyon)."""
    if confidence >= _THRESHOLD_HIGH:
        return _LABEL_HIGH
    if confidence >= _THRESHOLD_MEDIUM:
        return _LABEL_MEDIUM
    return _LABEL_LOW


def _unverified_claims_reason(verified: list) -> str:
    n_total = len(verified)
    n_unverified = len([c for c in verified if not c.get("verified", False)])
    first_reason = next(
        (str(c.get("verify_reason", "")) for c in verified if not c.get("verified", False)),
        "",
    )
    detail = f"{n_unverified}/{n_total} iddia doğrulanamadı."
    return f"{detail} İlk neden: {first_reason}" if first_reason else detail
