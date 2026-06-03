"""İstatistiksel yardımcılar — oran metriklerine güven aralığı (jüri titizliği).

Nokta-tahmini (P=1.0, R=0.875) küçük-N'de yanıltıcı: '8/8 → P=1.0' ama %95 alt-sınır ~0.63.
Wilson score aralığı normal-yaklaşımdan üstündür: 0/1'e yakın oranlarda ve küçük n'de
güvenilir, aralık [0,1] dışına TAŞMAZ (Wald yaklaşımı taşar). Saf fonksiyon — LLM/bağımlılık yok.

Ref: Wilson (1927); Brown, Cai & DasGupta (2001) küçük-n için Wilson'ı önerir.
"""

from __future__ import annotations

import math

# z=1.96 → %95 iki-taraflı güven aralığı.
Z_95 = 1.96


def wilson_interval(k: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """k başarı / n deneme oranı için Wilson score güven aralığı → (alt, üst), [0,1]'e kırpılı.

    n=0 → (0.0, 1.0) (bilgi yok). k=n (P=1.0) → alt-sınır < 1.0 (küçük-n'de dürüstlük).
    """
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n))
    return (max(0.0, center - half), min(1.0, center + half))


def fmt_ci(k: int, n: int, z: float = Z_95) -> str:
    """'%95 CI [alt, üst]' okunabilir string (rapor için)."""
    lo, hi = wilson_interval(k, n, z)
    return f"[{lo:.3f}, {hi:.3f}]"
