"""Offline break-glass reset for one administrator's MFA enrollment.

This command requires database access from the trusted application host. It is
dry-run by default and never changes a password. Prefer having another enrolled
administrator use the normal UI; use this only for documented recovery.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.database import SessionLocal  # noqa: E402
from app.models import AuditLog, User  # noqa: E402


def main(username: str, apply: bool) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username, User.role == "admin").first()
        if user is None:
            raise RuntimeError("administrator not found")
        was_enrolled = user.mfa_enrolled
        if apply:
            user.mfa_secret = ""
            user.mfa_confirmed = False
            user.mfa_last_counter = -1
            user.token_version += 1
            db.add(
                AuditLog(
                    username="system:local-recovery",
                    action="user.mfa_breakglass_reset",
                    detail=f"reset MFA for {user.username}",
                )
            )
            db.commit()
        else:
            db.rollback()
        print(
            f"MFA recovery {'applied' if apply else 'dry-run'}: "
            f"user={user.username}, previously_enrolled={was_enrolled}"
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    main(args.username, args.apply)
