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
MAX_CACHE_VALUE_BYTES = 32 * 1024 * 1024
MAX_MEMORY_CACHE_ENTRIES = 1024


class InMemoryBackend:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()
        self._next_sweep = 0.0

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
            now = time.monotonic()
            self._data[key] = (now + ttl, value)
            if now >= self._next_sweep or len(self._data) > MAX_MEMORY_CACHE_ENTRIES:
                stale = [k for k, (e, _) in self._data.items() if e < now]
                for k in stale:
                    self._data.pop(k, None)
                self._next_sweep = now + 60.0
                # A large set of still-live parameter combinations must not
                # grow this process-local cache without bound. Dict insertion
                # order gives us a small FIFO fallback after stale eviction.
                while len(self._data) > MAX_MEMORY_CACHE_ENTRIES:
                    self._data.pop(next(iter(self._data)))

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._next_sweep = 0.0


class RedisBackend:
    def __init__(self, url: str) -> None:
        import redis
        from urllib.parse import urlsplit

        from .config import get_settings

        kwargs = {"socket_connect_timeout": 2, "socket_timeout": 2}
        if urlsplit(url).scheme.casefold() == "rediss":
            kwargs.update(ssl_cert_reqs="required", ssl_check_hostname=True)
            ca_path = get_settings().REDIS_SSL_CA.strip()
            if ca_path:
                kwargs["ssl_ca_certs"] = ca_path
        self._r = redis.Redis.from_url(url, **kwargs)
        self._r.ping()

    def get(self, key: str):
        # GETRANGE bounds memory even if a compromised/shared Redis instance
        # plants an unexpectedly large value in our namespace.
        raw = self._r.getrange(_KEY_PREFIX + key, 0, MAX_CACHE_VALUE_BYTES)
        if raw is None:
            return None
        if len(raw) > MAX_CACHE_VALUE_BYTES:
            raise ValueError("cached value exceeds the safety limit")
        if not raw:
            return None
        return json.loads(raw)

    def set(self, key: str, value, ttl: float) -> None:
        # default=str turns datetimes into ISO strings; response models parse them back
        payload = json.dumps(value, default=str)
        if len(payload.encode("utf-8")) > MAX_CACHE_VALUE_BYTES:
            return
        self._r.set(_KEY_PREFIX + key, payload, ex=max(1, int(ttl)))

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
                logger.info("cache backend: Redis enabled")
            except Exception as exc:  # unreachable redis must not break the app
                logger.warning(
                    "Redis unavailable (%s); falling back to in-memory cache",
                    type(exc).__name__,
                )
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
