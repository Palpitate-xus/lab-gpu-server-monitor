from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, Server, ServerMetric, User
from ..schemas import DashboardStats, MetricOut, ProcessAction
from ..security import decrypt_text, get_current_user, require_admin
from ..ssh_collector import live_processes, remote_command
from .. import scheduler

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def _latest_by_server(db: Session) -> dict[int, ServerMetric]:
    """One query for the newest metric row of every server (no N+1)."""
    sub = (
        db.query(ServerMetric.server_id, func.max(ServerMetric.collected_at).label("mx"))
        .group_by(ServerMetric.server_id)
        .subquery()
    )
    rows = (
        db.query(ServerMetric)
        .join(
            sub,
            and_(
                ServerMetric.server_id == sub.c.server_id,
                ServerMetric.collected_at == sub.c.mx,
            ),
        )
        .all()
    )
    return {m.server_id: m for m in rows}


@router.get("/dashboard", response_model=DashboardStats)
def dashboard(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    servers = db.query(Server).all()
    stats = DashboardStats()
    stats.servers_total = len(servers)
    stats.servers_disabled = sum(1 for s in servers if not s.enabled)

    mem_total = mem_used = 0.0
    disk_total = disk_used = 0.0
    gpu_mem_total = gpu_mem_used = 0.0
    cpu_vals: list[float] = []
    gpu_utils: list[float] = []
    online = 0
    error = 0
    latest = _latest_by_server(db)
    for s in servers:
        m = latest.get(s.id)
        if m is None or m.status != "ok":
            if m is not None and m.status == "error":
                error += 1
            continue
        online += 1
        cpu_vals.append(m.cpu_percent or 0)
        mem_total += m.mem_total_mb or 0
        mem_used += m.mem_used_mb or 0
        disk_total += m.disk_total_gb or 0
        disk_used += m.disk_used_gb or 0
        for g in m.gpus or []:
            stats.gpus_total += 1
            gpu_mem_total += g.get("mem_total_mb", 0) or 0
            gpu_mem_used += g.get("mem_used_mb", 0) or 0
            util = g.get("utilization", 0)
            if isinstance(util, (int, float)):
                gpu_utils.append(util)
    stats.servers_online = online
    stats.servers_error = error
    stats.avg_cpu_percent = round(sum(cpu_vals) / len(cpu_vals), 1) if cpu_vals else 0
    stats.avg_gpu_util = round(sum(gpu_utils) / len(gpu_utils), 1) if gpu_utils else 0
    stats.mem_total_mb = round(mem_total, 1)
    stats.mem_used_mb = round(mem_used, 1)
    stats.disk_total_gb = round(disk_total, 1)
    stats.disk_used_gb = round(disk_used, 1)
    stats.gpu_mem_total_mb = round(gpu_mem_total, 1)
    stats.gpu_mem_used_mb = round(gpu_mem_used, 1)
    return stats


@router.get("/latest", response_model=list[MetricOut])
def latest_metrics(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    servers = db.query(Server).order_by(Server.id).all()
    latest = _latest_by_server(db)
    out = []
    for s in servers:
        m = latest.get(s.id)
        if m is not None:
            out.append(m)
    return out


@router.get("/server/{server_id}/latest", response_model=MetricOut)
def server_latest(server_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    m = (
        db.query(ServerMetric)
        .filter(ServerMetric.server_id == server_id)
        .order_by(ServerMetric.collected_at.desc())
        .first()
    )
    if m is None:
        raise HTTPException(status_code=404, detail="No metrics for this server yet")
    return m


@router.get("/server/{server_id}/history")
def server_history(
    server_id: int,
    hours: int = Query(default=3, ge=1, le=168, description="1-168h raw points"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from sqlalchemy.orm import load_only

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        db.query(ServerMetric)
        .options(load_only(
            ServerMetric.collected_at, ServerMetric.status,
            ServerMetric.cpu_percent, ServerMetric.mem_used_mb, ServerMetric.mem_total_mb,
            ServerMetric.swap_used_mb, ServerMetric.swap_total_mb,
            ServerMetric.disks, ServerMetric.net_ifaces, ServerMetric.disk_io,
            ServerMetric.gpus, ServerMetric.load1, ServerMetric.cpu_count,
        ))
        .filter(ServerMetric.server_id == server_id, ServerMetric.collected_at >= since)
        .order_by(ServerMetric.collected_at.asc())
        .all()
    )
    # downsample long windows to ~720 points (frontend charts do not need more)
    stride = max(1, len(rows) // 720)
    series = []
    for idx, m in enumerate(rows):
        if m.status != "ok" or idx % stride:
            continue
        gpus = m.gpus or []
        utils = [g.get("utilization", 0) or 0 for g in gpus]
        gpu_util = round(sum(utils) / len(utils), 1) if utils else 0
        mem_pcts = []
        temps = []
        powers = []
        clocks = []
        for g in gpus:
            total = g.get("mem_total_mb", 0) or 0
            used = g.get("mem_used_mb", 0) or 0
            if total > 0:
                mem_pcts.append(used / total * 100)
            t = g.get("temperature", 0) or 0
            if t:
                temps.append(t)
            p = g.get("power_draw", 0) or 0
            if p:
                powers.append(p)
            c = g.get("clock_graphics", 0) or 0
            if c:
                clocks.append(c)
        mem_pct = (m.mem_used_mb / m.mem_total_mb * 100) if m.mem_total_mb else 0
        swap_pct = (m.swap_used_mb / m.swap_total_mb * 100) if m.swap_total_mb else 0
        disk_pcts = [d.get("percent", 0) or 0 for d in (m.disks or [])]
        net_rx = sum(i.get("rx_bps", 0) or 0 for i in (m.net_ifaces or []))
        net_tx = sum(i.get("tx_bps", 0) or 0 for i in (m.net_ifaces or []))
        disk_r = sum(d.get("read_bps", 0) or 0 for d in (m.disk_io or []))
        disk_w = sum(d.get("write_bps", 0) or 0 for d in (m.disk_io or []))
        series.append(
            {
                "time": (
                    m.collected_at.replace(tzinfo=timezone.utc)
                    if m.collected_at.tzinfo is None else m.collected_at
                ).isoformat(),
                "cpu_percent": m.cpu_percent,
                "mem_percent": round(mem_pct, 1),
                "swap_percent": round(swap_pct, 1),
                "disk_percent": round(max(disk_pcts), 1) if disk_pcts else 0,
                "gpu_util": gpu_util,
                "gpu_mem_percent": round(sum(mem_pcts) / len(mem_pcts), 1) if mem_pcts else 0,
                "gpu_mem_used_mb": round(sum(g.get("mem_used_mb", 0) or 0 for g in gpus), 1),
                "gpu_temp": round(max(temps), 1) if temps else 0,
                "gpu_power": round(sum(powers), 1) if powers else 0,
                "gpu_clock": round(sum(clocks) / len(clocks)) if clocks else 0,
                "load1": m.load1,
                "load_per_core": round(m.load1 / m.cpu_count, 2) if m.cpu_count else 0,
                "net_rx_bps": round(net_rx, 1),
                "net_tx_bps": round(net_tx, 1),
                "disk_read_bps": round(disk_r, 1),
                "disk_write_bps": round(disk_w, 1),
            }
        )
    return series


@router.post("/refresh")
def refresh_now(_: User = Depends(require_admin)):
    started = scheduler.trigger_poll()
    if not started:
        raise HTTPException(status_code=409, detail="采集周期正在运行，请稍后再试")
    return {"ok": True, "status": scheduler.scheduler_status()}


# ---------------- live processes / process actions (btop parity) ----------------

import threading
import time as _time

_procs_cache: dict[int, tuple[float, dict]] = {}
_procs_lock = threading.Lock()
_PROCS_TTL = 10.0


@router.get("/server/{server_id}/processes")
def server_processes(
    server_id: int,
    sort: str = Query(default="cpu", pattern="^(cpu|mem|pid|time)$"),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fresh process table fetched live over SSH (not from history)."""
    with _procs_lock:
        hit = _procs_cache.get(server_id)
        if hit and _time.monotonic() - hit[0] < _PROCS_TTL:
            return hit[1]
    server = db.get(Server, server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    ok, data = live_processes(
        host=server.host,
        port=server.port or 22,
        username=server.username,
        password_enc=server.password or "",
        private_key_enc=server.private_key or "",
        passphrase_enc=server.passphrase or "",
        sort=sort,
    )
    if not ok:
        raise HTTPException(status_code=502, detail=str(data))
    payload = {"processes": data, "count": len(data)}
    with _procs_lock:
        _procs_cache[server_id] = (_time.monotonic(), payload)
    return payload


@router.post("/server/{server_id}/processes/action")
def process_action(
    server_id: int,
    body: ProcessAction,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Kill or renice a process on the remote server (admin only)."""
    server = db.get(Server, server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    sig = "".join(c for c in body.signal.upper() if c.isalnum()) or "TERM"
    if body.action == "kill":
        command = f"kill -{sig} {body.pid}"
    else:
        command = f"renice {body.nice} -p {body.pid}"

    ok, msg = remote_command(
        host=server.host,
        port=server.port or 22,
        username=server.username,
        password_enc=server.password or "",
        private_key_enc=server.private_key or "",
        passphrase_enc=server.passphrase or "",
        command=command,
    )
    try:
        db.add(
            AuditLog(
                username=admin.username,
                action=f"process.{body.action}",
                detail=f"{server.name}: {command} -> {'ok' if ok else msg}",
            )
        )
        db.commit()
    except Exception:
        db.rollback()
    if not ok:
        raise HTTPException(status_code=502, detail=msg)
    return {"ok": True, "message": msg}
