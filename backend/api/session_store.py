"""Session store — multi-turn konuşma geçmişi için.

Protocol pattern: in-memory (default, dev/test) ve Redis (production).
ENV ile seçilir:
    SESSION_STORE=memory|redis      (default memory)
    REDIS_URL=redis://localhost:6379  (redis seçiliyse)
    SESSION_TTL_S=3600                (1 saat default)
    SESSION_MAX_TURNS=20              (chat_history sınırı)

Veri modeli:
    key:    "adalet:session:{conversation_id}"
    value:  JSON: [{role, content, timestamp, domain}, ...]

KVKK:
  - TTL sıfırlanır (otomatik silme)
  - PII (TCKN/telefon) loglanırsa anonimleştirilir (gerekirse yeni katman)
  - Production'da Redis Türkiye sınırı içinde (Hetzner Helsinki yedek)
"""

from __future__ import annotations

import json
import os
import time
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Protocol

import structlog

from agents.state import ConversationTurn

log = structlog.get_logger()

STORE_KIND = os.getenv("SESSION_STORE", "memory").lower()
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
SESSION_TTL_S = int(os.getenv("SESSION_TTL_S", "3600"))
SESSION_MAX_TURNS = int(os.getenv("SESSION_MAX_TURNS", "20"))


def _key(conversation_id: str) -> str:
    """Anahtar şeması — namespace prefix."""
    return f"adalet:session:{conversation_id}"


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


# --------------------------------------------------------------------------
#  Protocol
# --------------------------------------------------------------------------

class SessionStore(Protocol):
    """Tüm session backend'leri bu protokole uyar."""

    name: str

    async def get_history(self, conversation_id: str) -> list[ConversationTurn]: ...
    async def append_turn(self, conversation_id: str, turn: ConversationTurn) -> None: ...
    async def clear(self, conversation_id: str) -> None: ...
    async def health(self) -> bool: ...


# --------------------------------------------------------------------------
#  In-memory store — default, dev/test
# --------------------------------------------------------------------------

class InMemorySessionStore:
    """Process-local TTL LRU. Restart'ta kaybolur — dev/test/CI için."""

    name = "memory"

    def __init__(
        self,
        ttl_s: int = SESSION_TTL_S,
        max_sessions: int = 1000,
        max_turns: int = SESSION_MAX_TURNS,
    ) -> None:
        self.ttl_s = ttl_s
        self.max_sessions = max_sessions
        self.max_turns = max_turns
        # (turns_list, last_access_epoch)
        self._data: OrderedDict[str, tuple[list[ConversationTurn], float]] = OrderedDict()

    def _evict_expired(self) -> None:
        now = time.time()
        dead = [k for k, (_t, last) in self._data.items() if now - last > self.ttl_s]
        for k in dead:
            self._data.pop(k, None)
        while len(self._data) > self.max_sessions:
            self._data.popitem(last=False)

    async def get_history(self, conversation_id: str) -> list[ConversationTurn]:
        self._evict_expired()
        entry = self._data.get(conversation_id)
        if not entry:
            return []
        turns, _last = entry
        self._data[conversation_id] = (turns, time.time())
        self._data.move_to_end(conversation_id)
        # Defensive copy
        return list(turns)

    async def append_turn(
        self, conversation_id: str, turn: ConversationTurn,
    ) -> None:
        self._evict_expired()
        if "timestamp" not in turn:
            turn = {**turn, "timestamp": _utcnow_iso()}  # type: ignore[typeddict-item]
        entry = self._data.get(conversation_id)
        turns: list[ConversationTurn] = entry[0] if entry else []
        turns.append(turn)
        # Sliding window
        if len(turns) > self.max_turns:
            turns = turns[-self.max_turns:]
        self._data[conversation_id] = (turns, time.time())
        self._data.move_to_end(conversation_id)

    async def clear(self, conversation_id: str) -> None:
        self._data.pop(conversation_id, None)

    async def health(self) -> bool:
        return True


# --------------------------------------------------------------------------
#  Redis store — production
# --------------------------------------------------------------------------

class RedisSessionStore:
    """redis.asyncio backend. TTL otomatik (Redis EXPIRE)."""

    name = "redis"

    def __init__(
        self,
        url: str = REDIS_URL,
        ttl_s: int = SESSION_TTL_S,
        max_turns: int = SESSION_MAX_TURNS,
    ) -> None:
        self.url = url
        self.ttl_s = ttl_s
        self.max_turns = max_turns
        self._client = None

    async def _get_client(self):
        if self._client is None:
            try:
                from redis import asyncio as aioredis
            except ImportError as exc:
                raise RuntimeError(f"redis paketi yok: {exc}") from exc
            self._client = aioredis.from_url(
                self.url, encoding="utf-8", decode_responses=True,
            )
        return self._client

    async def get_history(self, conversation_id: str) -> list[ConversationTurn]:
        client = await self._get_client()
        raw = await client.get(_key(conversation_id))
        if not raw:
            return []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data  # type: ignore[return-value]
        except json.JSONDecodeError:
            log.warning("session_corrupted", conversation_id=conversation_id)
        return []

    async def append_turn(
        self, conversation_id: str, turn: ConversationTurn,
    ) -> None:
        client = await self._get_client()
        if "timestamp" not in turn:
            turn = {**turn, "timestamp": _utcnow_iso()}  # type: ignore[typeddict-item]
        # GET → modify → SET (race-safe değil ama OK bu use-case için)
        existing = await self.get_history(conversation_id)
        existing.append(turn)
        if len(existing) > self.max_turns:
            existing = existing[-self.max_turns:]
        await client.set(
            _key(conversation_id),
            json.dumps(existing, ensure_ascii=False),
            ex=self.ttl_s,
        )

    async def clear(self, conversation_id: str) -> None:
        client = await self._get_client()
        await client.delete(_key(conversation_id))

    async def health(self) -> bool:
        try:
            client = await self._get_client()
            return bool(await client.ping())
        except Exception as exc:
            log.warning("redis_health_failed", error=str(exc))
            return False


# --------------------------------------------------------------------------
#  Factory + singleton
# --------------------------------------------------------------------------

_store_singleton: SessionStore | None = None


def get_store() -> SessionStore:
    global _store_singleton
    if _store_singleton is not None:
        return _store_singleton

    kind = STORE_KIND
    _store_singleton = RedisSessionStore() if kind == "redis" else InMemorySessionStore()
    log.info("session_store_loaded", kind=_store_singleton.name)
    return _store_singleton


def reset_store() -> None:
    """Test fixture — singleton sıfırla."""
    global _store_singleton
    _store_singleton = None


__all__ = (
    "InMemorySessionStore",
    "RedisSessionStore",
    "SessionStore",
    "get_store",
    "reset_store",
)
