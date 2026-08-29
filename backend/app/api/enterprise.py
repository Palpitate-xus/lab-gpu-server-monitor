"""Enterprise monitoring APIs: health tree, kernel events, slow health
(NVMe/RAID/NFS/MIG/NVLink/IPMI), inventory (DMI/NUMA/topology), GPU risk."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..security import get_current_user, require_admin
from ..database import get_db
from ..health import gpu_risk_score, health_tree
from ..models import (
    AlertEvent,
    AuditLog,
    HostInventory,
    KernelEventRow,
    Server,
    ServerMetric,
    SlowHealth,
    User,
)
from ..ssh_transport import forget_hostkey

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
                       user: User = Depends(get_current_user)):
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
                     user: User = Depends(get_current_user)):
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
def reset_hostkey(server_id: int, db: Session = Depends(get_db),
                  user: User = Depends(require_admin)):
    server = db.get(Server, server_id)
    if server is None:
        raise HTTPException(404, "server not found")
    forget_hostkey(f"server_{server_id}")
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
    db.commit()
    try:
        db.add(AuditLog(username=user.username, action="server.reset_hostkey",
                        detail=f"server {server.name} ({server.host})"))
        db.commit()
    except Exception:
        db.rollback()
    return {"ok": True, "message": "host key 记录已重置，下轮采集将重新信任该主机"}


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

    return app_cache.cached(
        "cluster:gpu-analysis", 300.0, lambda: _gpu_analysis(db)
    )


def _gpu_analysis(db: Session):
    from datetime import datetime, timedelta, timezone as tz
    from sqlalchemy.orm import load_only
    from ..health import gpu_risk_score

    servers = db.query(Server).filter(Server.enabled.is_(True), Server.server_type != "cpu").all()
    if not servers:
        return {"total_gpus": 0, "idle_held_count": 0, "high_risk_count": 0, "gpus": []}

    sids = [s.id for s in servers]

    def load_pairs(wmin: int) -> dict[int, list]:
        """Per server: ascending list of (collected_at, slim_gpu_dicts).

        MySQL extracts only the five scalars the idle math needs straight in
        the DB (JSON_EXTRACT); transferring whole gpus blobs for a widened
        window was ~15x slower."""
        since = datetime.now(tz.utc) - timedelta(minutes=wmin)
        pairs: dict[int, list] = {sid: [] for sid in sids}
        if db.bind.dialect.name == "mysql":
            from sqlalchemy import bindparam, text
            rows = db.execute(
                text(
                    """
                    SELECT server_id, collected_at,
                           JSON_EXTRACT(gpus, '$[*].uuid')         AS uuids,
                           JSON_EXTRACT(gpus, '$[*].index')        AS idxs,
                           JSON_EXTRACT(gpus, '$[*].utilization')  AS utils,
                           JSON_EXTRACT(gpus, '$[*].mem_used_mb')  AS mems,
                           JSON_EXTRACT(gpus, '$[*].mem_total_mb') AS totals
                    FROM server_metrics
                    WHERE server_id IN :ids
                      AND collected_at >= :since AND status = 'ok'
                    ORDER BY server_id, collected_at
                    """
                ).bindparams(bindparam("ids", expanding=True)),
                {"ids": sids, "since": since.replace(tzinfo=None)},
            )
            import json as _json
            for sid, t, u, i, ut, me, to in rows:
                us = _json.loads(u) if u else []
                if not us:
                    continue
                is_ = _json.loads(i) if i else []
                uts = _json.loads(ut) if ut else []
                mes = _json.loads(me) if me else []
                tos = _json.loads(to) if to else []
                for k, uuid in enumerate(us):
                    if not uuid:
                        continue
                    pairs[sid].append((t, {
                        "uuid": uuid,
                        "index": is_[k] if k < len(is_) else None,
                        "utilization": (uts[k] or 0) if k < len(uts) else 0,
                        "mem_used_mb": (mes[k] or 0) if k < len(mes) else 0,
                        "mem_total_mb": (tos[k] or 0) if k < len(tos) else 0,
                    }))
        else:
            for sid in sids:
                rows = (
                    db.query(ServerMetric)
                    .options(load_only(ServerMetric.gpus, ServerMetric.collected_at, ServerMetric.status))
                    .filter(ServerMetric.server_id == sid,
                            ServerMetric.collected_at >= since,
                            ServerMetric.status == "ok")
                    .order_by(ServerMetric.collected_at.asc())
                    .all()
                )
                pairs[sid] = [(m.collected_at, m.gpus or []) for m in rows]
        return pairs

    def build_samples(pairs_by_srv: dict[int, list]):
        """Per-server, per-GPU-uuid sample timeline; returns (samples, oldest_t)."""
        out: dict[int, tuple[dict[str, list[dict]], dict[str, int], datetime]] = {}
        for sid, pairs in pairs_by_srv.items():
            if not pairs:
                continue
            uuids: dict[str, list[dict]] = {}
            index_map: dict[str, int] = {}
            for t, g in pairs:
                u = g.get("uuid")
                if not u:
                    continue
                index_map[u] = g.get("index")
                uuids.setdefault(u, []).append({
                    "t": t.replace(tzinfo=None) if t.tzinfo is None
                         else t.astimezone(tz.utc).replace(tzinfo=None),
                    "util": g.get("utilization", 0) or 0,
                    "mem": g.get("mem_used_mb", 0) or 0,
                    "total": g.get("mem_total_mb", 0) or 0,
                })
            out[sid] = (uuids, index_map, pairs[0][0])
        return out

    # Adaptive lookback: a fixed window silently caps the reported idle
    # duration (a GPU idle for days used to show "~1h29m"). Start small and
    # widen only while some trailing idle run still reaches the window edge.
    WINDOW_STEPS = [180, 1440, 4320, 10080]  # 3h, 24h, 72h, 7d
    samples_by_srv = {}
    for wmin in WINDOW_STEPS:
        pairs_by_srv = load_pairs(wmin)
        samples_by_srv = build_samples(pairs_by_srv)
        if wmin == WINDOW_STEPS[-1]:
            break
        edge_hit = False
        for sid, (uuids, _idx, oldest_t) in samples_by_srv.items():
            # only widen if data actually exists at the window edge; a server
            # that was offline has no older samples anyway
            if (datetime.now(timezone.utc) - oldest_t.replace(tzinfo=timezone.utc)).total_seconds() < wmin * 60 - 180:
                continue
            for u, sams in uuids.items():
                if not sams:
                    continue
                last = sams[-1]
                total = last["total"]
                if total and last["util"] < 5 and last["mem"] / total * 100 >= 30:
                    first = sams[0]
                    if first["util"] < 5 and first["mem"] / (first["total"] or 1) * 100 >= 30:
                        edge_hit = True
                        break
            if edge_hit:
                break
        if not edge_hit:
            break

    # newest row per server, only for the displayed process lists
    from sqlalchemy import and_, func as sa_func
    latest_gpu_by_srv: dict[int, dict] = {}
    sub = (
        db.query(ServerMetric.server_id, sa_func.max(ServerMetric.collected_at).label("mx"))
        .filter(ServerMetric.server_id.in_(sids))
        .group_by(ServerMetric.server_id)
        .subquery()
    )
    for m in (
        db.query(ServerMetric)
        .options(load_only(ServerMetric.server_id, ServerMetric.gpus))
        .join(sub, and_(ServerMetric.server_id == sub.c.server_id,
                        ServerMetric.collected_at == sub.c.mx))
        .all()
    ):
        latest_gpu_by_srv[m.server_id] = {
            g.get("uuid"): g for g in (m.gpus or []) if g.get("uuid")
        }

    out = []
    srv_by_id = {s.id: s for s in servers}
    for sid, (uuids, index_map, _oldest) in samples_by_srv.items():
        s = srv_by_id[sid]
        risks = {r["uuid"]: r for r in gpu_risk_score(s.id)}
        for u, samples in uuids.items():
            last = samples[-1]
            mem_pct = (last["mem"] / last["total"] * 100) if last["total"] else 0
            idle_minutes = 0.0
            idle_held = False
            if mem_pct >= 30:
                n_idle = 0
                for sm in reversed(samples):
                    mp = (sm["mem"] / sm["total"] * 100) if sm["total"] else 0
                    if sm["util"] < 5 and mp >= 30:
                        n_idle += 1
                    else:
                        break
                if n_idle >= 5:
                    t_end = samples[-1]["t"]
                    t_start = samples[len(samples) - n_idle]["t"]
                    idle_minutes = max(0.0, (t_end - t_start).total_seconds() / 60)
                    idle_held = idle_minutes >= 25
            r = risks.get(u, {})
            out.append({
                "server_id": s.id,
                "server_name": s.name,
                "uuid": u,
                "gpu_index": index_map.get(u),
                "name": r.get("name", ""),
                "util": last["util"],
                "mem_pct": round(mem_pct, 1),
                "mem_used_gb": round(last["mem"] / 1024, 1),
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
                    for p in (latest_gpu_by_srv.get(sid, {}).get(u, {}).get("processes") or [])[:5]
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
