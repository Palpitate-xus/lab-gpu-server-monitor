"""One-off import: migrate existing SQLite data into MySQL.

Copies servers (with encrypted credentials), users, alert rules/events, settings
and (optionally) historical metrics. Run inside the container:
    python3 -m app.import_sqlite /app/data/gpu_monitor.db
"""

from __future__ import annotations

import json
import sqlite3
import sys

from .database import IS_MYSQL, SessionLocal
from .models import AlertEvent, AlertRule, AuditLog, Server, ServerMetric, Setting, User


def _fetch_all(cur, table: str) -> list[dict]:
    cur.execute(f"SELECT * FROM {table}")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def import_from_sqlite(sqlite_path: str, with_history: bool = True) -> dict:
    assert IS_MYSQL, "target database must be MySQL (DATABASE_URL)"
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    counts = {}
    db = SessionLocal()
    try:
        # settings
        for row in _fetch_all(cur, "settings"):
            if not db.get(Setting, row["key"]):
                db.add(Setting(key=row["key"], value=row["value"] or ""))
        db.commit()
        counts["settings"] = len(_fetch_all(cur, "settings"))

        # users
        n = 0
        for row in _fetch_all(cur, "users"):
            if db.query(User).filter(User.username == row["username"]).first():
                continue
            db.add(User(
                id=row["id"], username=row["username"], password_hash=row["password_hash"],
                display_name=row.get("display_name") or "", email=row.get("email") or "",
                role=row.get("role") or "viewer", is_active=bool(row.get("is_active", 1)),
            ))
            n += 1
        db.commit()
        counts["users"] = n

        # servers
        n = 0
        for row in _fetch_all(cur, "servers"):
            if db.get(Server, row["id"]):
                continue
            db.add(Server(
                id=row["id"], name=row["name"], host=row["host"], port=row["port"],
                auth_type=row.get("auth_type") or "password", username=row["username"],
                password=row.get("password") or "", private_key=row.get("private_key") or "",
                passphrase=row.get("passphrase") or "", enabled=bool(row.get("enabled", 1)),
                tags=json.loads(row["tags"]) if row.get("tags") else [],
                note=row.get("note") or "",
            ))
            n += 1
        db.commit()
        counts["servers"] = n

        # alert rules / events
        n = 0
        for row in _fetch_all(cur, "alert_rules"):
            if not db.get(AlertRule, row["id"]):
                db.add(AlertRule(
                    id=row["id"], name=row["name"], metric=row["metric"], op=row["op"],
                    threshold=row["threshold"], duration_minutes=row.get("duration_minutes") or 0,
                    server_id=row.get("server_id"), enabled=bool(row.get("enabled", 1)),
                ))
                n += 1
        db.commit()
        counts["alert_rules"] = n

        n = 0
        for row in _fetch_all(cur, "alert_events"):
            db.add(AlertEvent(
                rule_id=row.get("rule_id"), rule_name=row.get("rule_name") or "",
                server_id=row["server_id"], server_name=row.get("server_name") or "",
                metric=row["metric"], value=row.get("value") or 0,
                threshold=row.get("threshold") or 0, message=row.get("message") or "",
                triggered_at=row["triggered_at"], recovered_at=row.get("recovered_at"),
                notified=bool(row.get("notified", 0)),
            ))
            n += 1
        db.commit()
        counts["alert_events"] = n

        # audit logs
        n = 0
        for row in _fetch_all(cur, "audit_logs"):
            db.add(AuditLog(ts=row["ts"], username=row.get("username") or "",
                            action=row.get("action") or "", detail=row.get("detail") or ""))
            n += 1
        db.commit()
        counts["audit_logs"] = n

        # metrics history (bulk, chunked)
        if with_history:
            cur.execute("SELECT COUNT(*) FROM server_metrics")
            total = cur.fetchone()[0]
            cur.execute("SELECT * FROM server_metrics ORDER BY id")
            cols = [d[0] for d in cur.description]
            n = 0
            CHUNK = 200
            buffer = []
            for row in cur.fetchall():
                r = dict(zip(cols, row))
                m = ServerMetric(
                    server_id=r["server_id"], collected_at=r["collected_at"],
                    hostname=r.get("hostname") or "", os=r.get("os") or "",
                    kernel=r.get("kernel") or "", uptime_seconds=r.get("uptime_seconds") or 0,
                    cpu_model=r.get("cpu_model") or "", cpu_count=r.get("cpu_count") or 0,
                    cpu_percent=r.get("cpu_percent") or 0, cpu_freq_avg=r.get("cpu_freq_avg") or 0,
                    cpu_temp_package=r.get("cpu_temp_package") or 0,
                    cores=json.loads(r["cores"]) if r.get("cores") else [],
                    load1=r.get("load1") or 0, load5=r.get("load5") or 0, load15=r.get("load15") or 0,
                    mem_total_mb=r.get("mem_total_mb") or 0, mem_used_mb=r.get("mem_used_mb") or 0,
                    mem_available_mb=r.get("mem_available_mb") or 0, mem_cached_mb=r.get("mem_cached_mb") or 0,
                    swap_total_mb=r.get("swap_total_mb") or 0, swap_used_mb=r.get("swap_used_mb") or 0,
                    disk_total_gb=r.get("disk_total_gb") or 0, disk_used_gb=r.get("disk_used_gb") or 0,
                    disks=json.loads(r["disks"]) if r.get("disks") else [],
                    disk_io=json.loads(r["disk_io"]) if r.get("disk_io") else [],
                    net_rx_bytes=r.get("net_rx_bytes") or 0, net_tx_bytes=r.get("net_tx_bytes") or 0,
                    net_ifaces=json.loads(r["net_ifaces"]) if r.get("net_ifaces") else [],
                    users=json.loads(r["users"]) if r.get("users") else [],
                    gpu_count=r.get("gpu_count") or 0, gpu_driver=r.get("gpu_driver") or "",
                    gpus=json.loads(r["gpus"]) if r.get("gpus") else [],
                    processes=json.loads(r["processes"]) if r.get("processes") else [],
                    duration=r.get("duration") or 0,
                    status=r.get("status") or "ok", error=r.get("error") or "",
                )
                buffer.append(m)
                n += 1
                if len(buffer) >= CHUNK:
                    db.bulk_save_objects(buffer)
                    db.commit()
                    buffer = []
            if buffer:
                db.bulk_save_objects(buffer)
                db.commit()
            counts["metrics"] = n
        return counts
    finally:
        db.close()
        conn.close()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "/app/data/gpu_monitor.db"
    print(json.dumps(import_from_sqlite(path), indent=2))
