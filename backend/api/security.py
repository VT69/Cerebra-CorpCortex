"""
API-key authentication and a simple in-process rate limiter for endpoints
that write to the knowledge base or spend LLM budget.

Single-process only: in a multi-worker deployment the limiter should move to
a shared store (e.g. Redis) or the API gateway.
"""
import hashlib
import hmac
import threading
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import Depends, HTTPException, Request

from backend.config import settings


def _presented_key(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-api-key")


def check_api_key(request: Request, expected: Optional[str], purpose: str) -> str:
    """Return the presented key if it matches ``expected``; raise otherwise.
    Fails closed (503) when no key is configured for this purpose."""
    if not expected:
        raise HTTPException(status_code=503, detail=f"{purpose} disabled: no API key configured on the server")
    presented = _presented_key(request)
    if not presented or not hmac.compare_digest(presented.encode(), expected.encode()):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return presented


class SlidingWindowLimiter:
    """Allow at most ``limit`` calls per ``window_s`` seconds per caller."""

    def __init__(self, window_s: float = 60.0):
        self.window_s = window_s
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, caller: str, limit: int) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[caller]
            while q and now - q[0] >= self.window_s:
                q.popleft()
            if len(q) >= limit:
                retry = int(self.window_s - (now - q[0])) + 1
                raise HTTPException(status_code=429, detail="Rate limit exceeded",
                                    headers={"Retry-After": str(retry)})
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


write_limiter = SlidingWindowLimiter()


def _caller_id(request: Request, key: str) -> str:
    # Rate-limit per key (hashed so the key never sits in memory as a dict key)
    # and per client IP, so one leaked key can't be used from many hosts freely.
    ip = request.client.host if request.client else "unknown"
    return hashlib.sha256(f"{key}|{ip}".encode()).hexdigest()


async def require_write_access(request: Request) -> None:
    """FastAPI dependency for endpoints that write data or spend LLM budget."""
    key = check_api_key(request, settings.INGEST_API_KEY, "writes")
    write_limiter.check(_caller_id(request, key), settings.RATE_LIMIT_WRITES_PER_MIN)


WriteAccess = Depends(require_write_access)
