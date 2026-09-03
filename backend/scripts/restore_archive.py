"""Restore archived server_metrics from a daily tar.gz JSONL archive.

Usage (from backend/):
    python3 scripts/restore_archive.py /path/server_metrics_*.tar.gz.enc

Idempotent: servers already present are kept as-is; metric rows with an
existing (server_id, collected_at) are skipped.
"""

import argparse
from contextlib import ExitStack
import json
import os
import re
import sys
import tarfile
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.database import SessionLocal  # noqa: E402
from app.models import Server, ServerMetric  # noqa: E402
from app.archive_crypto import decrypt_fileobj  # noqa: E402
from app.config import get_settings  # noqa: E402

COLS = {c.key for c in ServerMetric.__table__.columns}
MAX_ARCHIVE_BYTES = 25 * 1024 * 1024 * 1024
MAX_METRICS_BYTES = 20 * 1024 * 1024 * 1024
MAX_SERVERS_BYTES = 256 * 1024 * 1024
MAX_JSONL_LINE_BYTES = 8 * 1024 * 1024
_METRICS_NAME = re.compile(r"^server_metrics_(\d{4}-\d{2}-\d{2}_\d{6})\.jsonl$")
_SERVERS_NAME = re.compile(r"^servers_(\d{4}-\d{2}-\d{2}_\d{6})\.jsonl$")


def _parse_dt(v):
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return v
    return v


def _safe_members(tf: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members: list[tarfile.TarInfo] = []
    stamps: dict[str, str] = {}
    for member in tf:
        if len(members) >= 2:
            raise ValueError("archive contains too many members")
        if not member.isfile() or "/" in member.name or "\\" in member.name:
            raise ValueError(f"unsafe archive member: {member.name}")
        metric_match = _METRICS_NAME.fullmatch(member.name)
        server_match = _SERVERS_NAME.fullmatch(member.name)
        if metric_match:
            if "metrics" in stamps or member.size > MAX_METRICS_BYTES:
                raise ValueError(f"invalid metrics member: {member.name}")
            stamps["metrics"] = metric_match.group(1)
        elif server_match:
            if "servers" in stamps or member.size > MAX_SERVERS_BYTES:
                raise ValueError(f"invalid servers member: {member.name}")
            stamps["servers"] = server_match.group(1)
        else:
            raise ValueError(f"unexpected archive member: {member.name}")
        members.append(member)
    if "metrics" not in stamps:
        raise ValueError("archive has no metrics member")
    if "servers" in stamps and stamps["servers"] != stamps["metrics"]:
        raise ValueError("archive member timestamps do not match")
    return members


def _bounded_lines(fh):
    while True:
        line = fh.readline(MAX_JSONL_LINE_BYTES + 1)
        if not line:
            return
        if len(line) > MAX_JSONL_LINE_BYTES:
            raise ValueError("archive JSONL record exceeds the safety limit")
        yield line


def main(path: str, create_disabled_servers: bool, allow_legacy_unencrypted: bool) -> None:
    db = SessionLocal()
    restored = skipped = servers_added = 0
    try:
        if os.path.getsize(path) > MAX_ARCHIVE_BYTES:
            raise ValueError("archive exceeds the encrypted/compressed size limit")
        with ExitStack() as stack:
            if path.endswith(".enc"):
                # TemporaryFile is anonymous/unlinked: a killed restore cannot
                # leave a named plaintext tarball in /tmp.
                decrypted = stack.enter_context(tempfile.TemporaryFile(mode="w+b"))
                os.fchmod(decrypted.fileno(), 0o600)
                decrypt_fileobj(path, decrypted, get_settings().ARCHIVE_ENCRYPTION_KEY)
                decrypted.seek(0)
                tf = stack.enter_context(tarfile.open(fileobj=decrypted, mode="r:gz"))
            else:
                if not allow_legacy_unencrypted:
                    raise ValueError("unencrypted legacy archive requires --allow-legacy-unencrypted")
                tf = stack.enter_context(tarfile.open(path, "r:gz"))
            members = list(_safe_members(tf))

            # 1) servers first - they are the FK targets for metrics
            for member in members:
                if not member.name.startswith("servers_"):
                    continue
                if not create_disabled_servers:
                    continue
                fh = tf.extractfile(member)
                if fh is None:
                    continue
                for line in _bounded_lines(fh):
                    if not line.strip():
                        continue
                    source = json.loads(line)
                    server_id = source.get("id")
                    if db.get(Server, server_id) is not None:
                        continue  # never overwrite live server config
                    db.add(Server(
                        id=server_id,
                        name=str(source.get("name") or f"restored-{server_id}")[:128],
                        host="",
                        port=22,
                        auth_type="key",
                        username="gpumon",
                        password="",
                        private_key="",
                        passphrase="",
                        bmc_host="",
                        bmc_user="",
                        bmc_password="",
                        enabled=False,
                        server_type=source.get("server_type") if source.get("server_type") in {"gpu", "cpu"} else "gpu",
                        tags=source.get("tags") if isinstance(source.get("tags"), list) else [],
                        note="Restored metadata; configure and review before enabling",
                    ))
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
                for line in _bounded_lines(fh):
                    if not line.strip():
                        continue
                    obj = json.loads(line)
                    obj = {k: v for k, v in obj.items() if k in COLS}
                    obj["collected_at"] = _parse_dt(obj.get("collected_at"))
                    obj.pop("id", None)
                    if db.get(Server, obj.get("server_id")) is None:
                        skipped += 1
                        continue
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive")
    parser.add_argument(
        "--create-disabled-servers",
        action="store_true",
        help="create missing servers as disabled placeholders without credentials",
    )
    parser.add_argument(
        "--allow-legacy-unencrypted",
        action="store_true",
        help="allow an old plaintext .tar.gz archive",
    )
    args = parser.parse_args()
    main(args.archive, args.create_disabled_servers, args.allow_legacy_unencrypted)
