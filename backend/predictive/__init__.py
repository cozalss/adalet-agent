"""predictive — dava sonucu tahmin ajanı (opsiyonel 8. ajan).

Sprint-7/8'de fine-tuned BERT-TR planlı (bkz. README.md). Bu paket şimdilik
README'nin "Aşama-1: Regex + Heuristic" yaklaşımını CANLI çalışır bir baseline
olarak sunar; `predict_outcome()` arayüzü stabildir — fine-tuned model geldiğinde
çağıranlar değişmeden içerik değişir.
"""

from __future__ import annotations

from predictive.inference import predict_outcome

__all__ = ("predict_outcome",)
