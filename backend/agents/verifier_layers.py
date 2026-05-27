"""Verifier katmanları — Sprint-4 W4.1 split.

`agents/nodes/verify.py` 433 satıra ulaşmıştı; CLAUDE.md "<800 satır" sınırının
altında olsa da okunabilirlik için 4 katman ve helper'ları bu modüle taşındı.

Katmanlar:
  - Layer 1: Rules-based syntactic check (madde/karar format regex)
  - Layer 2: Fuzzy snippet match (rapidfuzz)
  - Layer 2.5: LettuceDetect token-level grounding
  - Layer 3: NLI contradiction filter (mDeBERTa XNLI)
  - Layer 4 (W4.2): RARR-lite — evidence augmentation (verifier/rarr.py)

Bu modül salt fonksiyonlar — state mutate etmez, callable factory'leri
`agents/nodes/verify.py` üzerinden monkeypatch edilebilir (testler bunu kullanır).
"""

from __future__ import annotations

import re
from collections.abc import Callable

import structlog
from rapidfuzz import fuzz

from agents.config import (
    NLI_CONTRADICTION_THRESHOLD,
    VERIFY_BATCH,
    is_verify_strict,
)
from agents.state import Citation, Claim
from retrieval.citation import parse_citation

log = structlog.get_logger()


class VerifierUnavailableError(RuntimeError):
    """Strict modda zorunlu bir doğrulayıcı (NLI/LettuceDetect) çöktü.

    `verify_node` bunu yakalar ve cevabı **fail-closed** reddeder: doğrulayıcı
    çalışmadıysa iddia "doğrulanmış" sayılamaz (SIFIR HALÜSİNASYON, CLAUDE.md §1).
    Non-strict (dev/test) modda fırlatılmaz — graceful degrade korunur.
    """

# Madde referansı formatı genel desen — sentaktik geçerlilik
_MADDE_FORMAT_RE = re.compile(
    r"\b(?:m\.?|madde)\s*\d{1,4}\b", re.IGNORECASE,
)
# Esas/Karar formatı (Yargıtay/Danıştay)
_ESAS_KARAR_RE = re.compile(r"\b\d{4}\s*/\s*\d{1,6}\b")

# Claim metninde geçen madde numaralarını yakala (kanıt-daraltma için).
_CLAIM_MADDE_NO_RE = re.compile(r"\b(?:m\.?|madde)\s*(\d{1,4})\b", re.IGNORECASE)
# Citation.source_id ("m-IK-31") veya title ("IK Madde 31") sondaki madde no.
_REF_SID_MADDE_RE = re.compile(r"-(\d{1,4})$")
_REF_TITLE_MADDE_RE = re.compile(r"\bmadde\s*(\d{1,4})\b", re.IGNORECASE)


def _stated_madde_numbers(text: str) -> set[int]:
    """Claim metninde AÇIKÇA belirtilen madde numaraları."""
    return {int(n) for n in _CLAIM_MADDE_NO_RE.findall(text)}


def _ref_madde_no(ref: Citation) -> int | None:
    """Citation'ın madde numarası — source_id ('m-IK-31') ya da title ('IK Madde 31')."""
    sid = ref.get("source_id", "") or ""
    m = _REF_SID_MADDE_RE.search(sid)
    if m:
        return int(m.group(1))
    m = _REF_TITLE_MADDE_RE.search(ref.get("title", "") or "")
    return int(m.group(1)) if m else None


def _scope_refs_to_claim_madde(
    claim_text: str, refs: list[Citation],
) -> tuple[list[Citation], bool]:
    """Claim belirli madde no söylüyorsa kanıtı O maddenin kaynağına daralt.

    SIFIR HALÜSİNASYON tightening (Step-4): bir claim "Madde 31 ..." diyorsa,
    doğrulama o iddiayı m.31 kaynağıyla karşılaştırmalı — başka maddenin
    snippet'iyle gevşek token örtüşmesi üzerinden geçmemeli. LLM bir maddenin
    içeriğini başka maddeye atfederse (garbled m.31), kanıt doğru kaynağa
    daraltılınca fuzzy/NLI skoru düşer → unsupported.

    Returns:
        (scoped_refs, stated_but_missing)
        - claim madde no söylemiyorsa → (refs, False) — kısıt yok.
        - söylüyor ve eşleşen ref varsa → (eşleşen refs, False).
        - söylüyor ama HİÇBİR ref o numaraya sahip değilse → (refs, True):
          claim, retrieve edilmemiş bir maddeye atıfta bulunuyor (grounded olamaz).
    """
    stated = _stated_madde_numbers(claim_text)
    if not stated:
        return refs, False
    matching = [r for r in refs if _ref_madde_no(r) in stated]
    if matching:
        return matching, False
    return refs, True


# --------------------------------------------------------------------------
#  Lazy factory hooks — test'ler monkeypatch eder
# --------------------------------------------------------------------------

def _default_nli_factory() -> object:
    """Modül-seviye lazy NLI loader."""
    from verifier.nli import get_verifier
    return get_verifier()


def _default_lettuce_factory() -> object:
    """Modül-seviye lazy LettuceDetect loader."""
    from verifier.lettuce import get_detector
    return get_detector()


# Tek bir referans noktasına bağla; testler monkeypatch ile değiştirir.
get_verifier: Callable[[], object] = _default_nli_factory
get_lettuce: Callable[[], object] = _default_lettuce_factory


# --------------------------------------------------------------------------
#  Layer 1: Rules-based syntactic check
# --------------------------------------------------------------------------

def layer1_rules(claim: Claim) -> tuple[bool, str]:
    """Madde/karar referansı sentaktik geçerli mi?

    Türkçe agglutinative bir dil — "madde", "maddede", "maddesine" hepsi aynı
    kök. Bu nedenle `\\bmadde` (sadece prefix) regex'i kullanılır. Eğer claim
    metninde "madde*" geçiyorsa ama numara yoksa şüpheli (yer-tutucu olabilir).
    """
    text = claim.get("text", "")
    has_madde_root = bool(re.search(r"\bmadde", text, re.IGNORECASE))
    has_madde_format = bool(_MADDE_FORMAT_RE.search(text))
    has_esas_karar = bool(_ESAS_KARAR_RE.search(text))

    if has_madde_root and not (has_madde_format or has_esas_karar):
        return False, "'madde' geçiyor ama numara format bulunamadı"

    parsed = parse_citation(text)
    if parsed:
        _kanun, no = parsed
        if no < 1 or no > 99999:
            return False, f"Madde no geçersiz: {no}"
    return True, "ok"


# --------------------------------------------------------------------------
#  Layer 2: Fuzzy match (snippet)
# --------------------------------------------------------------------------

def layer2_fuzzy(
    claim: Claim, refs: list[Citation],
) -> tuple[float, str, int]:
    """Claim metnini state'teki snippet'lerle fuzzy karşılaştır.

    cite_ids varsa o snippet'lere öncelik ver; yoksa tüm refs'i tara.
    Skoru max(partial_ratio, token_set_ratio) ile normalize et.
    """
    claim_text = claim.get("text", "").strip()
    if not claim_text:
        return 0.0, "boş claim", -1

    # Step-4 tightening: claim belirli bir madde no söylüyorsa kanıtı O maddeye
    # daralt. Söylenen madde corpus'ta hiç yoksa grounded olamaz → 0.0 (uydurma
    # atıf). Bu, garbled madde-atfının yanlış snippet'le geçmesini engeller.
    scoped_refs, stated_but_missing = _scope_refs_to_claim_madde(claim_text, refs)
    if stated_but_missing:
        stated = sorted(_stated_madde_numbers(claim_text))
        return 0.0, f"atıf yapılan madde {stated} kaynakta yok", -1

    cite_ids = claim.get("cite_ids", []) or []
    candidates: list[tuple[int, Citation]] = []
    # Önce stated-madde scope; o yoksa cite_ids; o da yoksa tüm refs.
    scoped_ids = {r["source_id"] for r in scoped_refs}
    if len(scoped_refs) < len(refs):
        candidates = [(i, r) for i, r in enumerate(refs) if r["source_id"] in scoped_ids]
    elif cite_ids:
        candidates = [(i, r) for i, r in enumerate(refs) if r["source_id"] in cite_ids]
    if not candidates:
        candidates = list(enumerate(refs))

    best_score = 0.0
    best_idx = -1
    best_title = ""
    for idx, ref in candidates:
        snippet = ref["snippet"]
        if not snippet:
            continue
        partial = fuzz.partial_ratio(claim_text, snippet) / 100.0
        token_set = fuzz.token_set_ratio(claim_text, snippet) / 100.0
        score = max(partial, token_set)
        if score > best_score:
            best_score = score
            best_idx = idx
            best_title = ref["title"]

    return best_score, best_title or "no match", best_idx


# --------------------------------------------------------------------------
#  Layer 3: NLI contradiction filter
# --------------------------------------------------------------------------

def layer3_nli_batch(
    claims: list[Claim], refs: list[Citation],
) -> list[tuple[bool, float, float, str]]:
    """Her claim için en alakalı snippet ile NLI.

    Strateji: claim'in cite_ids'i veya layer2'nin best_idx'i ile snippet seç;
    sonra batch'le NLIVerifier'a gönder.

    NOT: NLI modeli yüklü değilse sessiz fallback —
    contradiction=False, score=0.0 dön. Mock LLM ile bu yol çalışır.

    Sprint-4 W4.1: `get_verifier` callable'ı her çağrıda module-level attribute
    olarak resolve edilir; test'ler `agents.nodes.verify.get_verifier` proxy'sini
    monkeypatch'ladığında otomatik olarak buraya yansır (sync edilmiş).
    """
    if not claims:
        return []

    pairs: list[tuple[str, str]] = []
    pair_indices: list[int] = []
    for i, claim in enumerate(claims):
        snippet = pick_evidence(claim, refs)
        if snippet:
            pairs.append((claim.get("text", ""), snippet))
            pair_indices.append(i)

    # Module-level lookup — test monkeypatch'ları görünür kalır
    import agents.verifier_layers as _self
    try:
        verifier = _self.get_verifier()
        nli_results = verifier.verify_batch(pairs, batch_size=VERIFY_BATCH)  # type: ignore[attr-defined]
    except Exception as exc:
        if is_verify_strict():
            # Fail-closed: NLI yüklü olmalıydı ama çöktü → sessiz pas YOK.
            log.error("nli_unavailable_strict", error=str(exc))
            raise VerifierUnavailableError(f"NLI doğrulayıcı kullanılamıyor: {exc}") from exc
        log.warning("nli_unavailable", error=str(exc))
        return [(False, 0.0, 0.0, "NLI atlandı") for _ in claims]

    output: list[tuple[bool, float, float, str]] = [
        (False, 0.0, 0.0, "snippet yok") for _ in claims
    ]
    for k, claim_idx in enumerate(pair_indices):
        r = nli_results[k]
        contradicted = r.contradiction_score >= NLI_CONTRADICTION_THRESHOLD
        msg = (
            f"label={r.label} ent={r.entailment_score:.2f} "
            f"con={r.contradiction_score:.2f}"
        )
        output[claim_idx] = (
            contradicted, r.entailment_score, r.contradiction_score, msg,
        )

    return output


# --------------------------------------------------------------------------
#  Layer 2.5: LettuceDetect token-level grounding
# --------------------------------------------------------------------------

async def layer25_lettuce(
    claims: list[Claim], refs: list[Citation],
) -> list[tuple[float, bool]]:
    """Her claim için token-level grounding skoru + fallback bayrağı.

    Returns:
        [(score, fallback_used), ...]  — score 0..1, fallback_used True ise
        gerçek model çalışmadı (rapidfuzz token-coverage kullanıldı).
    """
    if not claims:
        return []

    # Module-level lookup — test monkeypatch'ları görünür kalır
    import agents.verifier_layers as _self
    try:
        detector = _self.get_lettuce()
    except Exception as exc:
        if is_verify_strict():
            log.error("lettuce_unavailable_strict", error=str(exc))
            raise VerifierUnavailableError(f"LettuceDetect kullanılamıyor: {exc}") from exc
        log.warning("lettuce_unavailable", error=str(exc))
        return [(0.0, True) for _ in claims]

    out: list[tuple[float, bool]] = []
    for claim in claims:
        evidences = pick_evidence_list(claim, refs)
        try:
            r = await detector.grounding_score(claim.get("text", ""), evidences)  # type: ignore[attr-defined]
            out.append((float(r.grounding_score), bool(r.fallback_used)))
        except Exception as exc:
            if is_verify_strict():
                log.error("lettuce_call_failed_strict", error=str(exc))
                raise VerifierUnavailableError(
                    f"LettuceDetect çağrısı başarısız: {exc}",
                ) from exc
            log.warning("lettuce_call_failed", error=str(exc))
            out.append((0.0, True))
    return out


# --------------------------------------------------------------------------
#  Evidence selection helpers
# --------------------------------------------------------------------------

def pick_evidence(claim: Claim, refs: list[Citation]) -> str:
    """En alakalı snippet'i seç — stated-madde scope > cite_ids > fuzzy-best.

    Step-4: claim madde no söylüyorsa NLI/grounding o maddenin kaynağıyla
    karşılaştırılmalı (yanlış kaynağa karşı entailment kaçağını önler).
    """
    text = claim.get("text", "")
    scoped_refs, stated_but_missing = _scope_refs_to_claim_madde(text, refs)
    if stated_but_missing:
        return ""  # atıf yapılan madde kaynakta yok → kanıt yok
    if len(scoped_refs) < len(refs):
        snippets = [r["snippet"] for r in scoped_refs if r["snippet"]]
        if snippets:
            return "\n\n".join(snippets)[:2000]
    cite_ids = claim.get("cite_ids", []) or []
    if cite_ids:
        snippets = [r["snippet"] for r in refs if r["source_id"] in cite_ids]
        if snippets:
            return "\n\n".join(snippets)[:2000]
    if not refs:
        return ""
    best = max(
        refs,
        key=lambda r: fuzz.partial_ratio(text, r["snippet"] or ""),
    )
    return (best["snippet"] or "")[:2000]


def pick_evidence_list(claim: Claim, refs: list[Citation]) -> list[str]:
    """LettuceDetect için — birden çok evidence snippet'i listesi."""
    text = claim.get("text", "")
    scoped_refs, stated_but_missing = _scope_refs_to_claim_madde(text, refs)
    if stated_but_missing:
        return []
    if len(scoped_refs) < len(refs):
        snippets = [r["snippet"] for r in scoped_refs if r["snippet"]]
        if snippets:
            return snippets
    cite_ids = claim.get("cite_ids", []) or []
    if cite_ids:
        snippets = [
            r["snippet"] for r in refs
            if r["source_id"] in cite_ids and r["snippet"]
        ]
        if snippets:
            return snippets
    if not refs:
        return []
    ranked = sorted(
        refs,
        key=lambda r: fuzz.partial_ratio(text, r["snippet"] or ""),
        reverse=True,
    )
    return [r["snippet"] for r in ranked[:3] if r.get("snippet")]


__all__ = (
    "VerifierUnavailableError",
    "layer1_rules",
    "layer2_fuzzy",
    "layer3_nli_batch",
    "layer25_lettuce",
    "pick_evidence",
    "pick_evidence_list",
)
