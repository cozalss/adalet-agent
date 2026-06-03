"""Canlı taslak akışı — draft node'un ürettiği token'ları SSE'ye taşıyan kanal.

Draft node, LLM üretirken her token'ı buradaki `draft_token_sink`'e iter;
`/ask/stream` event_source'u bu sink'i kendi async token kuyruğuna bağlar →
`draft_token` SSE eventi → frontend canlı yazım.

sink yoksa (None) streaming KAPALI → node normal (bloklayan) `chat()` kullanır.
Böylece /ask (non-stream), mock/server client ve testler etkilenmez.

KIRMIZI ÇİZGİ NOTU: Akan metin DOĞRULANMAMIŞ taslaktır; frontend bunu "doğrulanıyor"
rozetiyle gösterir ve `final` geldiğinde verify'dan geçmiş cevaba oturtur. Akan
taslak asla nihai/doğrulanmış cevap gibi sunulmaz.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable

# Per-request token tüketici. event_source set eder, draft node okur.
# ContextVar: ensure_future/astream alt-task'larına kopyalanır → draft node görür.
draft_token_sink: contextvars.ContextVar[Callable[[str], None] | None] = (
    contextvars.ContextVar("draft_token_sink", default=None)
)
