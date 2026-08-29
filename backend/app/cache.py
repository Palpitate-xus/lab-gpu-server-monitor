"""TTL response cache with single-flight, protecting hot read endpoints.

Default backend is process-local memory (correct for the single-worker
deployment). Set REDIS_URL to switch to a shared Redis backend, e.g. for
multi-worker setups. Cache values must be JSON-serializable dicts/lists.
"""

from __future__ import annotations

import json
import logging
import threading
import time

logger = logging.getLogger("gpumon.cache")

_KEY_PREFIX = "gpumon:cache:"


class InMemoryBackend:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            hit = self._data.get(key)
            if not hit:
                return None
            expires, value = hit
            if expires < time.monotonic():
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: str, value, ttl: float) -> None:
        with self._lock:
            self._data[key] = (time.monotonic() + ttl, value)
            if len(self._data) > 1024:
                now = time.monotonic()
                stale = [k for k, (e, _) in self._data.items() if e < now]
                for k in stale:
                    self._data.pop(k, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class RedisBackend:
    def __init__(self, url: str) -> None:
        import redis

        self._r = redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        self._r.ping()

    def get(self, key: str):
        raw = self._r.get(_KEY_PREFIX + key)
        if raw is None:
            return None
        return json.loads(raw)

    def set(self, key: str, value, ttl: float) -> None:
        # default=str turns datetimes into ISO strings; response models parse them back
        self._r.set(_KEY_PREFIX + key, json.dumps(value, default=str), ex=max(1, int(ttl)))

    def clear(self) -> None:
        for k in self._r.scan_iter(_KEY_PREFIX + "*", count=200):
            self._r.delete(k)


_backend = None
_backend_lock = threading.Lock()


def get_backend():
    global _backend
    if _backend is not None:
        return _backend
    with _backend_lock:
        if _backend is not None:
            return _backend
        from .config import get_settings

        url = (get_settings().REDIS_URL or "").strip()
        if url:
            try:
                _backend = RedisBackend(url)
                logger.info("cache backend: redis (%s)", url.split("@")[-1])
            except Exception as exc:  # unreachable redis must not break the app
                logger.warning("redis unavailable (%s); falling back to in-memory cache", exc)
                _backend = InMemoryBackend()
        else:
            _backend = InMemoryBackend()
            logger.info("cache backend: in-memory (set REDIS_URL to use Redis)")
    return _backend


_inflight: dict[str, threading.Event] = {}
_inflight_lock = threading.Lock()


def cached(key: str, ttl: float, fn):
    """Return cached value for `key`, else compute via fn() once.

    Single-flight: concurrent callers for a missing key wait for the leader
    instead of stampeding the database. On any cache-backend failure the
    request degrades to a direct computation.
    """
    backend = get_backend()
    try:
        hit = backend.get(key)
        if hit is not None:
            return hit
    except Exception:
        return fn()

    with _inflight_lock:
        ev = _inflight.get(key)
        if ev is None:
            ev = threading.Event()
            _inflight[key] = ev
            leader = True
        else:
            leader = False

    if not leader:
        ev.wait(15)
        try:
            hit = backend.get(key)
            if hit is not None:
                return hit
        except Exception:
            pass
        return fn()

    try:
        value = fn()
        try:
            backend.set(key, value, ttl)
        except Exception:
            pass
        return value
    finally:
        with _inflight_lock:
            _inflight.pop(key, None)
        ev.set()


def invalidate_prefix(prefix: str) -> None:
    """Drop entries whose key starts with prefix (best-effort)."""
    backend = get_backend()
    if isinstance(backend, InMemoryBackend):
        with backend._lock:
            for k in [k for k in backend._data if k.startswith(prefix)]:
                backend._data.pop(k, None)
    else:
        try:
            for k in backend._r.scan_iter(_KEY_PREFIX + prefix + "*", count=200):
                backend._r.delete(k)
        except Exception:
            pass
