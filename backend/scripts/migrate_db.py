"""Create/upgrade the database using a short-lived DDL credential.

Set DATABASE_URL to the migration account only for this command. The normal
web process should use a separate account limited to SELECT/INSERT/UPDATE/DELETE.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.database import Base, engine  # noqa: E402
from app.migrate import run_migrations  # noqa: E402
from app import models  # noqa: E402,F401


def main() -> None:
    Base.metadata.create_all(bind=engine)
    applied = run_migrations()
    print("database schema ready" + (f"; applied: {', '.join(applied)}" if applied else ""))


if __name__ == "__main__":
    main()
