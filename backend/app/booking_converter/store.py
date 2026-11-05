"""Short-lived storage for in-progress conversions and duplicate-request guards (Redis, in-memory fallback)."""

from __future__ import annotations

import json
import threading
import time

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


class ConversionStore:
    def __init__(self) -> None:
        self._redis = None
        self._checked = False
        self._mem: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def _client(self):
        if not self._checked:
            self._checked = True
            try:
                import redis

                c = redis.Redis.from_url(get_settings().redis_url, socket_timeout=0.3, socket_connect_timeout=0.3)
                c.ping()
                self._redis = c
            except Exception:  # pragma: no cover - environment dependent
                log.warning("booking_store_redis_unavailable_using_memory")
        return self._redis

    def _purge(self) -> None:
        now = time.time()
        for k in [k for k, (_, exp) in self._mem.items() if exp <= now]:
            self._mem.pop(k, None)

    def put(self, key: str, value: dict | str, ttl: int) -> None:
        raw = value if isinstance(value, str) else json.dumps(value)
        c = self._client()
        if c is not None:
            try:
                c.set(f"bc:{key}", raw, ex=ttl)
                return
            except Exception:  # noqa: S110  # pragma: no cover
                pass
        with self._lock:
            self._purge()
            self._mem[key] = (raw, time.time() + ttl)

    def get(self, key: str) -> str | None:
        c = self._client()
        if c is not None:
            try:
                v = c.get(f"bc:{key}")
                return v.decode() if v is not None else None
            except Exception:  # noqa: S110  # pragma: no cover
                pass
        with self._lock:
            self._purge()
            item = self._mem.get(key)
            return item[0] if item else None

    def get_json(self, key: str) -> dict | None:
        raw = self.get(key)
        return json.loads(raw) if raw else None

    def claim(self, key: str, ttl: int) -> bool:
        """Atomically create ``key``; False if it already exists (someone else holds it)."""
        c = self._client()
        if c is not None:
            try:
                return bool(c.set(f"bc:{key}", "1", nx=True, ex=ttl))
            except Exception:  # noqa: S110  # pragma: no cover
                pass
        with self._lock:
            self._purge()
            if key in self._mem:
                return False
            self._mem[key] = ("1", time.time() + ttl)
            return True

    def release(self, key: str) -> None:
        c = self._client()
        if c is not None:
            try:
                c.delete(f"bc:{key}")
            except Exception:  # noqa: S110  # pragma: no cover
                pass
        with self._lock:
            self._mem.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._mem.clear()
        c = self._client()
        if c is not None:  # pragma: no cover
            for k in c.scan_iter("bc:*"):
                c.delete(k)


store = ConversionStore()
