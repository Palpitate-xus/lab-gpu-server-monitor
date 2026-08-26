"""Cluster-level aggregation endpoints for the cockpit dashboard."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Server, ServerMetric, User
from ..security import get_current_user

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def _avg(vals: list[float]) -> float:
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else 0.0


def _max(vals: list[float]) -> float:
    vals = [v for v in vals if v is not None]
    return round(max(vals), 1) if vals else 0.0


def _sum(vals: list[float]) -> float:
    """Sum per-server rates (cluster total), but average duplicate samples of
    the same server inside the bucket so multi-poll runs don't double count."""
    vals = [v for v in vals if v is not None]
    return round(sum(vals), 1) if vals else 0.0


@router.get("/cluster-history")
def cluster_history(
    hours: int = Query(default=6, ge=1, le=48),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Time series of cluster-wide averages for the cockpit trend chart."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        db.query(ServerMetric)
        .filter(ServerMetric.collected_at >= since, ServerMetric.status == "ok")
        .order_by(ServerMetric.collected_at.asc())
        .all()
    )

    # group by minute bucket (HH:MM) to smooth multi-server samples
    buckets: dict[str, dict[str, list[float]]] = {}
    for m in rows:
        key = m.collected_at.strftime("%H:%M")
        b = buckets.setdefault(
            key,
            {"cpu": [], "mem": [], "gpu_util": [], "gpu_mem": [], "gpu_temp": [], "gpu_power": [],
             "net_rx": [], "net_tx": [], "disk_read": [], "disk_write": []},
        )
        b["cpu"].append(m.cpu_percent or 0)
        if m.mem_total_mb:
            b["mem"].append(m.mem_used_mb / m.mem_total_mb * 100)
        gpus = m.gpus or []
        if gpus:
            b["gpu_util"].extend(g.get("utilization", 0) or 0 for g in gpus)
            mem_pcts = [
                g["mem_used_mb"] / g["mem_total_mb"] * 100
                for g in gpus
                if g.get("mem_total_mb")
            ]
            b["gpu_mem"].extend(mem_pcts)
            b["gpu_temp"].extend(g.get("temperature", 0) or 0 for g in gpus)
            b["gpu_power"].extend(g.get("power_draw", 0) or 0 for g in gpus)
        b["net_rx"].append(m.net_rx_bytes or 0)
        b["net_tx"].append(m.net_tx_bytes or 0)
        b["disk_read"].extend(d.get("read_bps", 0) or 0 for d in (m.disk_io or []))
        b["disk_write"].extend(d.get("write_bps", 0) or 0 for d in (m.disk_io or []))

    series = []
    for key in sorted(buckets.keys()):
        b = buckets[key]
        series.append(
            {
                "time": key,
                "cpu_percent": _avg(b["cpu"]),
                "mem_percent": _avg(b["mem"]),
                "gpu_util": _avg(b["gpu_util"]),
                "gpu_mem_percent": _avg(b["gpu_mem"]),
                "gpu_temp": _max(b["gpu_temp"]),
                "gpu_power": round(sum(b["gpu_power"]) / max(1, len(set(r.server_id for r in rows))), 1) if b["gpu_power"] else 0,
                "net_bps": round(_sum(b["net_rx"]), 1),
                "net_bps_tx": round(_sum(b["net_tx"]), 1),
                "disk_bps": round(_sum(b["disk_read"]), 1),
                "disk_bps_write": round(_sum(b["disk_write"]), 1),
            }
        )
    return series


@router.get("/cluster-gpus")
def cluster_gpus(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Flat GPU inventory across all servers for the cockpit heatmap matrix."""
    servers = db.query(Server).order_by(Server.id).all()
    result = []
    for s in servers:
        m = (
            db.query(ServerMetric)
            .filter(ServerMetric.server_id == s.id)
            .order_by(ServerMetric.collected_at.desc())
            .first()
        )
        entry = {
            "server_id": s.id,
            "server_name": s.name,
            "enabled": s.enabled,
            "online": bool(m and m.status == "ok"),
            "error": m.error if (m and m.status != "ok") else "",
            "hostname": m.hostname if m else "",
            "gpus": [],
        }
        if m and m.status == "ok" and s.server_type != "cpu":
            for g in m.gpus or []:
                entry["gpus"].append(
                    {
                        "index": g.get("index", 0),
                        "name": g.get("name", ""),
                        "utilization": g.get("utilization", 0) or 0,
                        "mem_used_mb": g.get("mem_used_mb", 0) or 0,
                        "mem_total_mb": g.get("mem_total_mb", 0) or 0,
                        "temperature": g.get("temperature", 0) or 0,
                        "power_draw": g.get("power_draw", 0) or 0,
                        "power_limit": g.get("power_limit", 0) or 0,
                        "pstate": g.get("pstate", ""),
                        "processes": g.get("processes", []),
                    }
                )
        result.append(entry)
    return result
