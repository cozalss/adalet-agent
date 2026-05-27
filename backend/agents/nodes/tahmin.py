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

from agents.state import AgentState
from core.observability import observe_node
from predictive import predict_outcome

log = structlog.get_logger()

# Tahmin için kullanılacak en benzer emsal sayısı (üst-K, score'a göre sıralı).
_TOP_K_CASES = 5


@observe_node(name="tahmin")
async def tahmin_node(state: AgentState) -> dict[str, object]:
    """Emsal kararlardan dava sonucu tahmini. Kaynak yoksa prediction=None.

    Sadece state'e `prediction` ekler; cevabı/verdict'i DEĞİŞTİRMEZ.
    """
    refs = state.get("emsal_refs", []) or []
    if not refs:
        # Emsal yok → tahmin yapılamaz (uydurma yok). Display'de gösterilmez.
        return {"prediction": None}

    top = refs[:_TOP_K_CASES]
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
