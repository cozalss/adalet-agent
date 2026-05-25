"""Token bucket rate limiter — Bedesten API 10 req/30s sınırına uyum.

Tek paylaşılan bucket tüm fetch çağrıları için. Concurrent kullanım güvenli.
"""

from __future__ import annotations

import asyncio
import time


class AsyncTokenBucket:
    """Asenkron token bucket — kapasiteyi aşan istekler bekletilir."""

    def __init__(self, capacity: int, refill_per_sec: float) -> None:
        if capacity <= 0:
            raise ValueError("capacity > 0 olmalı")
        if refill_per_sec <= 0:
            raise ValueError("refill_per_sec > 0 olmalı")

        self._capacity = capacity
        self._refill_per_sec = refill_per_sec
        self._tokens: float = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> None:
        """Belirtilen sayıda token bulana kadar bekle, sonra kullan.

        Kilit içinde re-check edilen loop — bir başka coroutine token'ları
        ararken çalıp negatife düşürmesini engeller. Token negatif olmaz.
        """
        if tokens > self._capacity:
            raise ValueError(f"tokens={tokens} > capacity={self._capacity}")

        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                needed = tokens - self._tokens
                wait_sec = needed / self._refill_per_sec

            # Lock'ı bıraktık → başka coroutine girebilir. Re-check şart.
            await asyncio.sleep(wait_sec)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            float(self._capacity),
            self._tokens + elapsed * self._refill_per_sec,
        )
        self._last_refill = now

    async def available_tokens(self) -> float:
        """Debug için — kilit altında refill yapıp güncel token sayısı döner."""
        async with self._lock:
            self._refill()
            return self._tokens
