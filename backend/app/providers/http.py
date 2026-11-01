"""Resilient HTTP client shared by external provider adapters.

* Token-bucket rate limiting per provider (in-process; Celery runs ingestion
  on a dedicated queue with concurrency 1 per provider so this is sufficient).
* Retries with exponential backoff on network errors, HTTP 429 and 5xx.
* Every request is recorded in ``data_provider_logs`` (own session, so logs
  survive an ingestion rollback) for provider health monitoring.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

from app.core.logging import get_logger
from app.providers.football.base import ProviderError

log = get_logger(__name__)

RETRYABLE = {429, 500, 502, 503, 504}


class RateLimiter:
    def __init__(self, per_minute: int):
        self.capacity = max(1, per_minute)
        self.tokens = float(self.capacity)
        self.rate = self.capacity / 60.0
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self, sleep: Callable[[float], None] = time.sleep) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            sleep(wait)


def record_provider_call(provider: str, operation: str, status: str, http_status: int | None, latency_ms: float,
                         records: int | None = None, error: str | None = None) -> None:
    try:
        from app.core.database import SessionLocal
        from app.models import DataProviderLog

        with SessionLocal() as db:
            db.add(DataProviderLog(provider=provider, operation=operation, status=status, http_status=http_status,
                                   latency_ms=latency_ms, records=records, error=(error or "")[:2000] or None))
            db.commit()
    except Exception as exc:  # pragma: no cover - logging must never break ingestion
        log.warning("provider_log_failed", error=str(exc))


class ProviderHttpClient:
    def __init__(
        self,
        provider: str,
        base_url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        per_minute: int = 30,
        max_retries: int = 4,
        backoff_base: float = 1.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        log_calls: bool = True,
    ):
        self.provider = provider
        self.client = httpx.Client(base_url=base_url, headers=headers or {}, params=params or {}, timeout=20.0,
                                   transport=transport)
        self.limiter = RateLimiter(per_minute)
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.sleep = sleep
        self.log_calls = log_calls

    def get(self, path: str, params: dict[str, Any] | None = None, operation: str | None = None) -> dict:
        op = operation or path
        attempt = 0
        while True:
            attempt += 1
            self.limiter.acquire(self.sleep)
            started = time.perf_counter()
            status_code = None
            try:
                resp = self.client.get(path, params=params)
                status_code = resp.status_code
                latency = (time.perf_counter() - started) * 1000
                if status_code in RETRYABLE and attempt <= self.max_retries:
                    self._log(op, "rate_limited" if status_code == 429 else "error", status_code, latency,
                              error=f"retryable HTTP {status_code}")
                    retry_after = resp.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else self.backoff_base * 2 ** (attempt - 1)
                    self.sleep(delay)
                    continue
                if status_code >= 400:
                    self._log(op, "error", status_code, latency, error=resp.text[:500])
                    raise ProviderError(f"{self.provider} {op} failed with HTTP {status_code}")
                data = resp.json()
                self._log(op, "success", status_code, latency, records=_count(data))
                return data
            except (httpx.TransportError, ValueError) as exc:
                latency = (time.perf_counter() - started) * 1000
                self._log(op, "error", status_code, latency, error=str(exc))
                if attempt <= self.max_retries:
                    self.sleep(self.backoff_base * 2 ** (attempt - 1))
                    continue
                raise ProviderError(f"{self.provider} {op} failed: {exc}") from exc

    def _log(self, op: str, status: str, http_status: int | None, latency: float, records: int | None = None,
             error: str | None = None) -> None:
        if self.log_calls:
            record_provider_call(self.provider, op, status, http_status, latency, records, error)


def _count(data: Any) -> int | None:
    if isinstance(data, dict):
        for key in ("response", "data"):
            if isinstance(data.get(key), list):
                return len(data[key])
    return None
