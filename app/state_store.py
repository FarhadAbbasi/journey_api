from __future__ import annotations
import json
import os
from typing import Any, Dict, Optional

STATE_TTL_SECONDS = int(os.getenv("STATE_TTL_SECONDS", "86400"))
REDIS_URL = os.getenv("REDIS_URL", "").strip()

class InMemoryStore:
    def __init__(self):
        self._db: Dict[str, Dict[str, Any]] = {}

    async def get(self, key: str) -> Optional[dict]:
        return self._db.get(key)

    async def set(self, key: str, value: dict) -> None:
        self._db[key] = value

def get_store():
    if not REDIS_URL:
        return InMemoryStore()

    try:
        import redis.asyncio as redis
        r = redis.from_url(REDIS_URL, decode_responses=True)

        class RedisStore:
            async def get(self, key: str) -> Optional[dict]:
                raw = await r.get(key)
                return json.loads(raw) if raw else None

            async def set(self, key: str, value: dict) -> None:
                await r.set(key, json.dumps(value), ex=STATE_TTL_SECONDS)

        return RedisStore()
    except Exception:
        # Fallback if redis isn't available
        return InMemoryStore()
