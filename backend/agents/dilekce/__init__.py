"""Dilekçe Ajanı paketi — vatandaşın sorusundan PDF dilekçe üretir.

Public API:
    - DilekceContext: render girdileri (immutable dataclass)
    - DilekceResult: render çıktıları (md + pdf bytes + template id)
    - render_dilekce(): tek-çağrı orchestrator (registry → context → render)
    - select_template_id(): domain + facts → template id

Mimari (kararlar):
    - jinja2 templates: agents/dilekce/templates/<domain>/<type>.j2
    - reportlab Türkçe PDF (DejaVuSans TTF embed)
    - LLM kullanılmaz — yalnız VERIFIED claim ve KAYNAKLI mevzuat string
      interpolation. Sıfır halüsinasyon ([[adalet_nli_finding]] uyumlu).
"""

from agents.dilekce.models import DilekceContext, DilekceResult
from agents.dilekce.renderer import render_dilekce
from agents.dilekce.template_registry import (
    available_templates,
    select_template_id,
)

__all__ = (
    "DilekceContext",
    "DilekceResult",
    "available_templates",
    "render_dilekce",
    "select_template_id",
)
