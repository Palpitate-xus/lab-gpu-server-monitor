"""Lightweight SQLite migration runner: applies pending SQL files from migrations/.

Runs AFTER SQLAlchemy create_all (which creates any brand-new tables from the
models). Migrations therefore only need to handle ALTERs on existing databases;
"duplicate column" errors are tolerated so the same file works on fresh DBs.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3

logger = logging.getLogger("gpumon.migrate")

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")

_NAME_RE = re.compile(r"^(\d+)_.*\.sql$")
_TOLERATED = ("duplicate column name", "already exists")


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " name TEXT UNIQUE NOT NULL,"
        " applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.commit()


def _applied(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM schema_migrations").fetchall()
    return {r[0] for r in rows}


def _statements(sql: str) -> list[str]:
    stmts = []
    for stmt in sql.split(";"):
        s = stmt.strip()
        if s:
            stmts.append(s)
    return stmts


def run_migrations(db_path: str) -> list[str]:
    """Apply pending migrations; returns list of applied file names."""
    if not os.path.isdir(MIGRATIONS_DIR):
        return []
    files = sorted(
        f for f in os.listdir(MIGRATIONS_DIR)
        if f.endswith(".sql") and _NAME_RE.match(f)
    )
    applied_now: list[str] = []
    conn = sqlite3.connect(db_path)
    try:
        _ensure_table(conn)
        done = _applied(conn)
        for fname in files:
            if fname in done:
                continue
            path = os.path.join(MIGRATIONS_DIR, fname)
            with open(path, encoding="utf-8") as fh:
                sql = fh.read()
            logger.info("applying migration %s", fname)
            try:
                for stmt in _statements(sql):
                    try:
                        conn.execute(stmt)
                    except sqlite3.OperationalError as e:
                        if any(t in str(e).lower() for t in _TOLERATED):
                            continue  # idempotent on fresh DBs
                        raise
                conn.execute("INSERT INTO schema_migrations (name) VALUES (?)", (fname,))
                conn.commit()
                applied_now.append(fname)
            except Exception:
                conn.rollback()
                logger.exception("migration %s failed", fname)
                raise
    finally:
        conn.close()
    return applied_now
