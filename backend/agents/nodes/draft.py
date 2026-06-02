"""Draft ajanı — LLM ile cevap taslağı + claim extraction.

İki aşamalı:
  1. LLM cevabı üretir (prompt: draft.tr.txt + retrieval bağlamı)
  2. Cevap içinden cümle bazlı claim'ler çıkarılır (verify için)

Claim extraction basit yapılır: cümle ayır + 'iddia içeren' filtre.
LLM-based extraction sonraki iterasyona bırakılır.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import structlog

from agents.config import (
    DRAFT_MAX_TOKENS,
    LLM_CONTEXT_BUDGET,
    LLM_TEMPERATURE,
)
from agents.llm import ChatMessage, get_llm
from agents.state import AgentState, Citation, Claim
from core.observability import observe_node

log = structlog.get_logger()

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "draft.tr.txt"
# Prompt'u modül yüklenirken bir kez oku — her draft_node çağrısında (her /ask)
# senkron disk I/O yapma (event loop'u bloke eder, gereksiz syscall).
_DRAFT_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")

# Draft system prompt — SIFIR HALÜSİNASYON savunma hattı. System rolü en
# yüksek talimat önceliği; user template kuralları görmezden gelinse bile bu
# kalır. CLAUDE.md §1: kaynağı doğrulanmamış iddia üretilemez.
_DRAFT_SYSTEM = (
    "Sen Türk hukuku konusunda uzman bir asistansın. MUTLAK KURALLAR:\n"
    "1. SADECE sana verilen kaynaklardaki bilgileri kullan. Kaynaklarda "
    "geçmeyen hiçbir kanun maddesi, Yargıtay/Danıştay kararı, tarih veya "
    "sayı UYDURMA.\n"
    "2. Bir madde numarası veya karar referansı, verilen kaynaklarda AÇIKÇA "
    "geçmiyorsa onu YAZMA.\n"
    "3. Emin olmadığında uydurmak yerine 'bu konuda kesin bilgi veremiyorum, "
    "bir avukata danışmanızı öneririm' de.\n"
    "4. Her hukuki iddiayı dayandığın kaynağın [src: ID] etiketiyle işaretle.\n"
    "5. Yanıtının TAMAMI Türkçe olmalı. İngilizce, Çince veya başka hiçbir "
    "dilde tek kelime bile yazma; tüm cevabı baştan sona Türkçe ver.\n"
    "6. İspat yükünü veya üst sınır yönünü ters yazma: kaynak satıcı/işveren/idare "
    "ispat eder diyorsa kullanıcıya ispat yükleme; kaynak 'aşamaz' diyorsa "
    "aşanı kabul etmek zorunda olduğunu söyleme.\n"
    "7. Ayrı 'Kaynaklar' listesi yazma; yalnız gövdeyi yaz ve her iddiaya [src: ID] koy. "
    "Yanıtı yarım cümleyle veya yarım [src: ...] etiketiyle bitirme.\n"
    "8. Kullanıcıya 'siz' diliyle hitap et; argo, devrik veya bozuk Türkçe cümle kurma.\n"
    "9. Ayıplı mal/iade/değişim sorusunda TKHK 8 ve TKHK 11'i esas al; "
    "servis/garanti yönetmeliğini yalnız soru servis veya garanti süreciyle ilgiliyse kullan.\n"
    "10. Kullanıcının söylediği süreyi kanuni süre gibi yorumlama. Kaynakta açık süre yoksa "
    "'bu süre geçtiği için hakkınız yok' veya 'şu gün içinde hakkınız var' deme."
)

# Kaynak ID etiketleri: [src: chunk_abc123]
_SRC_TAG_RE = re.compile(r"\[src:\s*([A-Za-z0-9_\-]+)\s*\]")
# Cümle ayraç — Türkçe nokta/!?
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜ])")

# Sprint-4 W4.6: LLM-based atomic claim extraction (opt-in).
# Heuristic regex bazı edge case'lerde claim'i bölemez (uzun cümle, virgül
# bağlı yan yargılar). LLM atomize bunları parçalar → verify daha hassas.
# Default OFF — ek LLM çağrı maliyeti; ENV=1 ile aktif edilir.
LLM_CLAIM_EXTRACTION_ENABLED = (
    os.getenv("LLM_CLAIM_EXTRACTION", "0").lower() in {"1", "true", "yes"}
)


@observe_node(as_type="generation", name="draft")
async def draft_node(state: AgentState) -> dict[str, object]:
    question = state["question"]
    refs: list[Citation] = (
        state.get("mevzuat_refs", []) + state.get("emsal_refs", [])
    )

    if not refs:
        return {
            "draft_response": "",
            "claims": [],
            "errors": ["draft: kaynak bulunamadı"],
        }

    kaynaklar = _format_refs_for_prompt(refs, question)
    olgular = _format_facts_for_prompt(state.get("case_facts") or {})
    uygunluk = _format_eligibility_for_prompt(state.get("eligibility") or [])
    gecmis = _format_history_for_prompt(state.get("chat_history") or [])
    user_prompt = (
        _DRAFT_TEMPLATE
        .replace("{kaynaklar_blogu}", kaynaklar)
        .replace("{olgular_blogu}", olgular)
        .replace("{uygunluk_blogu}", uygunluk)
        .replace("{gecmis_blogu}", gecmis)
        .replace("{soru}", question)
    )

    llm = get_llm()
    try:
        response = await llm.chat(
            messages=[
                ChatMessage(role="system", content=_DRAFT_SYSTEM),
                ChatMessage(role="user", content=user_prompt),
            ],
            temperature=LLM_TEMPERATURE,
            max_tokens=DRAFT_MAX_TOKENS,  # zengin yapısal format için (320→768)
            json_mode=False,
        )
    except Exception as exc:
        # LLM çağrısı çökerse (örn. context taşması, GPU OOM) tüm graph'ı
        # düşürme — boş draft döndür, finalize bunu fail-closed reddeder.
        log.error("draft_llm_failed", error=str(exc) or type(exc).__name__)
        return {
            "draft_response": "",
            "claims": [],
            "errors": [f"draft: LLM hatası ({type(exc).__name__})"],
        }

    draft_text = _clean_draft_response(response.content)
    draft_text = _backfill_missing_source_tags(draft_text, refs, question)
    draft_text = _remove_unsafe_duration_inferences(
        draft_text,
        state.get("case_facts") or {},
        state.get("eligibility") or [],
    )
    claims: list[Claim] = []
    if LLM_CLAIM_EXTRACTION_ENABLED:
        try:
            claims = await _extract_claims_llm(draft_text, refs, llm)
            log.info("draft_claims_llm", n_claims=len(claims))
        except Exception as exc:
            log.warning("draft_claims_llm_failed_fallback_regex", error=str(exc))
            claims = []
    if not claims:
        claims = _extract_claims(draft_text, refs)

    log.info("draft_done", tokens_out=response.tokens_out, n_claims=len(claims))
    return {"draft_response": draft_text, "claims": claims}


_CLAIM_LLM_SYSTEM = (
    "Sen Türk hukuku metinlerinden ATOMİK iddialar çıkaran bir asistansın. "
    "Her iddia tek bir önerme olmalı (bileşik cümle bölünmelidir). "
    "Disclaimer, soru, boş retorik atılmalıdır."
)
_CLAIM_LLM_USER_TMPL = (
    "Aşağıdaki cevaptan atomik iddialar çıkar. Her iddia için varsa "
    "kaynak ID'lerini ([src: X] etiketlerinden) listele.\n\n"
    "Cevap:\n{draft}\n\n"
    "Çıktı SADECE JSON: "
    '{{"claims": [{{"text": "...", "cite_ids": ["..."]}}]}}'
)


async def _extract_claims_llm(
    text: str, refs: list[Citation], llm: object,
) -> list[Claim]:
    """LLM ile atomik claim extraction. Başarısız olursa boş döner."""
    known_ids = {r["source_id"] for r in refs}
    user = _CLAIM_LLM_USER_TMPL.format(draft=text[:3000])
    resp = await llm.chat(  # type: ignore[attr-defined]
        messages=[
            ChatMessage(role="system", content=_CLAIM_LLM_SYSTEM),
            ChatMessage(role="user", content=user),
        ],
        temperature=0.0,
        max_tokens=600,
        json_mode=True,
    )
    data = json.loads(resp.content)
    raw = data.get("claims", []) if isinstance(data, dict) else []
    claims: list[Claim] = []
    for item in raw[:15]:
        if not isinstance(item, dict):
            continue
        ctext = str(item.get("text", "")).strip()
        if len(ctext) < 30 or ctext.endswith("?"):
            continue
        cite_ids = [c for c in (item.get("cite_ids") or []) if c in known_ids]
        claims.append(Claim(
            text=ctext, cite_ids=cite_ids, verified=False,
            verify_score=0.0, verify_reason="",
        ))
    return claims


# Triaj olgu anahtarları → kullanıcı-dostu Türkçe etiket (prompt okunurluğu).
_FACT_LABELS = {
    "sure": "Kullanıcının belirttiği süre (kanuni süre değildir)",
    "isci_sayisi": "İşçi sayısı",
    "tutar": "Tutar",
    "olay": "Olay",
    "taraf": "Taraf",
    "tarih": "Tarih",
    "sozlesme_durumu": "Sözleşme durumu",
    "teslim": "Teslim",
    "gerekce": "Gerekçe",
    "fesih_bildirimi": "Fesih bildirimi",
    "odenmeyen_haklar": "Ödenmeyen haklar",
}


def _format_facts_for_prompt(facts: dict[str, object]) -> str:
    """Triaj'ın çıkardığı olguları draft prompt'una belirgin blok olarak göm.

    Olgu yoksa boş string → LLM kendi olgu çıkarımını yapar (degrade yok).
    Varsa eşik-kontrolü (ADIM 2) için somut zemin verir: "Süre: 3 ay" gibi.
    Blok prompt'ta öne (KULLANICININ DURUMU) konur ki model gözünden kaçmasın.
    """
    if not facts:
        return ""
    parts = [
        f"{_FACT_LABELS.get(k, k)}: {str(v).strip()}"
        for k, v in facts.items()
        if str(v).strip()
    ]
    if not parts:
        return ""
    return (
        "\n\nKULLANICININ DURUMU (sorudan çıkarılan somut olgular — "
        "eşik karşılaştırmasında BUNLARI kullan):\n- " + "\n- ".join(parts)
    )


# saglaniyor → kullanıcıya gösterilecek karar etiketi
_VERDICT_LABEL = {
    "evet": "HAK VAR",
    "hayir": "HAK YOK",
    "belirsiz": "BELİRSİZ",
}


def _format_eligibility_for_prompt(assessments: list[dict[str, Any]]) -> str:
    """Uygunluk node'unun önceden hesapladığı eşik kararlarını draft'a göm.

    Bu blok varsa draft eşik aritmetiğini TEKRAR yapmaz — kararları prose'a
    çevirir. HAK YOK olanları eksik şartıyla, HAK VAR olanları dayanağıyla yazar.
    Boşsa "" → draft kendi DÜŞÜNME ADIMLARI ile idare eder (degrade yok).
    """
    if not assessments:
        return ""
    lines = []
    for a in assessments:
        label = _VERDICT_LABEL.get(a.get("saglaniyor", ""), "BELİRSİZ")
        hak = a.get("hak", "") or "?"
        madde = a.get("madde", "")
        kosul = a.get("kosul", "")
        gerekce = a.get("gerekce", "")
        kosul_str = f" | Şart: {kosul}" if kosul and kosul != "-" else ""
        lines.append(f"- [{label}] {hak} ({madde}){kosul_str} — {gerekce}")
    return (
        "\n\nUYGUNLUK DEĞERLENDİRMESİ (önceden hesaplandı — yanıtını BUNA dayandır; "
        "HAK YOK olanları eksik şartıyla açıkça belirt, HAK VAR olanları öne çıkar):\n"
        + "\n".join(lines)
    )


# Türkçe hukuk metni Qwen tokenizer'da ~2.3 karakter/token (eski "4 char/token"
# varsayımı YANLIŞTI → uzun TBK maddeleriyle (kira/tapu) draft prompt'u n_ctx=8192'yi
# aşıp `llama_decode -1` ile ÇÖKÜYORDU). Gerçekçi oran + ref sayısı + snippet cap ile
# prompt güvenli sınırda tutulur; ayrıca LLM client max_tokens clamp guard'ı var.
_CHARS_PER_TOKEN_TR = 2.3
_DRAFT_SNIPPET_CHARS = 260
_MAX_DRAFT_REFS = 4


_MAX_HISTORY_TURNS = 3      # son 3 tur yeterli; daha fazlası token boşa gider
_MAX_HISTORY_CHAR = 300    # tur başına karakter sınırı (özet için yeterli)


def _format_history_for_prompt(history: list[Any]) -> str:
    """Son N konuşma turunu draft prompt'una bağlam olarak göm.

    Amaç: "peki ya önceki durumda?" gibi devam sorularında LLM önceki
    konuşmayı bilsin, tekrar anlatma gerekliliği doğmasın.
    Yoksa boş string → template'teki {gecmis_blogu} silinir (degrade yok).
    """
    if not history:
        return ""
    recent = history[-_MAX_HISTORY_TURNS:]
    lines = []
    for turn in recent:
        role = "Kullanıcı" if turn.get("role") == "user" else "Asistan"
        content = str(turn.get("content", ""))[:_MAX_HISTORY_CHAR]
        lines.append(f"{role}: {content}")
    return (
        "\n\nÖNCEKİ KONUŞMA (bağlam için — bu bilgileri tekrar etme, "
        "konuşmaya devam ediyormuş gibi yanıt ver):\n"
        + "\n".join(lines)
    )


_PROMPT_REF_HINTS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("kira art", "yüzde", "tüfe", "tüketici fiyat"), ("m-TBK-344",)),
    (("depozito", "güvence bedeli", "kira teminatı"), ("m-TBK-342", "m-TBK-372")),
    (("seçimlik", "iade", "değişim", "bedel indir"), ("m-TKHK-11", "m-TKHK-8")),
    (("ayıpl", "arız", "bozuk", "teslim", "10 gün"), ("m-TKHK-11", "m-TKHK-8", "m-TKHK-10")),
    (("kıdem",), ("m-EIK-14",)),
    (("ihbar",), ("m-IK-17",)),
    (("işe iade",), ("m-IK-18",)),
)


_MODEL_SOURCE_BLOCK_RE = re.compile(
    r"\n\s*(?:---\s*)?(?:\*\*)?Kaynaklar(?:\*\*)?\s*:.*$",
    re.IGNORECASE | re.DOTALL,
)
_COMPLETE_SRC_AT_END_RE = re.compile(r"\[src:\s*[A-Za-z0-9_\-]+\s*\]\s*$")
_INCOMPLETE_SRC_AT_END_RE = re.compile(r"\s*\[src:\s*[^\]]*$")
_SENTENCE_END_RE = re.compile(r"[.!?](?:\s|$)")
_LEGAL_CLAIM_MARKERS = (
    "hak", "iade", "yüküml", "gerek", "edebilir", "etmeli", "zorunda",
    "tazminat", "fesih", "başvur", "talep", "ispat",
)
_UNSAFE_DURATION_MARKERS = (
    "süre geçti",
    "süreniz kalmam",
    "şartı karşılamadınız",
    "hakkınız olmayabilir",
    "geçtiği için",
    "kanuni süre değildir",
    "süre geçerli değildir",
    "süresi geçerli değildir",
)


def _clean_draft_response(raw: str) -> str:
    """Model çıktısını final aşamasına girmeden önce güvenli, tam gövdeye indir.

    Llama.cpp token sınırında kesilirse kaynak etiketi veya son cümle yarım kalabilir.
    Ayrıca model bazen prompt'a rağmen kendi "Kaynaklar" bloğunu üretir; kaynak listesi
    finalize_node tarafından tekilleştirilerek ekleneceği için burada gövde dışına atılır.
    """
    text = _MODEL_SOURCE_BLOCK_RE.sub("", raw.strip())
    text = _INCOMPLETE_SRC_AT_END_RE.sub("", text).rstrip()
    if not text:
        return ""
    if text[-1] in ".!?" or _COMPLETE_SRC_AT_END_RE.search(text):
        return text
    matches = list(_SENTENCE_END_RE.finditer(text))
    if not matches:
        return text
    return text[: matches[-1].end()].strip()


def _backfill_missing_source_tags(text: str, refs: list[Citation], question: str) -> str:
    """Kaynak etiketi eksik hukuki cümleleri mevcut en alakalı kaynakla iliştir.

    Bu yeni iddia üretmez; yalnızca modelin atladığı `[src: ...]` bağını ekler.
    Son söz yine verifier'dadır: yanlış iliştirilirse claim desteklenmez ve finalize
    güvenli tarafta cümleyi düşürür.
    """
    if not text.strip() or not refs:
        return text
    ranked = _prioritize_refs_for_prompt(refs, question)
    if not ranked:
        return text
    default_id = ranked[0]["source_id"]
    out = text
    for sent in _split_claim_candidates(text):
        if _SRC_TAG_RE.search(sent):
            continue
        clean = sent.strip()
        low = clean.lower()
        if not clean or "**ne yapmalı" in low:
            continue
        if not any(marker in low for marker in _LEGAL_CLAIM_MARKERS):
            continue
        replacement = f"{clean} [src: {default_id}]"
        out = out.replace(sent, replacement, 1)
    return out


def _remove_unsafe_duration_inferences(
    text: str,
    facts: dict[str, object],
    eligibility: list[dict[str, Any]],
) -> str:
    """Kullanıcının verdiği süreyi hak düşürücü süreye çeviren cümleleri sil.

    Eligibility node açık ve yapılandırılmış karar verdiyse bu filtreden geçmeyiz.
    Eligibility yokken küçük model, "10 gün önce aldım" bilgisini kaynakta olmayan
    kanuni deadline gibi yorumlayabiliyor; bu cümleler güvenli tarafta atılır.
    """
    if not facts.get("sure") or eligibility:
        return text
    out = text
    for sent in _split_claim_candidates(text):
        low = sent.lower()
        if any(marker in low for marker in _UNSAFE_DURATION_MARKERS):
            out = out.replace(sent, "", 1)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def _format_refs_for_prompt(refs: list[Citation], question: str = "") -> str:
    """LLM'e verilecek kaynak bloğu — ref sayısı + token bütçesi sınırında kal."""
    lines = []
    budget = int(LLM_CONTEXT_BUDGET * _CHARS_PER_TOKEN_TR)
    used = 0
    for r in _prioritize_refs_for_prompt(refs, question)[:_MAX_DRAFT_REFS]:
        chunk = (
            f"[{r['source_id']}] {r['title']}\n"
            f"  Kaynak: {r['url']}\n"
            f"  Metin: {r['snippet'][:_DRAFT_SNIPPET_CHARS]}\n"
        )
        if used + len(chunk) > budget:
            break
        lines.append(chunk)
        used += len(chunk)
    return "\n".join(lines)


def _prioritize_refs_for_prompt(refs: list[Citation], question: str) -> list[Citation]:
    """Prompt bütçesi dar; soru için kritik maddeler ilk slotlara girmeli."""
    q_low = question.lower()

    def score(ref: Citation) -> float:
        sid = ref["source_id"]
        title = ref["title"].lower()
        snippet = (ref["snippet"] or "").lower()
        val = float(ref.get("score", 0.0) or 0.0)
        for markers, source_ids in _PROMPT_REF_HINTS:
            if any(marker in q_low for marker in markers) and sid in source_ids:
                val += 100.0
        if "seçimlik" in q_low and sid == "m-TKHK-11":
            val += 80.0
        if ("arız" in q_low or "ayıpl" in q_low) and sid == "m-TKHK-10":
            val += 60.0
        if ("arız" in q_low or "ayıpl" in q_low or "iade" in q_low or "değişim" in q_low) and sid == "m-TKHK-11":
            val += 120.0
        if ("arız" in q_low or "ayıpl" in q_low) and sid == "m-TKHK-8":
            val += 90.0
        if (
            "YON_SSH" in sid
            and any(marker in q_low for marker in ("iade", "değişim", "ayıpl", "arız"))
            and not any(marker in q_low for marker in ("servis", "garanti", "onarım"))
        ):
            val -= 80.0
        q_terms = {t for t in re.findall(r"[a-zçğıöşü0-9]+", q_low) if len(t) >= 4}
        if q_terms:
            haystack = f"{title} {snippet}"
            val += sum(1.0 for term in q_terms if term in haystack)
        return val

    deduped: list[Citation] = []
    seen: set[str] = set()
    for ref in refs:
        sid = ref["source_id"]
        if sid in seen:
            continue
        seen.add(sid)
        deduped.append(ref)

    ranked_laws = sorted(
        [r for r in deduped if r.get("doc_type") == "law"],
        key=score,
        reverse=True,
    )
    ranked_cases = sorted(
        [r for r in deduped if r.get("doc_type") == "case"],
        key=score,
        reverse=True,
    )
    if not ranked_laws:
        return ranked_cases
    if not ranked_cases:
        return ranked_laws
    return [*ranked_laws[: max(_MAX_DRAFT_REFS - 1, 1)], ranked_cases[0], *ranked_laws[_MAX_DRAFT_REFS - 1:]]


def _extract_claims(text: str, refs: list[Citation]) -> list[Claim]:
    """Cümle bazlı claim extraction.

    İki yol:
      1) `[src: ...]` etiketi olan cümleler → cite_ids ile claim
      2) Etiketsiz declarative cümleler → cite_ids=[] ile claim (verify
         node tüm refs üzerinde fuzzy match yapar — cite_ids boşsa fallback
         davranışı verify.py:_layer2_fuzzy'de zaten var)

    Neden gevşek? Qwen 14B Q4 prompt'taki `[src: ...]` etiketini tutarsız
    koyuyor (E2E ölçümlerde 8 soru × ~70% etiketsiz). Etiket yok = claim
    yok = hard reject template — bu hatalı. Gerçek halüsinasyon koruması
    verify_node'da (NLI veto + fuzzy threshold), claim listesinde değil.

    Filtreler:
      - len < 30 → çok kısa, claim değil
      - soru cümlesi (? ile biten) → claim değil
      - disclaimer / boilerplate ("avukata danışın", "bilgilendirme amaçlı")
        → claim değil
      - max 15 claim → verify maliyetini sınırla
    """
    known_ids = {r["source_id"] for r in refs}
    claims: list[Claim] = []
    boilerplate_patterns = (
        "avukata danış",
        "bilgilendirme amaç",
        "hukuki tavsiye değil",
        "kesin işlem için",
    )

    sentences = _split_claim_candidates(text)
    for sent in sentences:
        cite_ids = [s for s in _SRC_TAG_RE.findall(sent) if s in known_ids]
        clean = _SRC_TAG_RE.sub("", sent).strip()
        if len(clean) < 30:
            continue
        if clean.endswith("?"):
            continue
        low = clean.lower()
        if any(p in low for p in boilerplate_patterns):
            continue
        claims.append(
            Claim(
                text=clean,
                cite_ids=cite_ids,
                verified=False,
                verify_score=0.0,
                verify_reason="",
            )
        )
        if len(claims) >= 15:
            break

    return claims


def _split_claim_candidates(text: str) -> list[str]:
    """Draft gövdesini claim adaylarına böl.

    LLM yapısal cevapta başlıklar ve boş satırlar kullanıyor. Sadece nokta sonrası
    büyük harf bölücüsü, başlıklar arasında uzun birleşik claim üretip verifier'ı
    yanıltıyordu; bu yüzden önce blokları, sonra cümleleri ayırıyoruz.
    """
    candidates: list[str] = []
    blocks = re.split(r"\n{2,}|\n(?=\*\*)", text)
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        for sent in _SENT_SPLIT_RE.split(block):
            sent = sent.strip()
            if sent:
                candidates.append(sent)
    return candidates
