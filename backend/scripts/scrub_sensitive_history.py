"""Remove usernames and command-line arguments from stored metric history.

The command is dry-run by default. Use --apply after taking a database backup.
Only the process identity/argv fields are removed; resource values and all GPU
measurements remain unchanged.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.database import SessionLocal  # noqa: E402
from app.models import ServerMetric  # noqa: E402
from app.privacy import minimize_gpus, minimize_processes  # noqa: E402


def main(apply: bool) -> None:
    db = SessionLocal()
    scanned = changed = 0
    try:
        query = db.query(ServerMetric).order_by(ServerMetric.id).yield_per(250)
        for metric in query:
            scanned += 1
            processes = minimize_processes(metric.processes)
            gpus = minimize_gpus(metric.gpus)
            if (
                processes != (metric.processes or [])
                or gpus != (metric.gpus or [])
                or bool(metric.users)
            ):
                changed += 1
                if apply:
                    metric.processes = processes
                    metric.gpus = gpus
                    metric.users = []
            if apply and changed and changed % 250 == 0:
                db.commit()
        if apply:
            db.commit()
        else:
            db.rollback()
        print(
            f"history scrub {'applied' if apply else 'dry-run'}: "
            f"scanned={scanned}, changed={changed}"
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    main(args.apply)
