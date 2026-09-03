"""Bounded login rate limiting: per-IP + per-IP/account tracking.

In-memory sliding window (single-process deployment; no Redis dependency).
- per IP/account: 5 failures / 10 min -> that source/account pair is delayed
- per IP:        20 failures / 10 min -> that source is delayed

There is deliberately no global username lock: an unauthenticated attacker
must not be able to lock an administrator out from every trusted source.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

MAX_FAILURES_PAIR = 5
MAX_FAILURES_IP = 20
WINDOW_SECONDS = 600  # 10 min
LOCK_SECONDS = 600
MAX_BUCKETS = 4096


@dataclass
class _Counter:
    failures: list[float] = field(default_factory=list)
    locked_until: float = 0.0


class LoginRateLimiter:
    def __init__(self):
        self._by_ip: OrderedDict[str, _Counter] = OrderedDict()
        self._by_pair: OrderedDict[str, _Counter] = OrderedDict()
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
            for key, table in (
                (f"ip:{ip}", self._by_ip),
                (f"pair:{ip}\0{username.casefold()}", self._by_pair),
            ):
                c = table.get(key)
                if c and c.locked_until > now:
                    return False, int(c.locked_until - now)
            return True, 0

    def _threshold(self, table: dict) -> int:
        return MAX_FAILURES_IP if table is self._by_ip else MAX_FAILURES_PAIR

    @staticmethod
    def _bounded(table: OrderedDict[str, _Counter]) -> None:
        while len(table) > MAX_BUCKETS:
            table.popitem(last=False)

    def record_failure(self, ip: str, username: str) -> None:
        now = time.time()
        with self._lock:
            for table, key in (
                (self._by_ip, f"ip:{ip}"),
                (self._by_pair, f"pair:{ip}\0{username.casefold()}"),
            ):
                c = table.setdefault(key, _Counter())
                table.move_to_end(key)
                self._prune(c, now)
                c.failures.append(now)
                if len(c.failures) >= self._threshold(table):
                    c.locked_until = now + LOCK_SECONDS
                    c.failures = []
                self._bounded(table)
            # opportunistically drop long-empty entries to bound memory
            for table in (self._by_ip, self._by_pair):
                for k in [k for k, c in table.items() if self._stale(c, now)]:
                    table.pop(k, None)

    def record_success(self, ip: str, username: str) -> None:
        with self._lock:
            self._by_pair.pop(f"pair:{ip}\0{username.casefold()}", None)

    def status(self) -> dict:
        now = time.time()
        with self._lock:
            return {
                "locked_ip_count": sum(c.locked_until > now for c in self._by_ip.values()),
                "locked_pair_count": sum(c.locked_until > now for c in self._by_pair.values()),
                "tracked_bucket_count": len(self._by_ip) + len(self._by_pair),
            }


limiter = LoginRateLimiter()
# Independent buckets for password/TOTP confirmations performed with an
# already-authenticated session. They must not consume the public login quota.
step_up_limiter = LoginRateLimiter()
