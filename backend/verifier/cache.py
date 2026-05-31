"""NLI doğrulama cache — aynı (claim, evidence) ikilisi tekrar doğrulanmasın.

NLI deterministik (model.eval() + temperature=0): aynı (claim_text, evidence_snippet)
her zaman aynı raw skoru üretir → güvenle cache'lenebilir. NLI ~100ms/pair (GPU),
cache hit Redis ~1ms veya bellek ~0 → tekrarlı doğrulamada ciddi hız.

Tasarım:
  - SENKRON cache (layer3_nli_batch zaten asyncio.to_thread içinde koşar → blocking
    redis.Redis çağrısı thread'de sorunsuz; async event-loop karmaşası yok).
  - Redis varsa orada (NLI_CACHE_ENABLED + REDIS_URL bağlanır), yoksa process-local
    bounded LRU dict'e graceful fallback. Cache ASLA doğrulamayı bozmaz (hata → miss).
  - RAW skor cache'lenir (label, entailment, contradiction); contradiction eşiği
    OKUMA anında uygulanır → NLI_CONTRADICTION_THRESHOLD değişse cache geçerli kalır.
  - Key namespace NLI model adına bağlı → model değişimi eski cache'i invalidate eder.

Değer şeması (JSON): {"l": label, "e": entailment_score, "c": contradiction_score}
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import OrderedDict

import structlog

from agents.config import NLI_CACHE_ENABLED, NLI_CACHE_TTL_S

log = structlog.get_logger()

_MEM_MAX = 5000  # bellek fallback üst sınırı (sabit RAM)


def _model_tag() -> str:
    """NLI model adının kısa hash'i — model değişince cache namespace değişir."""
    model = os.getenv("NLI_MODEL", "default")
    return hashlib.sha1(model.encode("utf-8")).hexdigest()[:8]


def nli_cache_key(claim_text: str, evidence: str) -> str:
    """(claim, evidence) → deterministik cache key. Model tag namespace'li."""
    h = hashlib.sha256()
    h.update(claim_text.encode("utf-8"))
    h.update(b"\x00")
    h.update(evidence.encode("utf-8"))
    return f"adalet:nli:{_model_tag()}:{h.hexdigest()}"


class VerificationCache:
    """NLI sonuç cache'i. Redis (varsa) + bellek fallback. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mem: OrderedDict[str, dict] = OrderedDict()
        self._redis = None
        self._redis_tried = False
        self.hits = 0
        self.misses = 0

    # ---- Redis lazy bağlanma (başarısızsa bellek fallback) ----
    def _get_redis(self):
        if self._redis is not None or self._redis_tried:
            return self._redis
        self._redis_tried = True
        url = os.getenv("REDIS_URL", "")
        if not url:
            log.info("nli_cache_memory_only", reason="no_redis_url")
            return None
        try:
            import redis  # sync client — thread içinde blocking OK
            client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2)
            client.ping()
            self._redis = client
            log.info("nli_cache_redis_connected")
        except Exception as exc:  # noqa: BLE001 — cache asla doğrulamayı bozmaz
            log.warning("nli_cache_redis_failed", error=str(exc))
            self._redis = None
        return self._redis

    # ---- bellek LRU yardımcıları ----
    def _mem_get(self, key: str) -> dict | None:
        with self._lock:
            if key in self._mem:
                self._mem.move_to_end(key)
                return self._mem[key]
        return None

    def _mem_set(self, key: str, val: dict) -> None:
        with self._lock:
            self._mem[key] = val
            self._mem.move_to_end(key)
            while len(self._mem) > _MEM_MAX:
                self._mem.popitem(last=False)

    # ---- public API ----
    def get_many(self, keys: list[str]) -> dict[str, dict]:
        """Verilen key'lerden cache'te olanları döndür ({key: {l,e,c}})."""
        if not NLI_CACHE_ENABLED or not keys:
            return {}
        found: dict[str, dict] = {}
        r = self._get_redis()
        if r is not None:
            try:
                raw = r.mget(keys)
                for key, val in zip(keys, raw):
                    if val:
                        found[key] = json.loads(val)
            except Exception as exc:  # noqa: BLE001
                log.warning("nli_cache_get_failed", error=str(exc))
        else:
            for key in keys:
                v = self._mem_get(key)
                if v is not None:
                    found[key] = v
        self.hits += len(found)
        self.misses += len(keys) - len(found)
        return found

    def set_many(self, items: dict[str, dict]) -> None:
        """Yeni NLI sonuçlarını cache'e yaz (TTL ile)."""
        if not NLI_CACHE_ENABLED or not items:
            return
        r = self._get_redis()
        if r is not None:
            try:
                pipe = r.pipeline()
                for key, val in items.items():
                    pipe.set(key, json.dumps(val, ensure_ascii=False), ex=NLI_CACHE_TTL_S)
                pipe.execute()
            except Exception as exc:  # noqa: BLE001
                log.warning("nli_cache_set_failed", error=str(exc))
        else:
            for key, val in items.items():
                self._mem_set(key, val)

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {"hits": self.hits, "misses": self.misses,
                "hit_rate": round(self.hits / total, 3) if total else 0.0,
                "backend": "redis" if self._redis is not None else "memory"}


_cache_singleton: VerificationCache | None = None


def get_verification_cache() -> VerificationCache:
    """Process-ömürlü cache singleton."""
    global _cache_singleton
    if _cache_singleton is None:
        _cache_singleton = VerificationCache()
    return _cache_singleton


def reset_verification_cache() -> None:
    """Test izolasyonu için singleton + sayaçları sıfırla."""
    global _cache_singleton
    _cache_singleton = None
