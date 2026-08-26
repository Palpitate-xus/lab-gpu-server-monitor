"""Database-agnostic migration runner (works on both MySQL and SQLite).

Migrations are plain SQL files applied per-statement; dialect differences are
handled by keeping statements ANSI-portable and tolerating "duplicate column" /
"already exists" errors so a fresh database (created by create_all) can skip
already-present objects. MySQL notes:
  - SQLite: ALTER TABLE x DROP COLUMN y              (sqlite >= 3.35)
  - MySQL:  both ALTER TABLE DROP COLUMN and ADD COLUMN are fine
  - partial indexes (WHERE ...) are SQLite-only -> create plain index on MySQL
"""

from __future__ import annotations

import logging
import os
import re

from sqlalchemy import text

from .database import IS_MYSQL, engine

logger = logging.getLogger("gpumon.migrate")

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")

_NAME_RE = re.compile(r"^(\d+)_.*\.sql$")
_TOLERATED = (
    "duplicate column",
    "already exists",
    "duplicate key name",
    "check that column/key exists",  # mysql drop-index miss
    # fresh databases get the final schema from create_all(); legacy-column
    # drops/alterations legitimately find nothing to change
    "no such column",
    "unknown column",
    "can't drop",  # mysql: can't drop column/key that doesn't exist
    "check that column exists",
)


def _ensure_table(conn) -> None:
    conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " name VARCHAR(255) UNIQUE NOT NULL,"
            " applied_at VARCHAR(64) NOT NULL)"
        ) if not IS_MYSQL else
        text(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " id INT AUTO_INCREMENT PRIMARY KEY,"
            " name VARCHAR(255) UNIQUE NOT NULL,"
            " applied_at VARCHAR(64) NOT NULL)"
        )
    )
    conn.commit()


def _applied(conn) -> set:
    rows = conn.execute(text("SELECT name FROM schema_migrations")).fetchall()
    return {r[0] for r in rows}


def _statements(sql: str) -> list:
    # strip line comments, then split statements on ';' (newlines preserved so
    # multi-line CREATE TABLE bodies stay inside one statement)
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    stmts = []
    for stmt in "\n".join(lines).split(";"):
        s = stmt.strip()
        if s:
            stmts.append(s)
    return stmts


def run_migrations() -> list[str]:
    if not os.path.isdir(MIGRATIONS_DIR):
        return []
    files = sorted(f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql") and _NAME_RE.match(f))
    applied_now: list[str] = []
    with engine.connect() as conn:
        _ensure_table(conn)
        done = _applied(conn)
        for fname in files:
            if fname in done:
                continue
            if fname.endswith(".mysql.sql") and not IS_MYSQL:
                continue
            if fname.endswith(".sqlite.sql") and IS_MYSQL:
                continue
            with open(os.path.join(MIGRATIONS_DIR, fname), encoding="utf-8") as fh:
                sql = fh.read()
            logger.info("applying migration %s", fname)
            try:
                for stmt in _statements(sql):
                    if not stmt.strip():
                        continue
                    if not IS_MYSQL:
                        # translate the few MySQL-isms we use in migration files
                        stmt = stmt.replace("INSERT IGNORE INTO", "INSERT OR IGNORE INTO")
                    try:
                        conn.execute(text(stmt))
                    except Exception as e:
                        msg = str(e).lower()
                        if any(t in msg for t in _TOLERATED):
                            continue
                        raise
                conn.execute(
                    text("INSERT INTO schema_migrations (name, applied_at) VALUES (:n, NOW())" if IS_MYSQL
                         else "INSERT INTO schema_migrations (name, applied_at) VALUES (:n, datetime('now'))"),
                    {"n": fname},
                )
                conn.commit()
                applied_now.append(fname)
            except Exception:
                conn.rollback()
                logger.exception("migration %s failed", fname)
                raise
    return applied_now
