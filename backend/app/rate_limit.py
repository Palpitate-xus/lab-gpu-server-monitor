"""Login rate limiting: per-IP + per-username failed-attempt tracking.

In-memory sliding window (single-process deployment; no Redis dependency).
- per username:    5 failures / 10 min  -> account locked 10 min
- per IP:         10 failures / 10 min  -> IP locked 10 min
  (shared NAT/proxy offices won't brick each other so easily)
- successful login clears the counters for that ip+username pair
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

MAX_FAILURES = 5
MAX_FAILURES_IP = 10
WINDOW_SECONDS = 600  # 10 min
LOCK_SECONDS = 600


@dataclass
class _Counter:
    failures: list[float] = field(default_factory=list)
    locked_until: float = 0.0


class LoginRateLimiter:
    def __init__(self):
        self._by_ip: dict[str, _Counter] = {}
        self._by_user: dict[str, _Counter] = {}
        self._lock = threading.Lock()

    def _prune(self, c: _Counter, now: float) -> None:
        c.failures = [t for t in c.failures if now - t < WINDOW_SECONDS]

    @staticmethod
    def _stale(c: _Counter, now: float) -> bool:
        return not c.failures and c.locked_until <= now

    def check(self, ip: str, username: str) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = time.time()
        with self._lock:
            for key, table in ((f"ip:{ip}", self._by_ip), (f"user:{username}", self._by_user)):
                c = table.get(key)
                if c and c.locked_until > now:
                    return False, int(c.locked_until - now)
            return True, 0

    def _threshold(self, table: dict) -> int:
        return MAX_FAILURES_IP if table is self._by_ip else MAX_FAILURES

    def record_failure(self, ip: str, username: str) -> None:
        now = time.time()
        with self._lock:
            for table, key in ((self._by_ip, f"ip:{ip}"), (self._by_user, f"user:{username}")):
                c = table.setdefault(key, _Counter())
                self._prune(c, now)
                c.failures.append(now)
                if len(c.failures) >= self._threshold(table):
                    c.locked_until = now + LOCK_SECONDS
                    c.failures = []
            # opportunistically drop long-empty entries to bound memory
            for table in (self._by_ip, self._by_user):
                for k in [k for k, c in table.items() if self._stale(c, now)]:
                    table.pop(k, None)

    def record_success(self, ip: str, username: str) -> None:
        with self._lock:
            self._by_ip.pop(f"ip:{ip}", None)
            self._by_user.pop(f"user:{username}", None)

    def status(self) -> dict:
        now = time.time()
        with self._lock:
            locked_ips = [k[3:] for k, c in self._by_ip.items() if c.locked_until > now]
            locked_users = [k[5:] for k, c in self._by_user.items() if c.locked_until > now]
            return {"locked_ips": locked_ips, "locked_users": locked_users}


limiter = LoginRateLimiter()
