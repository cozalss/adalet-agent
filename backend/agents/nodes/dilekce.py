"""Dilekçe ajanı (6. ajan) — verified içerikten PDF dilekçe üretir.

Konum: debate/tahmin sonrası, finalize ÖNCESİ. Conditional edge ile yalnız
`want_dilekce=True` + `verdict=pass` + verified_claims dolu olduğunda çalışır.

Sıfır halüsinasyon (CLAUDE.md §1):
    - Yalnız VERIFIED claim metinleri özet'e girer
    - Yalnız mevzuat_refs Citation'ları "Hukuki Dayanak" bölümüne yazılır
    - LLM çağrısı YOK — jinja2 deterministic template render
    - PDF kaynaksız madde no üretemez

KVKK:
    - PDF in-memory bytes; state'e yazılır, disk persistence yok
    - user_meta'da eksik alanlar (TC, telefon) {{ placeholder }} olarak kalır
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import structlog

from agents.dilekce import render_dilekce, select_template_id
from agents.state import AgentState, Citation
from core.observability import observe_node

log = structlog.get_logger()

# Özet metni için max claim uzunluğu (PDF okunabilirlik)
_MAX_OZET_CLAIMS = 6
_MAX_OZET_CHARS = 1200
_MAX_HUKUKI_DAYANAK = 5
_MAX_EMSAL = 3


def _build_olgular(state: AgentState) -> list[str]:
    """case_facts → insan-okunabilir 'Süre: 3 ay' tarzı string listesi.

    KVKK: olgu değerleri user_meta TC/telefon değil — case_facts triaj
    çıktısı (süre, tutar, olay, taraf, tarih).
    """
    labels = {
        "sure": "Süre",
        "isci_sayisi": "İşçi sayısı",
        "tutar": "Tutar",
        "olay": "Olay",
        "taraf": "Taraf",
        "tarih": "Tarih",
    }
    facts = state.get("case_facts") or {}
    out: list[str] = []
    for key, label in labels.items():
        val = facts.get(key)
        if val and str(val).strip():
            out.append(f"{label}: {str(val).strip()[:120]}")
    return out


def _build_ozet(state: AgentState) -> str:
    """VERIFIED claim cümlelerinden kullanıcı durumu özeti — kaynaksız ifade yok.

    Yalnız verified=True claim'leri al; src tag'lerini düşür (PDF okunabilirlik).
    """
    verified = state.get("verified_claims") or []
    bullets: list[str] = []
    for claim in verified:
        if not claim.get("verified"):
            continue
        text = str(claim.get("text", "")).strip()
        if len(text) < 20:
            continue
        bullets.append(f"- {text}")
        if len(bullets) >= _MAX_OZET_CLAIMS:
            break
    body = "\n".join(bullets)
    if len(body) > _MAX_OZET_CHARS:
        body = body[:_MAX_OZET_CHARS].rsplit("\n", 1)[0] + "\n- ..."
    if not body:
        body = (
            "_Bu durumda doğrulanmış somut iddia tespit edilemedi; ekli "
            "kaynaklara dayanılarak başvuru yapılması önerilir._"
        )
    return body


def _filter_citations(refs: list[Citation], limit: int) -> list[Citation]:
    """Kaynaklı (title + url dolu) Citation'ları üst-N al."""
    out: list[Citation] = []
    for r in refs:
        if not r.get("title") or not r.get("url"):
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


def _should_run(state: AgentState) -> bool:
    """Tüm no-op guard'ları tek yerde toparla. Aşağıdakilerden biri True ise atla."""
    if not state.get("want_dilekce"):
        return False
    if state.get("debate_verdict") != "pass":
        log.info("dilekce_skipped_not_pass", verdict=state.get("debate_verdict"))
        return False
    if state.get("domain", "unknown") == "unknown":
        return False
    if not any(c.get("verified") for c in (state.get("verified_claims") or [])):
        log.info("dilekce_skipped_no_verified_claims")
        return False
    if not (state.get("mevzuat_refs") or []):
        log.info("dilekce_skipped_no_dayanak")
        return False
    return True


def _build_render_args(state: AgentState, template_id: str) -> dict[str, Any]:
    """state → render_dilekce kwargs (saf, test edilebilir)."""
    return {
        "domain": state.get("domain", "unknown"),
        "template_id": template_id,
        "soru": state.get("question", ""),
        "olgular": _build_olgular(state),
        "ozet_metin": _build_ozet(state),
        "hukuki_dayanak": _filter_citations(
            state.get("mevzuat_refs") or [], _MAX_HUKUKI_DAYANAK,
        ),
        "emsal_destek": _filter_citations(
            state.get("emsal_refs") or [], _MAX_EMSAL,
        ),
        "user_meta": {k: str(v) for k, v in (state.get("user_meta") or {}).items()},
        "tarih": date.today().isoformat(),
    }


@observe_node(name="dilekce")
async def dilekce_node(state: AgentState) -> dict[str, Any]:
    """Dilekçe ajanı — VERIFIED cevaba dayalı PDF üret. Guards+render orkestrasyon."""
    if not _should_run(state):
        return {}
    case_facts: dict[str, str] = {
        k: str(v) for k, v in (state.get("case_facts") or {}).items() if v
    }
    template_id = select_template_id(
        state.get("domain", "unknown"), state.get("question", ""), case_facts,
    )
    if template_id is None:
        log.warning("dilekce_no_template", domain=state.get("domain"))
        return {}
    # PDF üretimi 1-3 sn CPU-bound — to_thread ile event loop'u bloklama.
    try:
        result = await asyncio.to_thread(
            render_dilekce, **_build_render_args(state, template_id),
        )
    except Exception as exc:
        log.error(
            "dilekce_render_failed",
            template_id=template_id, error=str(exc) or type(exc).__name__,
        )
        return {"errors": [f"dilekce: render hatası ({type(exc).__name__})"]}
    log.info(
        "dilekce_done", template_id=result.template_id,
        n_dayanak=result.n_dayanak, n_emsal=result.n_emsal,
        pdf_bytes=len(result.pdf_bytes),
    )
    return {
        "dilekce_md": result.markdown,
        "dilekce_pdf_bytes": result.pdf_bytes,
        "dilekce_template_id": result.template_id,
        "dilekce_filename": result.filename,
    }


__all__ = ("dilekce_node",)
