"""Doğrulama katmanı — sıfır halüsinasyon garantisi.

İki seviye:
  - citation.py (retrieval/citation.py): madde-no fuzzy text match (yapısal)
  - nli.py:                              claim ↔ evidence entailment (semantik)

LangGraph 'verify' düğümü her iki katmanı da çağırır.
"""
