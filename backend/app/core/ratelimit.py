"""Fixed-window rate limiter backed by Redis, with an in-memory fallback."""

from __future__ import annotations

import threading
import time

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


class RateLimiter:
    def __init__(self) -> None:
        self._redis = None
        self._redis_checked = False
        self._mem: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def _client(self):
        if not self._redis_checked:
            self._redis_checked = True
            try:
                import redis

                client = redis.Redis.from_url(get_settings().redis_url, socket_timeout=0.3, socket_connect_timeout=0.3)
                client.ping()
                self._redis = client
            except Exception:  # pragma: no cover - environment dependent
                log.warning("rate_limiter_redis_unavailable_using_memory")
        return self._redis

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        """Register a hit. Returns (allowed, retry_after_seconds)."""
        bucket = int(time.time() // window_seconds)
        full_key = f"rl:{key}:{bucket}"
        client = self._client()
        if client is not None:
            try:
                count = client.incr(full_key)
                if count == 1:
                    client.expire(full_key, window_seconds)
                return count <= limit, window_seconds - int(time.time() % window_seconds)
            except Exception:  # noqa: S110 - fall back to in-memory limiter  # pragma: no cover
                pass
        with self._lock:
            count, _ = self._mem.get(full_key, (0, 0.0))
            self._mem[full_key] = (count + 1, time.time())
            if len(self._mem) > 10000:
                cutoff = time.time() - 2 * window_seconds
                self._mem = {k: v for k, v in self._mem.items() if v[1] > cutoff}
            return count + 1 <= limit, window_seconds - int(time.time() % window_seconds)

    def reset(self) -> None:
        with self._lock:
            self._mem.clear()
        if self._redis is not None:  # pragma: no cover
            for k in self._redis.scan_iter("rl:*"):
                self._redis.delete(k)


limiter = RateLimiter()
