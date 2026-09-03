"""Health engine: built-in detectors + per-host health model + GPU risk score.

Not user-configurable rules — these are product-level detectors that run every
cycle on the freshest data and write AlertEvents with severity + context.

Detectors:
  GPU_IDLE_VRAM_HELD   VRAM used > threshold & util ~0 for N minutes (zombie/空占)
  GPU_MISSING          actual GPU UUID set ⊂ baseline (GPU fell off / removed)
  GPU_ECC_UNCORRECTED  uncorrected ECC > 0 (datacenter cards)
  GPU_XID              kernel Xid events seen this cycle
  GPU_THERMAL_THROTTLE HW/SW thermal throttling active
  NVME_HEALTH          critical_warning / spare low / media errors grow / pct_used
  RAID_DEGRADED        md array not clean / missing disks
  HOSTKEY_CHANGED      SSH host key mismatch (security)
  SSH_FAULT            classified SSH/collection failures (auth/dns/refused/timeout)
  NFS_STALE            NFS mounts missing from current mount table
  SERVICE_FAILED       systemd failed units > 0
  OOM_KILL             kernel OOM events this cycle
  STORAGE_BOTTLENECK   correlation: gpu util drop + iowait up + disk busy up
  GPU_RISK_SCORE       per-GPU 0-100 risk from history (ECC/Xid/temp/throttle/power)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import load_only

from .database import SessionLocal
from .models import (
    AlertEvent,
    GpuBaseline,
    KernelEventRow,
    Server,
    ServerMetric,
    Setting,
    SlowHealth,
)
from . import notifier

logger = logging.getLogger("gpumon.health")

SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}

# point events (no sustained condition to recover from) auto-close after TTL
POINT_EVENT_TYPES = ("GPU_XID", "OOM_KILL", "MCE_HARDWARE_ERROR", "PCIE_AER")
POINT_EVENT_TTL_MINUTES = 60

# built-in detectors use rule_id=None, rule_name=detector name; they share the
# AlertEvent table with user rules. severity mapping for events:
SEV_BY_DETECTOR = {
    "GPU_IDLE_VRAM_HELD": "warning",
    "GPU_MISSING": "critical",
    "GPU_ECC_UNCORRECTED": "critical",
    "GPU_XID": "critical",
    "GPU_THERMAL_THROTTLE": "warning",
    "NVME_HEALTH": "warning",
    "RAID_DEGRADED": "critical",
    "HOSTKEY_CHANGED": "critical",
    "SSH_FAULT": "critical",
    "BMC_UNREACHABLE": "warning",
    "CHASSIS_POWER_OFF": "critical",
    "PSU_FAULT": "critical",
    "SEL_CRITICAL": "critical",
    "NFS_STALE": "warning",
    "SERVICE_FAILED": "warning",
    "OOM_KILL": "critical",
    "STORAGE_BOTTLENECK": "info",
    "MCE_HARDWARE_ERROR": "critical",
    "PCIE_AER": "warning",
}


def _get_setting(db, key: str, default: float) -> float:
    row = db.get(Setting, key)
    if row is None or not row.value:
        return default
    try:
        return float(row.value)
    except ValueError:
        return default


def _notify(db, ev: AlertEvent, detector: str, server_name: str, level: str = "ALERT") -> None:
    """Push detector events through the same webhook path as user rules."""
    sev = SEV_BY_DETECTOR.get(detector, "warning")
    try:
        if level == "ALERT":
            ok, _why = notifier.notify_alert(
                server_name, detector, ev.value or 0, "", ev.threshold or 0, detector,
                severity=sev,
            )
        else:
            ok, _why = notifier.notify_recovery(server_name, detector, detector)
        if level == "ALERT":
            ev.notified = bool(ok)
            db.commit()
    except Exception:
        logger.exception("detector notification failed: %s", detector)


def _open_event(db, detector: str, server_id: int, key: str = ""):
    q = db.query(AlertEvent).filter(
        AlertEvent.rule_id.is_(None),
        AlertEvent.metric == detector,
        AlertEvent.server_id == server_id,
        AlertEvent.recovered_at.is_(None),
    )
    if key:
        q = q.filter(AlertEvent.message.contains(f"[{key}]"))
    return q.first()


def _fire(db, detector: str, server_id: int, server_name: str, message: str,
          value: float = 0, threshold: float = 0, key: str = "") -> None:
    ev = _open_event(db, detector, server_id, key)
    if ev is not None:
        return  # already open
    if key:
        message = f"[{key}] {message}"
    ev = AlertEvent(
        rule_id=None,
        rule_name=detector,
        server_id=server_id,
        server_name=server_name,
        metric=detector,
        value=value,
        threshold=threshold,
        message=message,
    )
    db.add(ev)
    db.commit()
    logger.info("detector fired: %s %s %s", detector, server_name, message)
    _notify(db, ev, detector, server_name, "ALERT")


def _recover(db, detector: str, server_id: int, key: str = "") -> None:
    ev = _open_event(db, detector, server_id, key)
    if ev is not None:
        ev.recovered_at = datetime.now(timezone.utc)
        db.commit()
        if ev.notified:
            _notify(db, ev, detector, ev.server_name, "RECOVERY")


def _ttl_recover_point_events(db) -> None:
    """Auto-close point events (Xid/OOM/MCE/AER) older than TTL so the open
    list does not grow forever."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=POINT_EVENT_TTL_MINUTES)
    rows = (
        db.query(AlertEvent)
        .filter(AlertEvent.rule_id.is_(None),
                AlertEvent.metric.in_(POINT_EVENT_TYPES),
                AlertEvent.recovered_at.is_(None),
                AlertEvent.triggered_at <= cutoff)
        .all()
    )
    for ev in rows:
        ev.recovered_at = datetime.now(timezone.utc)
    if rows:
        db.commit()


# ---------------------------------------------------------------- detectors

def _detect_gpu_idle(db, server: Server, m: ServerMetric) -> None:
    """VRAM held but ~0 util for N+ min => 空占 / zombie."""
    vram_pct = _get_setting(db, "gpu_idle_vram_pct", 30.0) / 100.0
    idle_minutes = int(_get_setting(db, "gpu_idle_minutes", 30))
    candidates = []
    for g in (m.gpus or []):
        total = g.get("mem_total_mb", 0) or 0
        used = g.get("mem_used_mb", 0) or 0
        util = g.get("utilization", 0) or 0
        key = g.get("uuid") or f"idx{g.get('index')}"
        if total <= 0 or used / total < vram_pct or util > 5:
            _recover(db, "GPU_IDLE_VRAM_HELD", server.id, key=key)
            continue
        candidates.append((g, used, total, key))
    if not candidates:
        return
    # one window query for all candidate GPUs
    since = m.collected_at - timedelta(minutes=idle_minutes)
    rows = (
        db.query(ServerMetric)
        .options(load_only(ServerMetric.gpus, ServerMetric.collected_at, ServerMetric.status))
        .filter(ServerMetric.server_id == server.id,
                ServerMetric.collected_at >= since,
                ServerMetric.status == "ok")
        .order_by(ServerMetric.collected_at.asc())
        .all()
    )
    min_samples = max(2, idle_minutes // 10)
    for g, used, total, key in candidates:
        uuid = g.get("uuid")
        held = True
        for r in rows:
            gg = next((x for x in (r.gpus or []) if x.get("uuid") == uuid), None)
            if gg is None or (gg.get("utilization", 0) or 0) > 5:
                held = False
                break
        if held and len(rows) >= min_samples:
            procs = [p for p in g.get("processes", []) if p.get("pid")]
            pinfo = ", ".join(f"PID {p['pid']}({p.get('user','?')})" for p in procs[:3]) or "无进程"
            _fire(db, "GPU_IDLE_VRAM_HELD", server.id, m.hostname or server.name,
                  f"GPU {g.get('index')} 显存占用 {round(used/1024,1)}GB 但利用率≈0 持续{idle_minutes}分钟（{pinfo}）——疑似空占/僵尸进程",
                  value=round(used / total * 100, 1), threshold=int(vram_pct * 100), key=key)
        else:
            _recover(db, "GPU_IDLE_VRAM_HELD", server.id, key=key)


def _detect_gpu_missing(
    db, server: Server, m: ServerMetric, baseline: list[GpuBaseline]
) -> None:
    if not baseline:
        return
    seen = {g.get("uuid") for g in (m.gpus or [])}
    for b in baseline:
        if b.gpu_uuid in seen:
            if b.missing_since is not None:
                b.missing_since = None
            b.last_seen = datetime.now(timezone.utc)
            _recover(db, "GPU_MISSING", server.id, key=b.gpu_uuid)
        else:
            if b.missing_since is None:
                b.missing_since = datetime.now(timezone.utc)
                _fire(db, "GPU_MISSING", server.id, m.hostname or server.name,
                      f"GPU {b.name or b.gpu_uuid} ({b.pci_bus_id}) 从采集结果中消失——掉卡/被移除/驱动异常",
                      key=b.gpu_uuid)
    db.commit()


def _detect_gpu_ecc(
    db, server: Server, m: ServerMetric, baseline_by_uuid: dict[str, GpuBaseline]
) -> None:
    for g in (m.gpus or []):
        if not g.get("ecc_supported"):
            continue
        uuid = g.get("uuid") or ""
        key = uuid or f"idx{g.get('index')}"
        volatile = g.get("ecc_uncorrected_volatile", 0) or 0
        aggregate = g.get("ecc_uncorrected_total", 0) or 0
        problems = []
        if volatile > 0:
            problems.append(f"本次启动新增 {volatile} 条")
        if uuid:
            b = baseline_by_uuid.get(uuid)
            if b is not None:
                if b.ecc_uncorrected_baseline is None:
                    b.ecc_uncorrected_baseline = aggregate
                elif aggregate > b.ecc_uncorrected_baseline:
                    problems.append(f"累计新增 {aggregate - b.ecc_uncorrected_baseline} 条")
                    b.ecc_uncorrected_baseline = aggregate
        if problems:
            _fire(db, "GPU_ECC_UNCORRECTED", server.id, m.hostname or server.name,
                  f"GPU {g.get('index')} 不可纠正 ECC 错误（{'，'.join(problems)}）——硬件故障风险",
                  value=volatile, key=key)
        else:
            _recover(db, "GPU_ECC_UNCORRECTED", server.id, key=key)
    db.commit()


def _detect_gpu_throttle(db, server: Server, m: ServerMetric) -> None:
    for g in (m.gpus or []):
        reasons = g.get("throttle_reasons", []) or []
        thermal = [r for r in reasons if "THERMAL" in r or r == "HW_SLOWDOWN"]
        if thermal:
            _fire(db, "GPU_THERMAL_THROTTLE", server.id, m.hostname or server.name,
                  f"GPU {g.get('index')} 热降频中（{','.join(thermal)}，{g.get('temperature')}°C）",
                  value=g.get("temperature", 0), threshold=0, key=g.get("uuid", ""))
        else:
            _recover(db, "GPU_THERMAL_THROTTLE", server.id, key=g.get("uuid", ""))


def _detect_kernel_events(db, server: Server, since: datetime) -> None:
    rows = (
        db.query(KernelEventRow)
        .filter(KernelEventRow.server_id == server.id,
                KernelEventRow.collected_at >= since)
        .all()
    )
    seen_types: set[str] = set()
    for ev in rows:
        seen_types.add(ev.event_type)
        detector = ev.event_type
        if detector == "GPU_XID":
            # key per-event (dedup_hash): distinct Xids on the same GPU must
            # each fire; a gpu_uuid-only key swallowed every later Xid
            _fire(db, "GPU_XID", server.id, server.name,
                  f"GPU {ev.gpu_uuid or '?'} Xid {ev.xid}: {ev.message[:120]}",
                  value=ev.xid, key=ev.dedup_hash[:16])
        elif detector in ("OOM_KILL", "MCE_HARDWARE_ERROR", "PCIE_AER"):
            _fire(db, detector, server.id, server.name, ev.message[:160], key=ev.dedup_hash[:16])
    # point events auto-close via _ttl_recover_point_events


def _detect_nvme(db, server: Server, latest: SlowHealth | None) -> None:
    if latest is None or not latest.nvme_smart:
        return
    for d in latest.nvme_smart:
        dev = d.get("device", "?")
        problems = []
        if d.get("critical_warning", 0):
            problems.append(f"critical_warning=0x{d['critical_warning']:x}")
        spare = d.get("available_spare")
        thr = d.get("available_spare_threshold")
        if spare is not None and thr is not None and spare <= thr:
            problems.append(f"可用备用空间 {spare}% ≤ 阈值 {thr}%")
        if d.get("media_errors"):
            problems.append(f"介质错误 {d['media_errors']} 次")
        pu = d.get("percentage_used")
        if pu is not None and pu >= 90:
            problems.append(f"寿命已用 {pu}%")
        if problems:
            _fire(db, "NVME_HEALTH", server.id, server.name,
                  f"{dev}: " + "; ".join(problems), key=dev)
        else:
            _recover(db, "NVME_HEALTH", server.id, key=dev)


def _detect_raid(db, server: Server, latest: SlowHealth | None) -> None:
    if latest is None or not (latest.mdraid or {}).get("arrays"):
        return
    for arr in latest.mdraid.get("arrays", []):
        state = arr.get("state", "")
        active, total = arr.get("active_disks"), arr.get("total_disks")
        if "_" in state or (active is not None and total is not None and active < total):
            _fire(db, "RAID_DEGRADED", server.id, server.name,
                  f"{arr.get('name')} {arr.get('level','')} 状态降级（{active}/{total} 在线, {state}）",
                  key=arr.get("name", ""))
        else:
            _recover(db, "RAID_DEGRADED", server.id, key=arr.get("name", ""))


def _detect_ssh_fault(db, server: Server, m: ServerMetric) -> None:
    if m.status == "error":
        # require two consecutive failures to avoid alerting on blips
        prev = (
            db.query(ServerMetric)
            .options(load_only(ServerMetric.status))
            .filter(ServerMetric.server_id == server.id,
                    ServerMetric.collected_at < m.collected_at)
            .order_by(ServerMetric.collected_at.desc())
            .first()
        )
        if prev is not None and prev.status == "error":
            _fire(db, "SSH_FAULT", server.id, server.name,
                  f"{m.error_code}: {m.error[:120]}", key="SSH")
    else:
        # recover all SSH faults on success
        for ev in (
            db.query(AlertEvent)
            .filter(AlertEvent.rule_id.is_(None), AlertEvent.metric == "SSH_FAULT",
                    AlertEvent.server_id == server.id, AlertEvent.recovered_at.is_(None))
            .all()
        ):
            ev.recovered_at = datetime.now(timezone.utc)
        db.commit()


def _detect_services(db, server: Server, latest: SlowHealth | None) -> None:
    if latest is None:
        return
    failed = latest.systemd_failed or []
    if failed:
        names = ", ".join(f["unit"] for f in failed[:5])
        msg = f"{len(failed)} 个 systemd 单元失败: {names}"
        ev = _open_event(db, "SERVICE_FAILED", server.id)
        if ev is not None:
            if ev.message != msg:
                ev.message = msg
                db.commit()
        else:
            _fire(db, "SERVICE_FAILED", server.id, server.name, msg)
    else:
        _recover(db, "SERVICE_FAILED", server.id)


def _detect_storage_bottleneck(db, server: Server, m: ServerMetric) -> None:
    """Correlation: GPU util dropped + iowait elevated + disk busy high."""
    since = m.collected_at - timedelta(minutes=20)
    rows = (
        db.query(ServerMetric)
        .options(load_only(
            ServerMetric.gpus, ServerMetric.cpu_iowait,
            ServerMetric.disk_io, ServerMetric.collected_at,
        ))
        .filter(ServerMetric.server_id == server.id,
                ServerMetric.collected_at >= since,
                ServerMetric.status == "ok")
        .order_by(ServerMetric.collected_at.asc())
        .all()
    )
    if len(rows) < 6:
        return
    def gpu_util(r):
        vals = [g.get("utilization", 0) or 0 for g in (r.gpus or [])]
        return sum(vals) / len(vals) if vals else 0
    def disk_busy(r):
        vals = [d.get("busy_percent", 0) or 0 for d in (r.disk_io or [])]
        return max(vals) if vals else 0
    first_util = sum(gpu_util(r) for r in rows[:3]) / 3
    last_util = sum(gpu_util(r) for r in rows[-3:]) / 3
    last_iowait = max(r.cpu_iowait or 0 for r in rows[-3:])
    last_busy = max(disk_busy(r) for r in rows[-3:])
    if first_util > 60 and last_util < first_util * 0.5 and last_iowait > 10 and last_busy > 70:
        _fire(db, "STORAGE_BOTTLENECK", server.id, m.hostname or server.name,
              f"疑似存储瓶颈：GPU 均值 {round(first_util)}%→{round(last_util)}%，iowait {round(last_iowait,1)}%，磁盘繁忙 {round(last_busy)}%")
    else:
        _recover(db, "STORAGE_BOTTLENECK", server.id)


# ---------------------------------------------------------------- risk score

def gpu_risk_scores(server_ids: list[int]) -> dict[int, list[dict]]:
    """Calculate exact 24h GPU risks for many servers in two streamed queries."""
    ordered_ids = list(dict.fromkeys(server_ids))
    result: dict[int, list[dict]] = {server_id: [] for server_id in ordered_ids}
    if not ordered_ids:
        return result

    db = SessionLocal()
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        metrics = (
            db.query(ServerMetric.server_id, ServerMetric.gpus)
            .filter(ServerMetric.server_id.in_(ordered_ids),
                    ServerMetric.collected_at >= since,
                    ServerMetric.status == "ok")
            .order_by(ServerMetric.server_id.asc(), ServerMetric.collected_at.asc())
            .execution_options(stream_results=True)
            .yield_per(500)
        )
        by_server: dict[int, dict[str, dict]] = {
            server_id: {} for server_id in ordered_ids
        }
        for server_id, gpus in metrics:
            uuids = by_server[server_id]
            for g in (gpus or []):
                u = g.get("uuid")
                if not u:
                    continue
                d = uuids.setdefault(u, {
                    "uuid": u, "index": g.get("index"), "name": g.get("name", ""),
                    "max_temp": 0, "thermal_throttle_samples": 0, "samples": 0,
                    "ecc_uncorrected_max": 0, "ecc_corrected_max": 0, "xid_events": 0,
                    "power_cap_samples": 0, "pcie_degraded_samples": 0,
                })
                d["samples"] += 1
                d["max_temp"] = max(d["max_temp"], g.get("temperature", 0) or 0)
                reasons = g.get("throttle_reasons", []) or []
                if any("THERMAL" in r or r == "HW_SLOWDOWN" for r in reasons):
                    d["thermal_throttle_samples"] += 1
                if "SW_POWER_CAP" in reasons:
                    d["power_cap_samples"] += 1
                d["ecc_uncorrected_max"] = max(
                    d["ecc_uncorrected_max"], g.get("ecc_uncorrected_volatile", 0) or 0
                )
                d["ecc_corrected_max"] = max(
                    d["ecc_corrected_max"], g.get("ecc_corrected_volatile", 0) or 0
                )
                if (
                    g.get("pcie_width_max")
                    and g.get("pcie_width_current")
                    and g["pcie_width_current"] < g["pcie_width_max"]
                ):
                    d["pcie_degraded_samples"] += 1

        xids = (
            db.query(KernelEventRow.server_id, KernelEventRow.gpu_uuid)
            .filter(KernelEventRow.server_id.in_(ordered_ids),
                    KernelEventRow.event_type == "GPU_XID",
                    KernelEventRow.collected_at >= since)
            .execution_options(stream_results=True)
            .yield_per(500)
        )
        for server_id, gpu_uuid in xids:
            if gpu_uuid in by_server[server_id]:
                by_server[server_id][gpu_uuid]["xid_events"] += 1

        for server_id, uuids in by_server.items():
            out = []
            for d in uuids.values():
                score = 0
                score += min(40, d["xid_events"] * 20)
                score += min(25, d["ecc_uncorrected_max"] * 5)
                score += min(
                    15,
                    10
                    if d["ecc_corrected_max"] > 100
                    else (5 if d["ecc_corrected_max"] > 0 else 0),
                )
                if d["thermal_throttle_samples"] > 0:
                    score += min(15, 5 + d["thermal_throttle_samples"])
                if d["max_temp"] >= 85:
                    score += 5
                if d["pcie_degraded_samples"] > max(1, d["samples"] // 10):
                    score += 5
                d["risk"] = min(100, score)
                if d["risk"] >= 60:
                    d["risk_label"] = "高危"
                elif d["risk"] >= 30:
                    d["risk_label"] = "关注"
                else:
                    d["risk_label"] = "健康"
                out.append(d)
            out.sort(key=lambda x: -x["risk"])
            result[server_id] = out
        return result
    finally:
        db.close()


def gpu_risk_score(server_id: int) -> list[dict]:
    """0-100 per-GPU risk from the last 24h: ECC, Xid, thermal throttle, temp, power cap."""
    return gpu_risk_scores([server_id])[server_id]


# ---------------------------------------------------------------- entry point

def run_detectors(server_id: int, latest_metric_id: Optional[int] = None) -> None:
    """Run all built-in detectors for one server after a fast collection."""
    db = SessionLocal()
    try:
        server = (
            db.query(Server)
            .options(load_only(Server.id, Server.name, Server.status))
            .filter(Server.id == server_id)
            .first()
        )
        if server is None:
            return
        if (server.status or "active") == "maintenance":
            return  # planned work: detectors stay silent
        m = (
            db.query(ServerMetric)
            .options(load_only(
                ServerMetric.collected_at, ServerMetric.hostname,
                ServerMetric.status, ServerMetric.error_code,
                ServerMetric.error, ServerMetric.gpus,
            ))
            .filter(ServerMetric.server_id == server_id)
            .order_by(ServerMetric.collected_at.desc())
            .first()
        )
        if m is None:
            return
        _ttl_recover_point_events(db)
        _detect_ssh_fault(db, server, m)
        if m.status == "ok":
            _detect_gpu_idle(db, server, m)
            baseline = (
                db.query(GpuBaseline)
                .filter(GpuBaseline.server_id == server.id)
                .all()
            )
            _detect_gpu_missing(db, server, m, baseline)
            _detect_gpu_ecc(db, server, m, {row.gpu_uuid: row for row in baseline})
            _detect_gpu_throttle(db, server, m)
            _detect_storage_bottleneck(db, server, m)
        since = datetime.now(timezone.utc) - timedelta(minutes=10)
        _detect_kernel_events(db, server, since)
        latest_slow = (
            db.query(SlowHealth)
            .options(load_only(
                SlowHealth.collected_at,
                SlowHealth.nvme_smart,
                SlowHealth.mdraid,
                SlowHealth.systemd_failed,
            ))
            .filter(SlowHealth.server_id == server_id)
            .order_by(SlowHealth.collected_at.desc())
            .first()
        )
        _detect_nvme(db, server, latest_slow)
        _detect_raid(db, server, latest_slow)
        _detect_services(db, server, latest_slow)
    except Exception:
        logger.exception("detectors failed for server %s", server_id)
        db.rollback()
    finally:
        db.close()


def update_gpu_baseline(server_id: int, gpus: list[dict]) -> None:
    """Record GPU UUIDs on every successful collect; new GPUs auto-registered."""
    valid_gpus = [gpu for gpu in gpus if gpu.get("uuid")]
    if not valid_gpus:
        return
    db = SessionLocal()
    try:
        existing = {
            row.gpu_uuid: row
            for row in db.query(GpuBaseline)
            .filter(
                GpuBaseline.server_id == server_id,
                GpuBaseline.gpu_uuid.in_([gpu["uuid"] for gpu in valid_gpus]),
            )
            .all()
        }
        for g in valid_gpus:
            uuid = g.get("uuid")
            row = existing.get(uuid)
            if row is None:
                row = GpuBaseline(
                    server_id=server_id, gpu_uuid=uuid,
                    name=g.get("name", ""), serial=g.get("serial", ""),
                    pci_bus_id=g.get("pci_bus_id", ""),
                )
                db.add(row)
                existing[uuid] = row
            else:
                row.last_seen = datetime.now(timezone.utc)
                row.missing_since = None
                if g.get("name"):
                    row.name = g["name"]
                if g.get("serial"):
                    row.serial = g["serial"]
                if g.get("pci_bus_id"):
                    row.pci_bus_id = g["pci_bus_id"]
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("baseline update failed")
    finally:
        db.close()


def health_tree(server_id: int, gpu_risks: Optional[list[dict]] = None) -> dict:
    """Aggregate per-host health model for the frontend tree view."""
    db = SessionLocal()
    try:
        server = (
            db.query(Server)
            .options(load_only(Server.id, Server.name, Server.server_type))
            .filter(Server.id == server_id)
            .first()
        )
        if server is None:
            return {}
        latest = (
            db.query(ServerMetric)
            .options(load_only(
                ServerMetric.collected_at, ServerMetric.hostname,
                ServerMetric.status, ServerMetric.error_code,
                ServerMetric.error, ServerMetric.ssh_latency,
                ServerMetric.duration, ServerMetric.cpu_percent,
                ServerMetric.cpu_iowait, ServerMetric.mem_used_mb,
                ServerMetric.mem_total_mb, ServerMetric.disks,
                ServerMetric.inodes, ServerMetric.net_ifaces,
                ServerMetric.gpus,
            ))
            .filter(ServerMetric.server_id == server_id)
            .order_by(ServerMetric.collected_at.desc())
            .first()
        )
        if latest is None:
            return {"server": server.name, "overall": "unknown", "categories": []}
        categories = []
        overall = "ok"

        def cat(name, status, detail=""):
            nonlocal overall
            categories.append({"name": name, "status": status, "detail": detail})
            if status == "critical":
                overall = "critical"
            elif status == "warning" and overall != "critical":
                overall = "warning"

        # connectivity
        if latest.status == "error":
            cat("连通性", "critical", f"{latest.error_code}: {latest.error[:80]}")
        else:
            cat("连通性", "ok", f"SSH {latest.ssh_latency}s · 采集 {latest.duration}s")

        if latest.status == "ok":
            # cpu / memory (thresholds configurable in settings)
            cpu_thr = _get_setting(db, "health_cpu_pct", 90.0)
            mem_thr = _get_setting(db, "health_mem_pct", 92.0)
            disk_thr = _get_setting(db, "health_disk_pct", 90.0)
            cat("CPU", "ok" if latest.cpu_percent < cpu_thr else "warning",
                f"{round(latest.cpu_percent,1)}% · iowait {round(latest.cpu_iowait or 0,1)}%")
            mem_pct = latest.mem_used_mb / latest.mem_total_mb * 100 if latest.mem_total_mb else 0
            cat("内存", "ok" if mem_pct < mem_thr else "warning", f"{round(mem_pct,1)}%")
            # storage
            disk_pcts = [d.get("percent", 0) for d in (latest.disks or [])]
            inode_pcts = [d.get("inodes_percent", 0) for d in (latest.inodes or [])]
            worst_d = max(disk_pcts) if disk_pcts else 0
            worst_i = max(inode_pcts) if inode_pcts else 0
            dstat = "ok" if worst_d < disk_thr else "warning"
            cat("文件系统", dstat,
                f"空间 {round(worst_d,1)}%" + (f" · inode {round(worst_i,1)}%" if worst_i else ""))
            # network
            err_ifaces = [i for i in (latest.net_ifaces or [])
                          if (i.get("rx_err_rate") or 0) + (i.get("tx_err_rate") or 0) > 0]
            cat("网络", "ok" if not err_ifaces else "warning",
                ", ".join(f"{i['iface']} err" for i in err_ifaces[:3]) or "正常")

        # GPUs from risk score (GPU servers only)
        risks = (
            gpu_risks
            if gpu_risks is not None
            else (gpu_risk_score(server_id) if server.server_type != "cpu" else [])
        )
        gpu_cats = []
        for r in risks:
            status = "critical" if r["risk"] >= 60 else ("warning" if r["risk"] >= 30 else "ok")
            bits = []
            if r["xid_events"]:
                bits.append(f"Xid×{r['xid_events']}")
            if r["ecc_uncorrected_max"]:
                bits.append(f"ECC-Unc {r['ecc_uncorrected_max']}")
            if r["thermal_throttle_samples"]:
                bits.append("热降频")
            detail = f"{r['name']} · 最高 {r['max_temp']}°C" + (f" · {'/'.join(bits)}" if bits else "")
            gpu_cats.append({"name": f"GPU{r.get('index', '?')}", "status": status, "detail": detail})
        if gpu_cats:
            # parent status must reflect children (was hardcoded "ok")
            worst = "ok"
            for c in gpu_cats:
                if c["status"] == "critical":
                    worst = "critical"
                elif c["status"] == "warning" and worst != "critical":
                    worst = "warning"
            cat("GPU", worst, f"{len(gpu_cats)} 卡")
            categories[-1]["children"] = gpu_cats

        # kernel events (24h)
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        kev = (
            db.query(KernelEventRow)
            .filter(KernelEventRow.server_id == server_id, KernelEventRow.collected_at >= since)
            .count()
        )
        if kev:
            crit = (
                db.query(KernelEventRow)
                .filter(KernelEventRow.server_id == server_id,
                        KernelEventRow.collected_at >= since,
                        KernelEventRow.severity == "critical")
                .count()
            )
            cat("内核事件", "critical" if crit else "warning", f"24h 内 {kev} 条（{crit} 条严重）")
        else:
            cat("内核事件", "ok", "24h 无异常")

        updated = latest.collected_at or datetime.now(timezone.utc)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return {
            "server": server.name,
            "overall": overall,
            "updated_at": updated.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "categories": categories,
        }
    finally:
        db.close()
