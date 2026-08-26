"""JWT revocation: in-memory jti blacklist.

Every token gets a unique jti. When a password changes, an account is
disabled/deleted, or a user logs out, we blacklist either that jti or
(mark) the user's tokens issued before that moment (per-user epoch).

Single-process deployment: memory is authoritative. If the app restarts the
blacklist empties, but tokens expire in <=2h anyway (ACCESS_TOKEN_EXPIRE_MINUTES).
"""

from __future__ import annotations

import threading
import time
import uuid

# jti -> expiry timestamp (for pruning)
_revoked_jti: dict[str, float] = {}
# user_id -> tokens issued before this ts are invalid
_user_epoch: dict[int, float] = {}
_lock = threading.Lock()

PRUNE_INTERVAL = 600


def new_jti() -> str:
    return uuid.uuid4().hex


def revoke_jti(jti: str, exp: float) -> None:
    with _lock:
        _revoked_jti[jti] = exp


def revoke_user_tokens(user_id: int) -> None:
    """Invalidate every token issued *before now* for this user."""
    with _lock:
        _user_epoch[user_id] = time.time()


def is_revoked(jti: str | None, user_id: int | None, issued_at: float | None) -> bool:
    now = time.time()
    with _lock:
        # occasional prune
        if len(_revoked_jti) > 4096:
            for k in [k for k, v in _revoked_jti.items() if v < now]:
                _revoked_jti.pop(k, None)
        if jti and jti in _revoked_jti:
            return True
        if user_id is not None and user_id in _user_epoch:
            if issued_at is None or issued_at < _user_epoch[user_id]:
                return True
    return False
