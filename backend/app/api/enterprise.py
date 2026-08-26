"""Enterprise monitoring APIs: health tree, kernel events, slow health
(NVMe/RAID/NFS/MIG/NVLink/IPMI), inventory (DMI/NUMA/topology), GPU risk."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..security import get_current_user
from ..database import get_db
from ..health import gpu_risk_score, health_tree
from ..models import (
    AlertEvent,
    HostInventory,
    KernelEventRow,
    Server,
    ServerMetric,
    SlowHealth,
    User,
)
from ..ssh_transport import forget_hostkey

router = APIRouter(prefix="/api", tags=["enterprise"])


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
            "collected_at": r.collected_at.isoformat(),
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
            "collected_at": r.collected_at.isoformat(),
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
                  user: User = Depends(get_current_user)):
    if not user.is_admin:
        raise HTTPException(403, "admin only")
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
    return {"ok": True, "message": "host key 记录已重置，下轮采集将重新信任该主机"}


# ------------------------------------------------------------- cluster level

@router.get("/cluster/health-summary")
def cluster_health_summary(db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    """One line per server: overall health + open detector counts."""
    servers = db.query(Server).filter(Server.enabled.is_(True)).all()
    out = []
    for s in servers:
        latest = (
            db.query(ServerMetric)
            .filter(ServerMetric.server_id == s.id)
            .order_by(ServerMetric.collected_at.desc())
            .first()
        )
        if latest is None:
            out.append({"server_id": s.id, "name": s.name, "overall": "unknown",
                        "connectivity": "unknown", "critical": 0, "warning": 0})
            continue
        sev = (
            db.query(AlertEvent)
            .filter(AlertEvent.server_id == s.id, AlertEvent.recovered_at.is_(None),
                    AlertEvent.rule_id.is_(None))
            .all()
        )
        crit = sum(1 for e in sev if "XID" in (e.metric or "") or e.metric in
                   ("GPU_MISSING", "GPU_ECC_UNCORRECTED", "RAID_DEGRADED", "OOM_KILL",
                    "MCE_HARDWARE_ERROR", "SSH_FAULT", "HOSTKEY_CHANGED"))
        warn = sum(1 for e in sev if e.metric in
                   ("GPU_THERMAL_THROTTLE", "NVME_HEALTH", "NFS_STALE", "SERVICE_FAILED",
                    "PCIE_AER", "GPU_IDLE_VRAM_HELD", "STORAGE_BOTTLENECK"))
        conn = "ok" if latest.status == "ok" else "critical"
        overall = "critical" if (crit or latest.status != "ok") else ("warning" if warn else "ok")
        out.append({
            "server_id": s.id, "name": s.name,
            "hostname": latest.hostname, "overall": overall, "connectivity": conn,
            "critical": crit, "warning": warn,
            "error_code": latest.error_code if latest.status != "ok" else "OK",
        })
    return out
