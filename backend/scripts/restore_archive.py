"""Restore archived server_metrics from a daily tar.gz JSONL archive.

Usage (from backend/):
    DATABASE_URL='...' python3 scripts/restore_archive.py /path/server_metrics_*.tar.gz

Idempotent: servers already present are kept as-is; metric rows with an
existing (server_id, collected_at) are skipped.
"""

import json
import os
import sys
import tarfile
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.database import SessionLocal  # noqa: E402
from app.models import Server, ServerMetric  # noqa: E402

COLS = {c.key for c in ServerMetric.__table__.columns}
SRV_COLS = {c.key for c in Server.__table__.columns}


def _parse_dt(v):
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return v
    return v


def main(path: str) -> None:
    db = SessionLocal()
    restored = skipped = servers_added = 0
    try:
        with tarfile.open(path, "r:gz") as tf:
            members = tf.getmembers()

            # 1) servers first - they are the FK targets for metrics
            for member in members:
                if not member.name.startswith("servers_"):
                    continue
                fh = tf.extractfile(member)
                if fh is None:
                    continue
                for line in fh:
                    if not line.strip():
                        continue
                    obj = {k: v for k, v in json.loads(line).items() if k in SRV_COLS}
                    obj["created_at"] = _parse_dt(obj.get("created_at"))
                    obj["updated_at"] = _parse_dt(obj.get("updated_at"))
                    if db.get(Server, obj.get("id")) is not None:
                        continue  # never overwrite live server config
                    db.add(Server(**obj))
                    db.commit()
                    servers_added += 1

            # 2) metrics
            for member in members:
                if not member.name.startswith("server_metrics_"):
                    continue
                fh = tf.extractfile(member)
                if fh is None:
                    continue
                batch = []
                for line in fh:
                    if not line.strip():
                        continue
                    obj = json.loads(line)
                    obj = {k: v for k, v in obj.items() if k in COLS}
                    obj["collected_at"] = _parse_dt(obj.get("collected_at"))
                    obj.pop("id", None)
                    dup = (
                        db.query(ServerMetric.id)
                        .filter(ServerMetric.server_id == obj.get("server_id"),
                                ServerMetric.collected_at == obj.get("collected_at"))
                        .first()
                    )
                    if dup:
                        skipped += 1
                        continue
                    batch.append(ServerMetric(**obj))
                    if len(batch) >= 300:
                        db.bulk_save_objects(batch)
                        db.commit()
                        restored += len(batch)
                        batch = []
                if batch:
                    db.bulk_save_objects(batch)
                    db.commit()
                    restored += len(batch)
        print(f"restore done: {restored} metrics restored, {skipped} duplicates skipped, "
              f"{servers_added} servers re-created <- {path}")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])
