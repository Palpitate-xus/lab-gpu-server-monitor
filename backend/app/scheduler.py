"""Background scheduler: tiered polling (fast / slow / inventory / kernel),
metric storage, built-in health detectors, user alert rules, retention.

Tiers:
  fast      every poll interval (default 30-60s) — cpu/mem/disk/net/gpu
  kernel    every poll — incremental XID/OOM/MCE event scan (dedup by boot_id+hash)
  slow      every ~5 min — nvme/raid/nfs/systemd/mig/nvlink/ipmi
  inventory every ~24h — machine-id/dmi/lscpu/numa/topo/ib
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import load_only

from .config import get_settings
from .database import SessionLocal
from .models import (
    AlertEvent,
    AlertRule,
    HostInventory,
    IpmiSnapshot,
    KernelEventRow,
    Server,
    ServerMetric,
    Setting,
    SlowHealth,
)
from . import notifier
from .health import run_detectors, update_gpu_baseline
from .ssh_collector import collect
from .collectors_extra import collect_inventory, collect_slow

settings = get_settings()
logger = logging.getLogger("gpumon.scheduler")

SLOW_INTERVAL = 300      # 5 min
# hard ceiling for one full poll cycle (all joins combined)
CYCLE_JOIN_TIMEOUT = 180
INVENTORY_INTERVAL = 86400  # 24h

_state = {
    "running": False,
    "thread": None,
    "last_run": None,
    "last_duration": 0.0,
    "interval": settings.POLL_INTERVAL_SECONDS,
    "heartbeat_monotonic": None,
    "lock": threading.Lock(),
    "last_retention_day": "",
}

_stop_event = threading.Event()

# one in-flight poll per server; overlapping cycles must not stack SSH storms
_server_busy: set[tuple[int, str]] = set()
_busy_guard = threading.Lock()

_cycle_lock = threading.Lock()


def _touch_scheduler_heartbeat() -> None:
    with _state["lock"]:
        _state["heartbeat_monotonic"] = time.monotonic()


def _server_begin(server_id: int, tier: str) -> bool:
    key = (server_id, tier)
    with _busy_guard:
        if key in _server_busy:
            return False
        _server_busy.add(key)
        return True


def _server_end(server_id: int, tier: str) -> None:
    with _busy_guard:
        _server_busy.discard((server_id, tier))

METRIC_LABELS = {
    "cpu_percent": "CPU 使用率",
    "mem_percent": "内存使用率",
    "gpu_util": "GPU 利用率",
    "gpu_temp": "GPU 温度",
    "gpu_mem_percent": "GPU 显存",
    "gpu_power": "GPU 功耗",
    "disk_percent": "磁盘使用率",
    "load_per_core": "每核负载",
    "swap_percent": "Swap 使用率",
}

_ALERT_METRIC_COLS = (
    ServerMetric.server_id,
    ServerMetric.collected_at,
    ServerMetric.hostname,
    ServerMetric.status,
    ServerMetric.cpu_percent,
    ServerMetric.mem_total_mb,
    ServerMetric.mem_used_mb,
    ServerMetric.swap_total_mb,
    ServerMetric.swap_used_mb,
    ServerMetric.disks,
    ServerMetric.load1,
    ServerMetric.cpu_count,
    ServerMetric.gpus,
)


def _extract_metric(m: ServerMetric, metric: str) -> Optional[float]:
    """Extract a comparable scalar from a metric row; None = not available."""
    if metric == "cpu_percent":
        return m.cpu_percent
    if metric == "mem_percent":
        return (m.mem_used_mb / m.mem_total_mb * 100) if m.mem_total_mb else None
    if metric == "swap_percent":
        return (m.swap_used_mb / m.swap_total_mb * 100) if m.swap_total_mb else None
    if metric == "disk_percent":
        # max mount percent
        pcts = [d.get("percent", 0) for d in (m.disks or [])]
        return max(pcts) if pcts else None
    if metric == "load_per_core":
        return (m.load1 / m.cpu_count) if m.cpu_count else None
    if metric in ("gpu_util", "gpu_temp", "gpu_mem_percent", "gpu_power"):
        gpus = m.gpus or []
        if not gpus:
            return None
        vals = []
        for g in gpus:
            if metric == "gpu_util":
                vals.append(g.get("utilization", 0) or 0)
            elif metric == "gpu_temp":
                vals.append(g.get("temperature", 0) or 0)
            elif metric == "gpu_power":
                vals.append(g.get("power_draw", 0) or 0)
            else:  # gpu_mem_percent
                total = g.get("mem_total_mb", 0) or 0
                used = g.get("mem_used_mb", 0) or 0
                if total > 0:
                    vals.append(used / total * 100)
        # for temps/power/mem we alert on the max (worst GPU); util on avg
        if not vals:
            return None
        if metric == "gpu_util":
            return sum(vals) / len(vals)
        return max(vals)
    return None


def _compare(value: float, op: str, threshold: float) -> bool:
    if op == ">":
        return value > threshold
    if op == ">=":
        return value >= threshold
    if op == "<":
        return value < threshold
    if op == "<=":
        return value <= threshold
    return False


def _eval_alerts() -> None:
    """Evaluate all enabled rules against latest metrics; open/recover events."""
    db = SessionLocal()
    try:
        rules = db.query(AlertRule).filter(AlertRule.enabled.is_(True)).all()
        if not rules:
            return
        servers = db.query(Server).filter(Server.enabled.is_(True)).all()
        latest_by_server: dict[int, ServerMetric] = {}
        for s in servers:
            m = (
                db.query(ServerMetric)
                .options(load_only(*_ALERT_METRIC_COLS))
                .filter(ServerMetric.server_id == s.id, ServerMetric.status == "ok")
                .order_by(ServerMetric.collected_at.desc())
                .first()
            )
            if m is not None:
                latest_by_server[s.id] = m

        interval = _load_interval()
        maintenance_ids = {s.id for s in servers if (s.status or "active") == "maintenance"}
        for rule in rules:
            target_ids = (
                [rule.server_id] if rule.server_id else list(latest_by_server.keys())
            )
            for sid in target_ids:
                if sid in maintenance_ids:
                    continue
                m = latest_by_server.get(sid)
                if m is None:
                    continue
                value = _extract_metric(m, rule.metric)
                if value is None:
                    continue
                breached = _compare(value, rule.op, rule.threshold)

                open_event = (
                    db.query(AlertEvent)
                    .filter(
                        AlertEvent.rule_id == rule.id,
                        AlertEvent.server_id == sid,
                        AlertEvent.recovered_at.is_(None),
                    )
                    .first()
                )

                if open_event is not None and open_event.acked_at is not None:
                    # acknowledged and still breached: stay open, do not re-fire
                    continue

                if breached and open_event is None:
                    if rule.duration_minutes > 0:
                        # require the breach to hold for duration across recent samples
                        since = m.collected_at - timedelta(minutes=rule.duration_minutes)
                        rows = (
                            db.query(ServerMetric)
                            .options(load_only(*_ALERT_METRIC_COLS))
                            .filter(
                                ServerMetric.server_id == sid,
                                ServerMetric.collected_at >= since,
                                ServerMetric.status == "ok",
                            )
                            .order_by(ServerMetric.collected_at.asc())
                            .all()
                        )
                        # 0.0 is a valid sample: filter on None only
                        vals = [
                            v for v in (_extract_metric(r, rule.metric) for r in rows)
                            if v is not None
                        ]
                        # sparse window (restart/new rule) must not fire instantly
                        expected = max(1, rule.duration_minutes * 60 // max(10, interval))
                        if len(vals) < max(2, expected // 2):
                            continue
                        if not all(_compare(v, rule.op, rule.threshold) for v in vals):
                            continue
                    ev = AlertEvent(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        server_id=sid,
                        server_name=m.hostname or str(sid),
                        metric=rule.metric,
                        value=round(value, 1),
                        threshold=rule.threshold,
                        message=f"{METRIC_LABELS.get(rule.metric, rule.metric)} {round(value,1)} {rule.op} {rule.threshold}",
                    )
                    db.add(ev)
                    db.commit()
                    ok, msg = notifier.notify_alert(
                        m.hostname or str(sid), rule.metric, value, rule.op, rule.threshold, rule.name
                    )
                    if ok:
                        ev.notified = True
                        db.commit()
                        logger.info("alert notified: %s %s", ev.message, msg)
                elif not breached and open_event is not None:
                    open_event.recovered_at = datetime.now(timezone.utc)
                    db.commit()
                    notifier.notify_recovery(
                        open_event.server_name, open_event.metric, open_event.rule_name or rule.name
                    )
    except Exception:
        logger.exception("alert evaluation failed")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# GPU idle-held (空占) state: persists idle_since per GPU so the analysis
# page can report exact, unbounded idle durations without window scanning.
# ---------------------------------------------------------------------------

IDLE_STATE_KEY = "gpu_idle_state"
_gpu_idle_mem: dict[str, str] | None = None
_idle_lock = threading.Lock()


def _gpu_is_idle_held(g: dict) -> bool:
    total = g.get("mem_total_mb") or 0
    return bool(
        (g.get("utilization", 0) or 0) < 5
        and total
        and (g.get("mem_used_mb", 0) or 0) / total * 100 >= 30
    )


def _load_idle_state(db) -> dict[str, str]:
    global _gpu_idle_mem
    with _idle_lock:
        if _gpu_idle_mem is not None:
            return _gpu_idle_mem
    row = db.get(Setting, IDLE_STATE_KEY)
    try:
        import json

        state = json.loads(row.value) if row and row.value else {}
    except Exception:
        state = {}
    with _idle_lock:
        _gpu_idle_mem = state
    return state


def _save_idle_state(db, state: dict[str, str]) -> None:
    import json

    global _gpu_idle_mem
    row = db.get(Setting, IDLE_STATE_KEY)
    if row:
        row.value = json.dumps(state)
    else:
        db.add(Setting(key=IDLE_STATE_KEY, value=json.dumps(state)))
    db.commit()
    with _idle_lock:
        _gpu_idle_mem = state


def _backfill_idle_start(db, server_id: int, uuid: str, before: datetime):
    """Walk history backwards to find where the current idle run began."""
    start = None
    cursor = before
    while True:
        rows = (
            db.query(ServerMetric)
            .options(load_only(ServerMetric.collected_at, ServerMetric.gpus))
            .filter(
                ServerMetric.server_id == server_id,
                ServerMetric.collected_at < cursor,
                ServerMetric.status == "ok",
            )
            .order_by(ServerMetric.collected_at.desc())
            .limit(2000)
            .all()
        )
        if not rows:
            break
        for m in rows:
            g = next((x for x in (m.gpus or []) if x.get("uuid") == uuid), None)
            if g and _gpu_is_idle_held(g):
                start = m.collected_at
            else:
                return start
        cursor = rows[-1].collected_at
        if len(rows) < 2000:
            break
    return start


def update_gpu_idle_state(server_id: int, collected_at: datetime, gpus: list) -> None:
    """Maintain idle_since per GPU; called on every successful poll."""
    db = SessionLocal()
    try:
        state = dict(_load_idle_state(db))
        changed = False
        seen = set()
        for g in gpus or []:
            u = g.get("uuid")
            if not u:
                continue
            key = f"{server_id}:{u}"
            seen.add(key)
            if _gpu_is_idle_held(g):
                if key not in state:
                    start = _backfill_idle_start(db, server_id, u, collected_at) or collected_at
                    if start.tzinfo is None:
                        start = start.replace(tzinfo=timezone.utc)
                    state[key] = start.isoformat()
                    changed = True
            elif key in state:
                del state[key]
                changed = True
        for key in [k for k in state if k.startswith(f"{server_id}:") and k not in seen]:
            del state[key]
            changed = True
        if changed:
            _save_idle_state(db, state)
    except Exception:
        logger.exception("idle-state update failed for server %s", server_id)
    finally:
        db.close()


def _archive_expired_metrics(cutoff: datetime) -> int | None:
    """Export every server_metrics row older than cutoff to a tar.gz JSONL
    archive in ARCHIVE_DIR. Returns the greatest archived row ID (zero when
    there was nothing to archive). Any failure or an unset ARCHIVE_DIR returns
    None, so retention skips deletion. The caller deletes only IDs at or below
    the returned boundary, preventing a concurrently inserted old row from
    being deleted without appearing in the archive."""
    import json
    import os
    import tarfile
    import tempfile

    from sqlalchemy import func as sa_func

    archive_dir = get_settings().ARCHIVE_DIR.strip()
    db = SessionLocal()
    temporary_paths: list[str] = []
    try:
        max_id = (
            db.query(sa_func.max(ServerMetric.id))
            .filter(ServerMetric.collected_at < cutoff)
            .scalar()
        )
        if max_id is None:
            return 0
        n = (
            db.query(sa_func.count(ServerMetric.id))
            .filter(ServerMetric.collected_at < cutoff, ServerMetric.id <= max_id)
            .scalar()
        )
        if not archive_dir:
            logger.warning(
                "retention wants to delete %d expired metrics but ARCHIVE_DIR "
                "is not set; refusing to delete", n)
            return None
        from .archive_crypto import ensure_archive_storage

        ensure_archive_storage(archive_dir)

        now = datetime.now(timezone.utc)
        stamp = now.strftime("%Y-%m-%d_%H%M%S")
        jsonl_name = f"server_metrics_{stamp}.jsonl"
        servers_name = f"servers_{stamp}.jsonl"
        written = 0
        # Anonymous temporary files have no persistent pathname to recover
        # after SIGKILL/power loss. Plain JSONL/tar data is never published in
        # ARCHIVE_DIR; only the authenticated encrypted result is named.
        with (
            tempfile.TemporaryFile(mode="w+b", dir=archive_dir) as metrics_tmp,
            tempfile.TemporaryFile(mode="w+b", dir=archive_dir) as servers_tmp,
            tempfile.TemporaryFile(mode="w+b", dir=archive_dir) as tar_tmp,
        ):
            os.fchmod(metrics_tmp.fileno(), 0o600)
            os.fchmod(servers_tmp.fileno(), 0o600)
            os.fchmod(tar_tmp.fileno(), 0o600)
            from .privacy import minimize_metric

            q = (
                db.query(ServerMetric)
                .filter(ServerMetric.collected_at < cutoff, ServerMetric.id <= max_id)
                .order_by(ServerMetric.id.asc())
            )
            for m in q.yield_per(300):
                metrics_tmp.write(
                    (
                        json.dumps(minimize_metric(m), default=str) + "\n"
                    ).encode("utf-8")
                )
                written += 1
            if written != n:
                raise RuntimeError(
                    f"archive row count changed: expected {n}, serialized {written}"
                )

            # Server metadata restores only missing FK targets, disabled and
            # without addresses or credentials.
            for s in db.query(Server).order_by(Server.id.asc()):
                servers_tmp.write(
                    (
                        json.dumps(
                            {
                                "id": s.id,
                                "name": s.name,
                                "server_type": s.server_type,
                                "tags": s.tags or [],
                            },
                            default=str,
                        )
                        + "\n"
                    ).encode("utf-8")
                )

            metrics_size = metrics_tmp.tell()
            servers_size = servers_tmp.tell()
            metrics_tmp.seek(0)
            servers_tmp.seek(0)
            with tarfile.open(fileobj=tar_tmp, mode="w:gz") as tf:
                for name, source, size in (
                    (jsonl_name, metrics_tmp, metrics_size),
                    (servers_name, servers_tmp, servers_size),
                ):
                    info = tarfile.TarInfo(name=name)
                    info.size = size
                    info.mode = 0o600
                    info.mtime = int(now.timestamp())
                    tf.addfile(info, source)
            tar_tmp.flush()
            tar_tmp.seek(0)

            from .archive_crypto import encrypt_fileobj

            final_path = os.path.join(archive_dir, f"server_metrics_{stamp}.tar.gz.enc")
            encrypted_part = final_path + ".part"
            temporary_paths.append(encrypted_part)
            encrypt_fileobj(
                tar_tmp,
                encrypted_part,
                get_settings().ARCHIVE_ENCRYPTION_KEY,
            )
        # Publish without overwriting an archive from a same-second run.
        os.link(encrypted_part, final_path)
        os.unlink(encrypted_part)
        os.chmod(final_path, 0o600)
        directory_fd = os.open(archive_dir, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        logger.info("archived %d expired metrics -> %s", written, final_path)
        return max_id
    except Exception:
        logger.exception("metric archive failed; retention delete skipped")
        return None
    finally:
        db.close()
        for temporary_path in temporary_paths:
            try:
                os.remove(temporary_path)
            except FileNotFoundError:
                pass


def _retention_cleanup() -> None:
    """Delete metrics older than retention_days (0 = keep forever), in batches
    so MySQL does not take a giant lock and SQLite stays responsive. Rows are
    archived to ARCHIVE_DIR first; a failed archive blocks the delete."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _state["lock"]:
        if _state["last_retention_day"] == today:
            return
        _state["last_retention_day"] = today
    db = SessionLocal()
    try:
        row = db.get(Setting, "retention_days")
        days = 0
        if row and row.value:
            try:
                days = int(row.value)
            except ValueError:
                days = 0
        if days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            archived_through_id = _archive_expired_metrics(cutoff)
            if archived_through_id is None:
                return
            if archived_through_id == 0:
                return
            while True:
                ids = [
                    i for (i,) in db.query(ServerMetric.id)
                    .filter(
                        ServerMetric.collected_at < cutoff,
                        ServerMetric.id <= archived_through_id,
                    )
                    .limit(5000)
                    .all()
                ]
                if not ids:
                    break
                db.query(ServerMetric).filter(ServerMetric.id.in_(ids)).delete(
                    synchronize_session=False
                )
                db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _store_kernel_events(server_id: int, boot_id: str, events) -> None:
    """Dedup-insert kernel events; (server_id, dedup_hash) is unique."""
    if not events:
        return
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        for ev in events:
            h = hashlib.sha256(
                f"{boot_id}|{ev.event_type}|{ev.xid}|{ev.raw_message[:200]}".encode()
            ).hexdigest()[:40]
            exists = (
                db.query(KernelEventRow.id)
                .filter(KernelEventRow.server_id == server_id,
                        KernelEventRow.dedup_hash == h)
                .first()
            )
            if exists:
                continue
            db.add(KernelEventRow(
                server_id=server_id,
                collected_at=now,
                boot_id=boot_id,
                event_type=ev.event_type,
                severity=ev.severity,
                gpu_uuid=ev.gpu_uuid,
                xid=ev.xid,
                message=ev.message,
                raw_message=ev.raw_message,
                dedup_hash=h,
            ))
        db.commit()
    except Exception:
        logger.exception("kernel event store failed for server %s", server_id)
        db.rollback()
    finally:
        db.close()


def _poll_one(server: Server) -> None:
    if not _server_begin(server.id, "poll"):
        logger.info("server %s poll still in flight; skipping", server.id)
        return
    try:
        # SSH phase: no DB session held (collects run 30-120s on slow hosts)
        res = collect(
            host=server.host,
            port=server.port or 22,
            username=server.username,
            password_enc=server.password or "",
            private_key_enc=server.private_key or "",
            passphrase_enc=server.passphrase or "",
            server_key=f"server_{server.id}",
        )
    except Exception:
        logger.exception("poll server %s failed", server.id)
        return
    finally:
        _server_end(server.id, "poll")

    if res.ok and getattr(res, "kernel_log", ""):
        from .collectors_extra import parse_kernel_log
        _store_kernel_events(
            server.id, res.boot_id, parse_kernel_log(res.kernel_log, res.boot_id)
        )

    db = SessionLocal()
    try:
        m = ServerMetric(
            server_id=server.id,
            collected_at=datetime.now(timezone.utc),
            hostname=res.hostname,
            os=res.os,
            kernel=res.kernel,
            uptime_seconds=res.uptime_seconds,
            boot_id=res.boot_id,
            cpu_model=res.cpu_model,
            cpu_count=res.cpu_count,
            cpu_percent=res.cpu_percent,
            cpu_iowait=res.cpu_iowait,
            cpu_freq_avg=res.cpu_freq_avg,
            cpu_temp_package=res.cpu_temp_package,
            cores=res.cores,
            load1=res.load1,
            load5=res.load5,
            load15=res.load15,
            mem_total_mb=res.mem_total_mb,
            mem_used_mb=res.mem_used_mb,
            mem_available_mb=res.mem_available_mb,
            mem_cached_mb=res.mem_cached_mb,
            swap_total_mb=res.swap_total_mb,
            swap_used_mb=res.swap_used_mb,
            disk_total_gb=sum(d["total_gb"] for d in res.disks),
            disk_used_gb=sum(d["used_gb"] for d in res.disks),
            disks=res.disks,
            inodes=res.inodes,
            disk_io=res.disk_io,
            net_rx_bytes=sum(i.get("rx_bps", 0) for i in res.net_ifaces),
            net_tx_bytes=sum(i.get("tx_bps", 0) for i in res.net_ifaces),
            net_ifaces=res.net_ifaces,
            users=res.users,
            sock_estab=res.sock_estab,
            sock_timewait=res.sock_timewait,
            fd_allocated=res.fd_allocated,
            fd_max=res.fd_max,
            gpu_count=len(res.gpus),
            gpu_driver=res.gpu_driver,
            gpus=res.gpus,
            processes=res.processes,
            duration=res.duration,
            ssh_latency=res.ssh_latency,
            status="ok" if res.ok else "error",
            error_code=res.error_code,
            error=res.error,
        )
        db.add(m)
        db.commit()
        if res.ok:
            update_gpu_baseline(server.id, res.gpus)
            update_gpu_idle_state(server.id, m.collected_at, res.gpus)
        # built-in detectors run for both ok and error results
        run_detectors(server.id)
    except Exception:
        logger.exception("poll server %s store failed", server.id)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def _slow_one(server: Server) -> None:
    if not _server_begin(server.id, "slow"):
        return
    try:
        r = collect_slow(
            host=server.host,
            port=server.port or 22,
            username=server.username,
            password_enc=server.password or "",
            private_key_enc=server.private_key or "",
            passphrase_enc=server.passphrase or "",
            server_key=f"server_{server.id}",
        )
    except Exception:
        logger.exception("slow collect server %s failed", server.id)
        return
    finally:
        _server_end(server.id, "slow")
    if not r.ok:
        return
    db = SessionLocal()
    try:
        db.add(SlowHealth(
            server_id=server.id,
            collected_at=datetime.now(timezone.utc),
            nvme_smart=r.nvme_smart,
            mdraid=r.mdraid,
            nfs_mounts=r.nfs_mounts,
            systemd_failed=r.systemd_failed,
            services=r.services,
            mig=r.mig,
            nvlink=r.nvlink,
            ipmi=r.ipmi,
            duration=r.duration,
        ))
        db.commit()
    except Exception:
        logger.exception("slow store server %s failed", server.id)
        db.rollback()
    finally:
        db.close()


def _inventory_one(server: Server) -> None:
    if not _server_begin(server.id, "inventory"):
        return
    try:
        r = collect_inventory(
            host=server.host,
            port=server.port or 22,
            username=server.username,
            password_enc=server.password or "",
            private_key_enc=server.private_key or "",
            passphrase_enc=server.passphrase or "",
            server_key=f"server_{server.id}",
        )
    except Exception:
        logger.exception("inventory collect server %s failed", server.id)
        return
    finally:
        _server_end(server.id, "inventory")
    if not r.ok:
        return
    db = SessionLocal()
    try:
        # keep one inventory row per server per day (replace today's)
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        db.query(HostInventory).filter(
            HostInventory.server_id == server.id,
            HostInventory.collected_at >= day_start,
        ).delete()
        db.add(HostInventory(
            server_id=server.id,
            collected_at=now,
            machine_id=r.machine_id,
            dmi=r.dmi,
            lscpu=r.lscpu,
            numa=r.numa,
            gpu_topology=r.gpu_topology,
            pci_numa=r.pci_numa,
            disks=r.disks,
            nics=r.nics,
            ip_addrs=r.ip_addrs,
            ib=r.ib,
            time_info=r.time_info,
            gpu_baseline=[],
        ))
        db.commit()
    except Exception:
        logger.exception("inventory store server %s failed", server.id)
        db.rollback()
    finally:
        db.close()


def _load_servers() -> list[Server]:
    db = SessionLocal()
    try:
        servers = db.query(Server).filter(Server.enabled.is_(True)).all()
        for s in servers:
            db.expunge(s)
        return servers
    finally:
        db.close()


def _run_cycle() -> None:
    servers = _load_servers()
    if not servers:
        return
    now_n = _utcnow_naive()
    last_slow = _last_collect_time(SlowHealth)
    last_inv = _last_collect_time(HostInventory)
    do_slow = (now_n - last_slow).total_seconds() >= SLOW_INTERVAL if last_slow else True
    do_inv = (now_n - last_inv).total_seconds() >= INVENTORY_INTERVAL if last_inv else True

    threads = []
    for server in servers:
        threads.append(threading.Thread(target=_poll_one, args=(server,), daemon=True))
        if do_slow:
            threads.append(threading.Thread(target=_slow_one, args=(server,), daemon=True))
        if do_inv:
            threads.append(threading.Thread(target=_inventory_one, args=(server,), daemon=True))
    cycle_start = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=CYCLE_JOIN_TIMEOUT)
    # alert evaluation must never see a half-finished cycle
    _eval_alerts()
    slowest = [t for t in threads if t.is_alive()]
    if slowest:
        logger.warning(
            "cycle finished with %d/%d threads still running after %ss "
            "(unreachable hosts); alerts evaluated on available data",
            len(slowest), len(threads), CYCLE_JOIN_TIMEOUT,
        )
    logger.info("collect cycle done: %d servers, %d tasks, %.1fs",
                len(servers), len(threads), time.monotonic() - cycle_start)


def _last_collect_time(model) -> Optional[datetime]:
    """Max collected_at across servers. MySQL DATETIME comes back naive (UTC
    wall clock), so normalize both sides to naive-UTC before comparing."""
    from sqlalchemy import func
    db = SessionLocal()
    try:
        row = db.query(func.max(model.collected_at)).scalar()
        if row is None:
            return None
        if row.tzinfo is not None:
            row = row.astimezone(timezone.utc).replace(tzinfo=None)
        return row
    finally:
        db.close()


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _load_interval() -> int:
    db = SessionLocal()
    try:
        row = db.get(Setting, "poll_interval")
        if row and row.value:
            try:
                v = int(row.value)
                if v >= 10:
                    return v
            except ValueError:
                pass
    finally:
        db.close()
    return settings.POLL_INTERVAL_SECONDS


def _expire_maintenance() -> None:
    """Maintenance windows with an expiry roll back to active automatically."""
    from .models import ServerNote

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        rows = (
            db.query(Server)
            .filter(Server.status == "maintenance",
                    Server.status_until.isnot(None),
                    Server.status_until <= now)
            .all()
        )
        for s in rows:
            s.status = "active"
            s.status_reason = ""
            s.status_until = None
            db.add(ServerNote(server_id=s.id, username="system", kind="note",
                              content="维护窗口到期，自动恢复为 active"))
        if rows:
            db.commit()
            logger.info("maintenance expired for %s", ", ".join(s.name for s in rows))
    except Exception:
        db.rollback()
    finally:
        db.close()


def _hourly_aggregate() -> None:
    """Roll the previous completed hour into server_metrics_hourly (idempotent)."""
    from .models import ServerMetricHourly

    now = datetime.now(timezone.utc)
    hour_end = now.replace(minute=0, second=0, microsecond=0)
    hour_start = hour_end - timedelta(hours=1)
    db = SessionLocal()
    try:
        servers = db.query(Server.id).filter(Server.enabled.is_(True)).all()
        for (sid,) in servers:
            existing = (
                db.query(ServerMetricHourly)
                .filter(ServerMetricHourly.server_id == sid,
                        ServerMetricHourly.hour == hour_start)
                .first()
            )
            rows = (
                db.query(ServerMetric)
                .options(load_only(
                    ServerMetric.status, ServerMetric.cpu_percent,
                    ServerMetric.mem_used_mb, ServerMetric.mem_total_mb,
                    ServerMetric.gpus, ServerMetric.net_rx_bytes, ServerMetric.net_tx_bytes,
                ))
                .filter(ServerMetric.server_id == sid,
                        ServerMetric.collected_at >= hour_start,
                        ServerMetric.collected_at < hour_end)
                .all()
            )
            ok = [r for r in rows if r.status == "ok"]
            agg = ServerMetricHourly(
                server_id=sid, hour=hour_start, samples=len(rows), ok_samples=len(ok),
            )
            if ok:
                cpus = [r.cpu_percent or 0 for r in ok]
                agg.cpu_avg = round(sum(cpus) / len(cpus), 1)
                agg.cpu_max = round(max(cpus), 1)
                mems = [r.mem_used_mb / r.mem_total_mb * 100 for r in ok if r.mem_total_mb]
                agg.mem_avg_pct = round(sum(mems) / len(mems), 1) if mems else 0
                utils, mem_pcts, powers = [], [], []
                idle_samples = 0
                for r in ok:
                    for g in (r.gpus or []):
                        u = g.get("utilization", 0) or 0
                        utils.append(u)
                        tot, used = g.get("mem_total_mb", 0) or 0, g.get("mem_used_mb", 0) or 0
                        if tot > 0:
                            mem_pcts.append(used / tot * 100)
                            if used / tot >= 0.30 and u <= 5:
                                idle_samples += 1
                        p = g.get("power_draw", 0) or 0
                        if p:
                            powers.append(p)
                agg.gpu_util_avg = round(sum(utils) / len(utils), 1) if utils else 0
                agg.gpu_util_max = round(max(utils), 1) if utils else 0
                agg.gpu_mem_pct_avg = round(sum(mem_pcts) / len(mem_pcts), 1) if mem_pcts else 0
                agg.gpu_power_avg = round(sum(powers) / len(powers), 1) if powers else 0
                agg.net_rx_avg_bps = round(sum(r.net_rx_bytes or 0 for r in ok) / len(ok), 1)
                agg.net_tx_avg_bps = round(sum(r.net_tx_bytes or 0 for r in ok) / len(ok), 1)
                # approximate minutes of idle-but-held GPU samples
                interval = _load_interval()
                agg.idle_held_minutes = int(idle_samples * interval / 60)
            if existing is not None:
                db.delete(existing)
                db.flush()
            db.add(agg)
            db.commit()
    except Exception:
        logger.exception("hourly aggregate failed")
        db.rollback()
    finally:
        db.close()


def _scheduler_loop() -> None:
    logger.info("scheduler started")
    last_hourly_day_hour = ""
    while not _stop_event.is_set():
        _touch_scheduler_heartbeat()
        started = datetime.now(timezone.utc)
        try:
            _expire_maintenance()
            _touch_scheduler_heartbeat()
            _run_cycle_guarded()
            _touch_scheduler_heartbeat()
            _retention_cleanup()
            _touch_scheduler_heartbeat()
            hh = started.strftime("%Y-%m-%d %H")
            if hh != last_hourly_day_hour and started.minute >= 2:
                # roll up the previous hour once, shortly after it completes
                last_hourly_day_hour = hh
                _hourly_aggregate()
                _touch_scheduler_heartbeat()
        except Exception:
            logger.exception("poll cycle failed")
        finished = datetime.now(timezone.utc)
        with _state["lock"]:
            _state["last_run"] = finished.isoformat()
            _state["last_duration"] = (finished - started).total_seconds()
            _state["interval"] = _load_interval()
            interval = _state["interval"]
        _stop_event.wait(interval)
    logger.info("scheduler stopped")


def start_scheduler() -> None:
    with _state["lock"]:
        if _state["running"]:
            return
        _state["running"] = True
    _stop_event.clear()
    t = threading.Thread(target=_scheduler_loop, name="gpumon-scheduler", daemon=True)
    t.start()
    _state["thread"] = t
    start_cache_warmer()
    _start_ipmi_loop()


# ---------------------------------------------------------------------------
# Cache warmer: rebuilds hot endpoint payloads in the background just before
# they expire, so interactive requests never pay the cold-build cost.
# ---------------------------------------------------------------------------

_warmer_started = False


def start_cache_warmer() -> None:
    global _warmer_started
    if _warmer_started:
        return
    _warmer_started = True
    threading.Thread(target=_cache_warm_loop, name="gpumon-cache-warmer", daemon=True).start()


def _cache_warm_loop() -> None:
    while not _stop_event.is_set():
        try:
            _warm_hot_keys()
        except Exception:
            logger.exception("cache warm cycle failed")
        _stop_event.wait(10)


def _warm_hot_keys() -> None:
    from concurrent.futures import ThreadPoolExecutor

    from . import cache as app_cache
    from .api import cockpit as ck
    from .api import enterprise as ent
    from .api import metrics as mt

    def _own_session(fn):
        def run():
            s = SessionLocal()
            try:
                return fn(s)
            finally:
                s.close()
        return run

    # cached() is a no-op while a payload is still fresh, so this idles
    # cheaply and only rebuilds what is about to expire; concurrent sessions
    # keep a slow rebuild from stalling the rest
    jobs = (
        ("metrics:dashboard", 15.0, _own_session(lambda s: mt._dashboard(s))),
        ("metrics:latest:slim", 10.0, _own_session(lambda s: mt._latest_payload(s, True))),
        ("cockpit:cluster-gpus", 15.0, _own_session(lambda s: ck._cluster_gpus(s))),
        ("cockpit:power-now", 15.0, _own_session(lambda s: ck._cluster_power_now(s))),
        ("cluster:health-summary", 15.0, _own_session(lambda s: ent._cluster_health_summary(s))),
        ("cockpit:history:6", 60.0, _own_session(lambda s: ck._cluster_history(s, 6))),
        ("cockpit:history:24", 60.0, _own_session(lambda s: ck._cluster_history(s, 24))),
        ("cockpit:energy:7", 300.0, _own_session(lambda s: ck._cluster_energy(s, 7))),
        ("cluster:gpu-analysis", 300.0, _own_session(lambda s: ent._gpu_analysis(s))),
    )
    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(lambda item: app_cache.cached(*item), jobs))


# ---------------------------------------------------------------------------
# Out-of-band IPMI tier: independent 5-minute loop, direct BMC connections
# from the monitor host (works even when the target OS is down).
# ---------------------------------------------------------------------------

_IPMI_INTERVAL = 300
_ipmi_started = False


def _start_ipmi_loop() -> None:
    global _ipmi_started
    if _ipmi_started:
        return
    _ipmi_started = True
    threading.Thread(target=_ipmi_loop, name="gpumon-ipmi", daemon=True).start()


def _ipmi_loop() -> None:
    while not _stop_event.is_set():
        _stop_event.wait(_IPMI_INTERVAL)
        if _stop_event.is_set():
            break
        try:
            _ipmi_cycle()
        except Exception:
            logger.exception("ipmi cycle failed")


def _ipmi_cycle() -> None:
    from concurrent.futures import ThreadPoolExecutor

    from .ipmi_collector import collect_ipmi, ipmitool_available
    from .security import decrypt_text

    if not ipmitool_available():
        logger.warning("ipmitool not installed on monitor host; IPMI tier disabled")
        return
    db = SessionLocal()
    try:
        servers = db.query(Server).filter(Server.enabled.is_(True)).all()
        targets = [
            (s.id, s.name, s.bmc_host, s.bmc_user, decrypt_text(s.bmc_password or ""))
            for s in servers if s.bmc_host
        ]
    finally:
        db.close()
    if not targets:
        return

    started = time.time()

    def one(t):
        sid, name, host, user, pwd = t
        try:
            res = collect_ipmi(host, user, pwd)
        except Exception as exc:  # collector itself should not raise
            res = {"ok": False, "error": str(exc)[:300], "mc_info": {}, "chassis": {},
                   "power": {}, "sensors": [], "sel": [], "sel_info": {},
                   "fru": [], "lan": {}, "duration": 0}
        _store_ipmi(sid, name, res)
        return bool(res.get("ok"))

    with ThreadPoolExecutor(max_workers=8) as ex:
        oks = list(ex.map(one, targets))
    logger.info("ipmi cycle done: %d/%d BMC reachable, %.1fs",
                sum(oks), len(targets), time.time() - started)


def _store_ipmi(server_id: int, server_name: str, res: dict) -> None:
    from . import health as health_mod
    from .ipmi_collector import summarize

    s = summarize(res)
    db = SessionLocal()
    try:
        db.add(IpmiSnapshot(
            server_id=server_id,
            collected_at=datetime.now(timezone.utc),
            ok=bool(res.get("ok")),
            error=res.get("error", ""),
            mc_info=res.get("mc_info", {}),
            chassis=res.get("chassis", {}),
            power=res.get("power", {}),
            sensors=res.get("sensors", []),
            sel=res.get("sel", []),
            sel_info=res.get("sel_info", {}),
            fru=res.get("fru", []),
            lan=res.get("lan", {}),
            power_w=float(s["power_w"]),
            duration=res.get("duration", 0),
        ))
        db.commit()

        if not res.get("ok"):
            health_mod._fire(db, "BMC_UNREACHABLE", server_id, server_name,
                             f"BMC 连接失败：{res.get('error', '')[:150]}")
            return
        health_mod._recover(db, "BMC_UNREACHABLE", server_id)

        if not s["power_on"]:
            health_mod._fire(db, "CHASSIS_POWER_OFF", server_id, server_name,
                             "BMC 报告机箱电源处于关闭状态")
        else:
            health_mod._recover(db, "CHASSIS_POWER_OFF", server_id)
        for psu in s["psu_bad"]:
            health_mod._fire(db, "PSU_FAULT", server_id, server_name,
                             f"电源传感器异常：{psu}", key=psu)
        for e in s["sel_critical"][-3:]:
            key = f"{e.get('record', '')}-{(e.get('event') or '')[:40]}"
            health_mod._fire(db, "SEL_CRITICAL", server_id, server_name,
                             (e.get("event") or "")[:200], key=key)
    except Exception:
        logger.exception("ipmi store/detectors failed for %s", server_name)
    finally:
        db.close()


def _run_cycle_guarded() -> None:
    if not _cycle_lock.acquire(blocking=False):
        logger.info("poll cycle already running; skipping")
        return
    try:
        _run_cycle()
    finally:
        _cycle_lock.release()


def trigger_poll() -> bool:
    """Manual refresh; returns False when a cycle is already in flight."""
    if _cycle_lock.locked():
        return False
    threading.Thread(target=_run_cycle_guarded, daemon=True).start()
    return True


def scheduler_status() -> dict:
    with _state["lock"]:
        thread = _state.get("thread")
        heartbeat = _state.get("heartbeat_monotonic")
        heartbeat_age = time.monotonic() - heartbeat if heartbeat is not None else None
        heartbeat_timeout = max(CYCLE_JOIN_TIMEOUT + 60, _state["interval"] * 3)
        alive = bool(thread and thread.is_alive())
        return {
            "running": _state["running"],
            "alive": alive,
            "healthy": bool(
                alive
                and heartbeat_age is not None
                and heartbeat_age <= heartbeat_timeout
            ),
            "heartbeat_age_seconds": (
                round(heartbeat_age, 2) if heartbeat_age is not None else None
            ),
            "interval": _state["interval"],
            "last_run": _state["last_run"],
            "last_duration": round(_state["last_duration"], 2),
        }
