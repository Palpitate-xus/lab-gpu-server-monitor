"""Cluster-level aggregation endpoints for the cockpit dashboard."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, load_only

from ..database import get_db
from ..models import Server, ServerMetric, Setting, User
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
        .options(load_only(
            ServerMetric.server_id, ServerMetric.collected_at,
            ServerMetric.cpu_percent, ServerMetric.mem_used_mb, ServerMetric.mem_total_mb,
            ServerMetric.gpus, ServerMetric.net_rx_bytes, ServerMetric.net_tx_bytes,
            ServerMetric.disk_io,
        ))
        .filter(ServerMetric.collected_at >= since, ServerMetric.status == "ok")
        .order_by(ServerMetric.collected_at.asc())
        .all()
    )

    # group by minute bucket; the key must include the date or 48h windows
    # merge same-clock-time samples across days and sort wrong over midnight
    buckets: dict[str, dict] = {}
    for m in rows:
        key = m.collected_at.strftime("%Y-%m-%d %H:%M")
        b = buckets.setdefault(
            key,
            {"cpu": [], "mem": [], "gpu_util": [], "gpu_mem": [], "gpu_temp": [], "gpu_power": [],
             "net_rx": [], "net_tx": [], "disk_read": [], "disk_write": [], "servers": set(),
             "minute": m.collected_at.replace(second=0, microsecond=0)},
        )
        b["servers"].add(m.server_id)
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
        # gauge metrics must be averaged per server inside a bucket, else a
        # server sampled twice in one minute gets double-counted in the sum
        b.setdefault("gpu_power_by_srv", {}).setdefault(m.server_id, []).append(
            sum(g.get("power_draw", 0) or 0 for g in gpus)
        )
        b["net_rx"].append(m.net_rx_bytes or 0)
        b["net_tx"].append(m.net_tx_bytes or 0)
        b["disk_read"].extend(d.get("read_bps", 0) or 0 for d in (m.disk_io or []))
        b["disk_write"].extend(d.get("write_bps", 0) or 0 for d in (m.disk_io or []))

    series = []
    for key in sorted(buckets.keys()):
        b = buckets[key]
        minute = b["minute"]
        if minute.tzinfo is None:
            minute = minute.replace(tzinfo=timezone.utc)
        series.append(
            {
                "time": minute.isoformat().replace("+00:00", "Z"),
                "cpu_percent": _avg(b["cpu"]),
                "mem_percent": _avg(b["mem"]),
                "gpu_util": _avg(b["gpu_util"]),
                "gpu_mem_percent": _avg(b["gpu_mem"]),
                "gpu_temp": _max(b["gpu_temp"]),
                # cluster TOTAL power: mean per server (de-dup within bucket), then sum
                "gpu_power": round(sum(
                    sum(v) / len(v) for v in b.get("gpu_power_by_srv", {}).values()
                ), 1),
                "net_bps": round(_sum(b["net_rx"]), 1),
                "net_bps_tx": round(_sum(b["net_tx"]), 1),
                "disk_bps": round(_sum(b["disk_read"]), 1),
                "disk_bps_write": round(_sum(b["disk_write"]), 1),
            }
        )
    return series


@router.get("/cluster-power-now")
def cluster_power_now(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Current total GPU power draw (W) across the cluster (latest sample per server)."""
    latest_ids = (
        db.query(ServerMetric.server_id, func.max(ServerMetric.id))
        .filter(ServerMetric.status == "ok")
        .group_by(ServerMetric.server_id)
        .all()
    )
    total = 0.0
    servers = 0
    for sid, mid in latest_ids:
        m = db.get(ServerMetric, mid)
        if m and m.gpus:
            w = sum(g.get("power_draw", 0) or 0 for g in m.gpus)
            if w:
                total += w
                servers += 1
    return {"total_w": round(total, 1), "servers_reporting": servers}


@router.get("/cluster-energy")
def cluster_energy(
    days: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Daily GPU energy consumption (kWh) for the whole cluster.

    Energy per day = mean power (W) of that day's samples x 24h / 1000.
    Also returns an estimated cost when a price is configured (yuan/kWh).
    """
    since = datetime.now(timezone.utc) - timedelta(days=days + 1)
    rows = (
        db.query(ServerMetric)
        .options(load_only(ServerMetric.server_id, ServerMetric.collected_at, ServerMetric.gpus))
        .filter(ServerMetric.collected_at >= since, ServerMetric.status == "ok")
        .order_by(ServerMetric.collected_at.asc())
        .all()
    )
    # per-day per-server watt samples; a server's daily mean is weighted
    # equally regardless of how many samples it managed to report
    day_samples: dict[str, dict[int, list[float]]] = {}
    for m in rows:
        watts = sum(g.get("power_draw", 0) or 0 for g in (m.gpus or []))
        day = m.collected_at.strftime("%Y-%m-%d")
        day_samples.setdefault(day, {}).setdefault(m.server_id, []).append(watts)

    # price config from settings (admin editable on settings page)
    price_row = db.get(Setting, "energy_price")
    price = float(price_row.value) if price_row and price_row.value else 0.0

    out = []
    for day in sorted(day_samples.keys()):
        by_srv = day_samples[day]
        if not by_srv:
            continue
        srv_means = [sum(v) / len(v) for v in by_srv.values()]
        peak_w = max(max(v) for v in by_srv.values())
        n = sum(len(v) for v in by_srv.values())
        mean_w = sum(srv_means)  # cluster total = sum of per-server means
        # coverage: fraction of the day that has samples (accuracy note)
        coverage = min(1.0, n / (1440 * max(1, len(by_srv))))
        kwh = mean_w * 24 / 1000
        out.append({
            "date": day,
            "samples": n,
            "coverage": round(coverage, 2),
            "avg_w": round(mean_w, 1),
            "peak_w": round(peak_w, 1),
            "kwh": round(kwh, 2),
            "cost": round(kwh * price, 2) if price else None,
        })
    total_kwh = round(sum(d["kwh"] for d in out), 1)
    return {
        "days": out,
        "total_kwh": total_kwh,
        "avg_kwh_per_day": round(total_kwh / len(out), 2) if out else 0,
        "price": price,
        "total_cost": round(total_kwh * price, 2) if price else None,
    }


@router.get("/cluster-gpus")
def cluster_gpus(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Flat GPU inventory across all servers for the cockpit heatmap matrix."""
    from sqlalchemy import and_, func

    servers = db.query(Server).order_by(Server.id).all()
    sub = (
        db.query(ServerMetric.server_id, func.max(ServerMetric.collected_at).label("mx"))
        .group_by(ServerMetric.server_id)
        .subquery()
    )
    latest = {
        m.server_id: m
        for m in db.query(ServerMetric)
        .join(sub, and_(ServerMetric.server_id == sub.c.server_id,
                        ServerMetric.collected_at == sub.c.mx))
        .all()
    }
    result = []
    for s in servers:
        m = latest.get(s.id)
        entry = {
            "server_id": s.id,
            "server_name": s.name,
            "enabled": s.enabled,
            "status": s.status or "active",
            "tags": s.tags or [],
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
