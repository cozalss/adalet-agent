"""Finalize ajanı — son cevabı topla, disclaimer ekle, güven skorunu hesapla.

E2E baseline akış için verify/debate atlanabilir; bu node tek başına da çalışır.
"""

from __future__ import annotations

import re

import structlog

from agents.config import DISCLAIMER_TR
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


@observe_node(name="finalize")
async def finalize_node(state: AgentState) -> dict:
    import time as _time
    _t0 = _time.perf_counter()
    domain = state.get("domain", "unknown")
    verdict = state.get("debate_verdict", "pass")

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

    # Citation bloğu
    citations_md = _format_citations(state)
    # Dilekçe linki (6. ajan üretmişse) — sadece markdown atıfı, bytes API'den
    # GET /dilekce/{conversation_id} ile servis edilir (bkz. api/routes/dilekce).
    dilekce_md_block = _format_dilekce_link(state)
    final = (
        f"{filtered_draft}"
        f"{dilekce_md_block}"
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
    if verdict == "retry":
        # retry-limit doldu, debate "reject"e çevirdi
        body = (
            "Bu konuda güvenilir bir yanıt oluşturmayı birkaç kez denedim "
            "ancak kaynaklarla destekleyemedim. "
            "Soruyu farklı bir şekilde sormayı ya da bir avukattan destek almayı deneyin."
        )
    else:
        body = (
            "Bu soruya şu an net bir yanıt veremiyorum. "
            "Konuyu daha ayrıntılı anlatan ek bilgi paylaşırsanız yeniden deneyebilirim; "
            "durumunuz karmaşıksa bir avukata danışmanızı öneririm."
        )

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


def _format_citations(state: AgentState) -> str:
    cited_ids = set(_SRC_TAG_RE.findall(state.get("draft_response", "") or ""))
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


def _unverified_claims_reason(verified: list) -> str:
    n_total = len(verified)
    n_unverified = len([c for c in verified if not c.get("verified", False)])
    first_reason = next(
        (str(c.get("verify_reason", "")) for c in verified if not c.get("verified", False)),
        "",
    )
    detail = f"{n_unverified}/{n_total} iddia doğrulanamadı."
    return f"{detail} İlk neden: {first_reason}" if first_reason else detail
