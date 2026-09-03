"""Enterprise monitoring APIs: health tree, kernel events, slow health
(NVMe/RAID/NFS/MIG/NVLink/IPMI), inventory (DMI/NUMA/topology), GPU risk."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..security import (
    check_step_up_limit,
    get_current_user,
    record_step_up_failure,
    record_step_up_success,
    require_admin,
    verify_password,
)
from ..schemas import HostKeyResetRequest
from ..database import get_db
from ..health import gpu_risk_score, health_tree
from ..models import (
    AlertEvent,
    AuditLog,
    HostInventory,
    KernelEventRow,
    Server,
    ServerMetric,
    Setting,
    SlowHealth,
    User,
)
from ..ssh_transport import (
    HostKeyFingerprintMismatch,
    replace_hostkey_with_expected_fingerprint,
)

router = APIRouter(prefix="/api", tags=["enterprise"])


def _iso(dt) -> str:
    """ISO string with explicit UTC offset (MySQL DATETIME rows come back naive)."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@router.get("/servers/{server_id}/health")
def server_health(server_id: int, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    tree = health_tree(server_id)
    if not tree:
        raise HTTPException(404, "server not found")
    return tree


@router.get("/servers/{server_id}/risk")
def server_gpu_risk(server_id: int, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    server = db.get(Server, server_id)
    if server is None:
        raise HTTPException(404, "server not found")
    return {"server": server.name, "gpus": gpu_risk_score(server_id)}


@router.get("/servers/{server_id}/kernel-events")
def server_kernel_events(
    server_id: int,
    hours: int = Query(24, ge=1, le=168),
    severity: str = Query("", pattern="^(|info|warning|critical)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = (
        db.query(KernelEventRow)
        .filter(KernelEventRow.server_id == server_id,
                KernelEventRow.collected_at >= since)
    )
    if severity:
        q = q.filter(KernelEventRow.severity == severity)
    rows = q.order_by(KernelEventRow.collected_at.desc()).limit(500).all()
    return [
        {
            "id": r.id,
            "collected_at": _iso(r.collected_at),
            "boot_id": r.boot_id,
            "event_type": r.event_type,
            "severity": r.severity,
            "gpu_uuid": r.gpu_uuid,
            "xid": r.xid,
            "message": r.message,
        }
        for r in rows
    ]


@router.get("/kernel-events")
def all_kernel_events(
    hours: int = Query(24, ge=1, le=168),
    severity: str = Query("", pattern="^(|info|warning|critical)$"),
    event_type: str = Query(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = db.query(KernelEventRow).filter(KernelEventRow.collected_at >= since)
    if severity:
        q = q.filter(KernelEventRow.severity == severity)
    if event_type:
        q = q.filter(KernelEventRow.event_type == event_type)
    rows = q.order_by(KernelEventRow.collected_at.desc()).limit(1000).all()
    servers = {s.id: s.name for s in db.query(Server).all()}
    return [
        {
            "id": r.id,
            "server_id": r.server_id,
            "server_name": servers.get(r.server_id, str(r.server_id)),
            "collected_at": _iso(r.collected_at),
            "event_type": r.event_type,
            "severity": r.severity,
            "gpu_uuid": r.gpu_uuid,
            "xid": r.xid,
            "message": r.message,
        }
        for r in rows
    ]


@router.get("/servers/{server_id}/slow-health")
def server_slow_health(server_id: int, db: Session = Depends(get_db),
                       user: User = Depends(require_admin)):
    latest = (
        db.query(SlowHealth)
        .filter(SlowHealth.server_id == server_id)
        .order_by(SlowHealth.collected_at.desc())
        .first()
    )
    if latest is None:
        return {"collected_at": None, "nvme_smart": [], "mdraid": {}, "nfs_mounts": [],
                "systemd_failed": [], "services": {}, "mig": [], "nvlink": {}, "ipmi": []}
    return {
        "collected_at": latest.collected_at.isoformat(),
        "nvme_smart": latest.nvme_smart or [],
        "mdraid": latest.mdraid or {},
        "nfs_mounts": latest.nfs_mounts or [],
        "systemd_failed": latest.systemd_failed or [],
        "services": latest.services or {},
        "mig": latest.mig or [],
        "nvlink": latest.nvlink or {},
        "ipmi": latest.ipmi or [],
    }


@router.get("/servers/{server_id}/inventory")
def server_inventory(server_id: int, db: Session = Depends(get_db),
                     user: User = Depends(require_admin)):
    latest = (
        db.query(HostInventory)
        .filter(HostInventory.server_id == server_id)
        .order_by(HostInventory.collected_at.desc())
        .first()
    )
    if latest is None:
        return {"collected_at": None}
    return {
        "collected_at": latest.collected_at.isoformat(),
        "machine_id": latest.machine_id,
        "dmi": latest.dmi or {},
        "lscpu": latest.lscpu or {},
        "numa": latest.numa or {},
        "gpu_topology": latest.gpu_topology or "",
        "pci_numa": latest.pci_numa or [],
        "disks": latest.disks or [],
        "nics": latest.nics or [],
        "ip_addrs": latest.ip_addrs or [],
        "ib": latest.ib or {},
        "time_info": latest.time_info or {},
    }


@router.post("/servers/{server_id}/reset-hostkey")
def reset_hostkey(
    server_id: int,
    body: HostKeyResetRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    server = db.get(Server, server_id)
    if server is None:
        raise HTTPException(404, "server not found")
    ip, bucket = check_step_up_limit(request, user, "hostkey-reset")
    if not verify_password(body.reauth_password, user.password_hash):
        record_step_up_failure(ip, bucket)
        try:
            db.add(
                AuditLog(
                    username=user.username,
                    action="server.reset_hostkey.reauth_failed",
                    detail=f"server_id={server_id} ip={ip}",
                )
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            raise HTTPException(503, "security audit unavailable") from exc
        raise HTTPException(403, "administrator re-authentication failed")
    record_step_up_success(ip, bucket)

    # Record intent before changing trust state. The submitted fingerprint must
    # have been verified through an out-of-band channel.
    try:
        db.add(
            AuditLog(
                username=user.username,
                action="server.reset_hostkey.requested",
                detail=(
                    f"server_id={server_id} fingerprint="
                    f"{body.expected_fingerprint.rstrip('=')} ip={ip}"
                ),
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(503, "security audit unavailable") from exc

    try:
        actual_fingerprint = replace_hostkey_with_expected_fingerprint(
            server.host,
            server.port or 22,
            f"server_{server_id}",
            body.expected_fingerprint,
        )
    except HostKeyFingerprintMismatch as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "unable to verify and pin the SSH host key") from exc

    # also clear any open HOSTKEY/SSH alerts so it can recover on next poll
    (
        db.query(AlertEvent)
        .filter(
            AlertEvent.server_id == server_id,
            AlertEvent.rule_id.is_(None),
            AlertEvent.metric.in_(["SSH_FAULT", "HOSTKEY_CHANGED"]),
            AlertEvent.recovered_at.is_(None),
        )
        .update({"recovered_at": datetime.now(timezone.utc)}, synchronize_session=False)
    )
    db.add(
        AuditLog(
            username=user.username,
            action="server.reset_hostkey.completed",
            detail=f"server_id={server_id} fingerprint={actual_fingerprint}",
        )
    )
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(503, "security audit unavailable") from exc
    return {
        "ok": True,
        "fingerprint": actual_fingerprint,
        "message": "SSH host key fingerprint verified and pinned",
    }


@router.get("/servers/{server_id}/collect-health")
def server_collect_health(server_id: int,
                          hours: int = Query(24, ge=1, le=168),
                          db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    """How reliable is collection for this host: success rate, latency,
    and which error codes actually occurred."""
    from sqlalchemy import func

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = db.query(ServerMetric.status, ServerMetric.error_code,
                 func.count(ServerMetric.id), func.avg(ServerMetric.ssh_latency),
                 func.avg(ServerMetric.duration)).filter(
        ServerMetric.server_id == server_id,
        ServerMetric.collected_at >= since,
    ).group_by(ServerMetric.status, ServerMetric.error_code).all()
    total = ok = 0
    lat_sum = dur_sum = 0.0
    errors: dict[str, int] = {}
    for status, code, cnt, avg_lat, avg_dur in q:
        total += cnt
        if status == "ok":
            ok += cnt
            lat_sum += (avg_lat or 0) * cnt
            dur_sum += (avg_dur or 0) * cnt
        else:
            errors[code or "UNKNOWN"] = errors.get(code or "UNKNOWN", 0) + cnt
    return {
        "window_hours": hours,
        "total": total,
        "ok": ok,
        "success_rate": round(ok / total * 100, 1) if total else 0,
        "avg_ssh_latency": round(lat_sum / ok, 3) if ok else 0,
        "avg_duration": round(dur_sum / ok, 2) if ok else 0,
        "errors": errors,
    }


@router.get("/cluster/utilization-report")
def cluster_utilization_report(
    hours: int = Query(24, ge=1, le=168),
    tag: str = Query(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Per-server utilization over the window from hourly aggregates:
    GPU average util, idle-held minutes (空占), average power, ok-rate."""
    from ..models import ServerMetricHourly

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = db.query(Server).filter(Server.enabled.is_(True), Server.server_type != "cpu")
    servers = q.all()
    out = []
    for s in servers:
        if tag and tag not in (s.tags or []):
            continue
        rows = (
            db.query(ServerMetricHourly)
            .filter(ServerMetricHourly.server_id == s.id,
                    ServerMetricHourly.hour >= since)
            .all()
        )
        if not rows:
            continue
        samples = sum(r.samples for r in rows)
        ok = sum(r.ok_samples for r in rows)
        weighted = sum(r.gpu_util_avg * r.ok_samples for r in rows)
        power_w = sum(r.gpu_power_avg * r.ok_samples for r in rows)
        idle_min = sum(r.idle_held_minutes for r in rows)
        gpu_hours = (ok / 60.0)  # ok samples are ~1 minute each at default interval
        out.append({
            "server_id": s.id,
            "server_name": s.name,
            "tags": s.tags or [],
            "hours_covered": round(len(rows), 1),
            "success_rate": round(ok / samples * 100, 1) if samples else 0,
            "gpu_util_avg": round(weighted / ok, 1) if ok else 0,
            "gpu_power_avg_w": round(power_w / ok, 1) if ok else 0,
            "idle_held_minutes": idle_min,
            "idle_held_gpu_hours": round(idle_min / 60.0, 1),
            "gpu_hours": round(gpu_hours, 1),
            "idle_ratio_pct": round(idle_min / (ok * 60) * 100, 1) if ok else 0,
        })
    out.sort(key=lambda x: -x["idle_held_minutes"])
    return {
        "window_hours": hours,
        "total_gpu_hours": round(sum(x["gpu_hours"] for x in out), 1),
        "total_idle_gpu_hours": round(sum(x["idle_held_gpu_hours"] for x in out), 1),
        "servers": out,
    }


# ------------------------------------------------------------- cluster level

@router.get("/cluster/gpu-analysis")
def cluster_gpu_analysis(db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    """Cluster-wide GPU idle-held detection (空占) + failure-risk ranking."""
    from .. import cache as app_cache

    payload = app_cache.cached(
        "cluster:gpu-analysis", 300.0, lambda: _gpu_analysis(db)
    )
    from ..privacy import minimize_processes

    return {
        **payload,
        "gpus": [
            {**gpu, "processes": minimize_processes(gpu.get("processes"))}
            for gpu in payload.get("gpus", [])
        ],
    }


def _gpu_analysis(db: Session):
    from datetime import timezone as tz
    import json as _json

    servers = db.query(Server).filter(Server.enabled.is_(True), Server.server_type != "cpu").all()
    if not servers:
        return {"total_gpus": 0, "idle_held_count": 0, "high_risk_count": 0, "gpus": []}
    sids = [s.id for s in servers]

    # idle_since per GPU is maintained by the scheduler on every poll
    # (settings key gpu_idle_state), so durations are exact and unbounded
    from ..scheduler import IDLE_STATE_KEY
    state_row = db.get(Setting, IDLE_STATE_KEY)
    try:
        idle_state = _json.loads(state_row.value) if state_row and state_row.value else {}
    except Exception:
        idle_state = {}

    from sqlalchemy import and_, func as sa_func
    from sqlalchemy.orm import load_only
    sub = (
        db.query(ServerMetric.server_id, sa_func.max(ServerMetric.collected_at).label("mx"))
        .filter(ServerMetric.server_id.in_(sids))
        .group_by(ServerMetric.server_id)
        .subquery()
    )
    latest_by_srv = {
        m.server_id: m
        for m in db.query(ServerMetric)
        .options(load_only(ServerMetric.server_id, ServerMetric.collected_at, ServerMetric.gpus))
        .join(sub, and_(ServerMetric.server_id == sub.c.server_id,
                        ServerMetric.collected_at == sub.c.mx))
        .all()
    }

    from concurrent.futures import ThreadPoolExecutor

    def _risks_for(server_id: int):
        from ..health import gpu_risk_score

        return server_id, {r["uuid"]: r for r in gpu_risk_score(server_id)}

    with ThreadPoolExecutor(max_workers=4) as ex:
        risks_by_srv = dict(ex.map(_risks_for, [s.id for s in servers if s.id in latest_by_srv]))

    out = []
    for s in servers:
        m = latest_by_srv.get(s.id)
        if m is None:
            continue
        risks = risks_by_srv.get(s.id, {})
        for g in (m.gpus or []):
            u = g.get("uuid")
            if not u:
                continue
            total = g.get("mem_total_mb") or 0
            util = g.get("utilization", 0) or 0
            mem = g.get("mem_used_mb") or 0
            mem_pct = (mem / total * 100) if total else 0
            idle_minutes = 0.0
            idle_held = False
            if util < 5 and total and mem_pct >= 30:
                since_iso = idle_state.get(f"{s.id}:{u}")
                if since_iso:
                    try:
                        since_dt = datetime.fromisoformat(since_iso)
                        if since_dt.tzinfo is not None:
                            since_dt = since_dt.astimezone(tz.utc).replace(tzinfo=None)
                        idle_minutes = max(
                            0.0,
                            (m.collected_at.replace(tzinfo=None) - since_dt).total_seconds() / 60,
                        )
                        idle_held = idle_minutes >= 25
                    except ValueError:
                        pass
            r = risks.get(u, {})
            out.append({
                "server_id": s.id,
                "server_name": s.name,
                "uuid": u,
                "gpu_index": g.get("index"),
                "name": r.get("name", ""),
                "util": util,
                "mem_pct": round(mem_pct, 1),
                "mem_used_gb": round(mem / 1024, 1),
                "idle_held": idle_held,
                "idle_minutes": round(idle_minutes, 0),
                "risk": r.get("risk", 0),
                "risk_label": r.get("risk_label", "健康"),
                "xid_events": r.get("xid_events", 0),
                "ecc_uncorrected": r.get("ecc_uncorrected_max", 0),
                "thermal_throttle": r.get("thermal_throttle_samples", 0),
                "max_temp": r.get("max_temp", 0),
                "processes": [
                    {"pid": p.get("pid"), "user": p.get("user", ""), "command": (p.get("command") or "")[:60]}
                    for p in (g.get("processes") or [])[:5]
                ],
            })
    out.sort(key=lambda x: (not x["idle_held"], -(x["risk"])))
    return {
        "total_gpus": len(out),
        "idle_held_count": sum(1 for x in out if x["idle_held"]),
        "high_risk_count": sum(1 for x in out if x["risk"] >= 30),
        "gpus": out,
    }

@router.get("/cluster/health-summary")
def cluster_health_summary(db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    """One line per server: overall health + open detector counts."""
    from .. import cache as app_cache

    return app_cache.cached(
        "cluster:health-summary", 15.0, lambda: _cluster_health_summary(db)
    )


def _cluster_health_summary(db: Session):
    from sqlalchemy import and_, func
    from sqlalchemy.orm import load_only

    servers = db.query(Server).filter(Server.enabled.is_(True)).all()
    sub = (
        db.query(ServerMetric.server_id, func.max(ServerMetric.collected_at).label("mx"))
        .group_by(ServerMetric.server_id)
        .subquery()
    )
    latest_map = {
        m.server_id: m
        for m in db.query(ServerMetric)
        .join(sub, and_(ServerMetric.server_id == sub.c.server_id,
                        ServerMetric.collected_at == sub.c.mx))
        .options(load_only(ServerMetric.server_id, ServerMetric.status,
                           ServerMetric.hostname, ServerMetric.error_code))
        .all()
    }
    open_counts: dict[int, list[str]] = {}
    rows = (
        db.query(AlertEvent.server_id, AlertEvent.metric)
        .filter(AlertEvent.recovered_at.is_(None), AlertEvent.rule_id.is_(None))
        .all()
    )
    for sid, metric in rows:
        open_counts.setdefault(sid, []).append(metric or "")

    out = []
    for s in servers:
        latest = latest_map.get(s.id)
        if latest is None:
            out.append({"server_id": s.id, "name": s.name, "overall": "unknown",
                        "connectivity": "unknown", "critical": 0, "warning": 0,
                        "status": s.status or "active", "tags": s.tags or []})
            continue
        sev = open_counts.get(s.id, [])
        crit = sum(1 for e in sev if "XID" in e or e in
                   ("GPU_MISSING", "GPU_ECC_UNCORRECTED", "RAID_DEGRADED", "OOM_KILL",
                    "MCE_HARDWARE_ERROR", "SSH_FAULT", "HOSTKEY_CHANGED"))
        warn = sum(1 for e in sev if e in
                   ("GPU_THERMAL_THROTTLE", "NVME_HEALTH", "NFS_STALE", "SERVICE_FAILED",
                    "PCIE_AER", "GPU_IDLE_VRAM_HELD", "STORAGE_BOTTLENECK"))
        conn = "ok" if latest.status == "ok" else "critical"
        if s.status == "maintenance":
            # maintenance hosts are excluded from cluster health judgement
            overall = "maintenance"
        else:
            overall = "critical" if (crit or latest.status != "ok") else ("warning" if warn else "ok")
        out.append({
            "server_id": s.id, "name": s.name,
            "hostname": latest.hostname, "overall": overall, "connectivity": conn,
            "critical": crit, "warning": warn,
            "status": s.status or "active", "tags": s.tags or [],
            "error_code": latest.error_code if latest.status != "ok" else "OK",
        })
    return out
