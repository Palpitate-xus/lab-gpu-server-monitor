"""Background scheduler that polls every enabled server, stores metrics,
evaluates alert rules, and rolls up history. History is kept forever by default
(retention_days setting, 0 = keep everything)."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from .config import get_settings
from .database import SessionLocal
from .models import AlertEvent, AlertRule, Server, ServerMetric, Setting
from . import notifier
from .ssh_collector import collect

settings = get_settings()
logger = logging.getLogger("gpumon.scheduler")

_state = {
    "running": False,
    "thread": None,
    "last_run": None,
    "last_duration": 0.0,
    "interval": settings.POLL_INTERVAL_SECONDS,
    "lock": threading.Lock(),
}

_stop_event = threading.Event()

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
        servers = db.query(Server).all()
        latest_by_server: dict[int, ServerMetric] = {}
        for s in servers:
            m = (
                db.query(ServerMetric)
                .filter(ServerMetric.server_id == s.id, ServerMetric.status == "ok")
                .order_by(ServerMetric.collected_at.desc())
                .first()
            )
            if m is not None:
                latest_by_server[s.id] = m

        for rule in rules:
            target_ids = (
                [rule.server_id] if rule.server_id else list(latest_by_server.keys())
            )
            for sid in target_ids:
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

                if breached and open_event is None:
                    if rule.duration_minutes > 0:
                        # require the breach to hold for duration across recent samples
                        since = m.collected_at - timedelta(minutes=rule.duration_minutes)
                        rows = (
                            db.query(ServerMetric)
                            .filter(
                                ServerMetric.server_id == sid,
                                ServerMetric.collected_at >= since,
                            )
                            .order_by(ServerMetric.collected_at.asc())
                            .all()
                        )
                        if rows:
                            held = all(
                                _compare(v, rule.op, rule.threshold)
                                for v in filter(
                                    None, (_extract_metric(r, rule.metric) for r in rows)
                                )
                            )
                            if not held:
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


def _retention_cleanup() -> None:
    """Delete metrics older than retention_days (0 = keep forever)."""
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
            from sqlalchemy import delete

            stmt = delete(ServerMetric).where(ServerMetric.collected_at < cutoff)
            db.execute(stmt)
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _poll_one(server: Server) -> None:
    db = SessionLocal()
    try:
        res = collect(
            host=server.host,
            port=server.port or 22,
            username=server.username,
            password_enc=server.password or "",
            private_key_enc=server.private_key or "",
            passphrase_enc=server.passphrase or "",
        )
        m = ServerMetric(
            server_id=server.id,
            collected_at=datetime.now(timezone.utc),
            hostname=res.hostname,
            os=res.os,
            kernel=res.kernel,
            uptime_seconds=res.uptime_seconds,
            cpu_model=res.cpu_model,
            cpu_count=res.cpu_count,
            cpu_percent=res.cpu_percent,
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
            disk_io=res.disk_io,
            net_rx_bytes=sum(i.get("rx_bps", 0) for i in res.net_ifaces),
            net_tx_bytes=sum(i.get("tx_bps", 0) for i in res.net_ifaces),
            net_ifaces=res.net_ifaces,
            users=res.users,
            gpu_count=len(res.gpus),
            gpu_driver=res.gpu_driver,
            gpus=res.gpus,
            processes=res.processes,
            duration=res.duration,
            status="ok" if res.ok else "error",
            error=res.error,
        )
        db.add(m)
        db.commit()
    except Exception:
        logger.exception("poll server %s failed", server.id)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def _run_cycle() -> None:
    db = SessionLocal()
    ids: list[int] = []
    try:
        ids = [s.id for s in db.query(Server).filter(Server.enabled.is_(True)).all()]
    finally:
        db.close()
    if not ids:
        return

    threads = []
    for sid in ids:
        db = SessionLocal()
        try:
            server = db.get(Server, sid)
            if server is None:
                continue
            db.expunge(server)
        finally:
            db.close()
        t = threading.Thread(target=_poll_one, args=(server,), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=settings.SSH_CONNECT_TIMEOUT + settings.SSH_COMMAND_TIMEOUT + 5)
    _eval_alerts()


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


def _scheduler_loop() -> None:
    logger.info("scheduler started")
    while not _stop_event.is_set():
        started = datetime.now(timezone.utc)
        try:
            _run_cycle()
            _retention_cleanup()
        except Exception:
            logger.exception("poll cycle failed")
        finished = datetime.now(timezone.utc)
        with _state["lock"]:
            _state["last_run"] = finished.isoformat()
            _state["last_duration"] = (finished - started).total_seconds()
            _state["interval"] = _load_interval()
        _stop_event.wait(_state["interval"])
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


def trigger_poll() -> None:
    threading.Thread(target=_run_cycle, daemon=True).start()


def scheduler_status() -> dict:
    with _state["lock"]:
        return {
            "running": _state["running"],
            "interval": _state["interval"],
            "last_run": _state["last_run"],
            "last_duration": round(_state["last_duration"], 2),
        }
