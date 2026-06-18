"""Tahmin ajanı — opsiyonel 8. ajan (dava sonucu tahmini).

Konum: debate/self_rag sonrası, finalize ÖNCESİ (PREDICTIVE_ENABLED=1 ile
graph'a eklenir). Getirilen benzer Yargıtay kararlarına (emsal_refs) dayanarak
vatandaşa "bu davada tahmini sonuç ne" sinyali üretir.

KRİTİK (CLAUDE.md §1-2): Tahmin YALNIZ display'dir — verify/debate hard-gate'i
asla geçersiz kılmaz. Doğrulanmamış iddia üretmez; emsal yoksa veya sinyal
zayıfsa prediction=None / "belirsiz" döner. SIFIR HALÜSİNASYON korunur.
"""

from __future__ import annotations

import structlog

from agents.policy import _is_general_question
from agents.state import AgentState, Citation
from core.observability import observe_node
from predictive import predict_outcome

log = structlog.get_logger()

# Tahmin için kullanılacak en benzer emsal sayısı (üst-K, score'a göre sıralı).
_TOP_K_CASES = 5


def _doc_key(source_id: str) -> str:
    """Chunk id'yi karar id'sine indir: h-123-c4 -> h-123."""
    return source_id.rsplit("-c", 1)[0] if "-c" in source_id else source_id


def _top_unique_case_refs(refs: list[Citation], limit: int = _TOP_K_CASES) -> list[Citation]:
    """Tahmin için aynı kararın birden fazla chunk'ını tek emsal say."""
    seen: set[str] = set()
    out: list[Citation] = []
    for ref in refs:
        key = _doc_key(ref.get("source_id", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(ref)
        if len(out) >= limit:
            break
    return out


@observe_node(name="tahmin")
async def tahmin_node(state: AgentState) -> dict[str, object]:
    """Emsal kararlardan dava sonucu tahmini. Kaynak yoksa prediction=None.

    Sadece state'e `prediction` ekler; cevabı/verdict'i DEĞİŞTİRMEZ.
    """
    refs = state.get("emsal_refs", []) or []
    if not refs:
        # Emsal yok → tahmin yapılamaz (uydurma yok). Display'de gösterilmez.
        return {"prediction": None}

    # Dava-sonucu tahmini YALNIZ somut uyuşmazlık-senaryosunda anlamlı. Bilgi/usul/
    # tanım soruları ("kira yasal sınırı nedir?", "nasıl itiraz ederim?") dava DEĞİL —
    # bunlarda "geçmiş davalar %X aleyhe" göstermek yanıltıcı (jüri-riski). _is_general_question
    # bu soruları yakalar → tahmin gizlenir (prediction=None → frontend kartı render etmez).
    if _is_general_question(state.get("question", "")):
        log.info("tahmin_skip", reason="general_question")
        return {"prediction": None}

    top = _top_unique_case_refs(refs)
    texts = [r["snippet"] for r in top]
    ids = [r["source_id"] for r in top]
    prediction = await predict_outcome(state.get("question", ""), texts, ids)
    log.info(
        "tahmin_done",
        verdict=prediction["verdict_class"],
        confidence=prediction["confidence"],
        n_cases=len(top),
    )
    return {"prediction": prediction}


__all__ = ("tahmin_node",)
