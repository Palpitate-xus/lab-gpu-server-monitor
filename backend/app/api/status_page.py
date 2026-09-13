"""Public status page (Uptime-Kuma style) configuration + data.

Config lives in the settings table as one JSON blob under "status_page".
The public endpoints (/api/status-public*) require NO authentication.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as tz
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import and_, func as sa_func
from sqlalchemy.orm import Session, load_only

from ..database import get_db
from ..models import Server, ServerMetric, ServerMetricHourly, Setting, User
from ..security import require_admin

router = APIRouter(prefix="/api", tags=["status-page"])

SETTING_KEY = "status_page"

DEFAULT_CONFIG = {
    "title": "服务状态",
    "description": "实验室 GPU 集群公开状态页",
    "server_ids": [],            # empty = all enabled servers
    "show_history_days": 45,     # uptime bar chart days
    "show_latency": True,
    "show_gpu": True,
    "theme": "auto",             # auto | light | dark
    "footer": "Powered by lab-gpu-server-monitor",
    "published": False,          # must be explicitly turned on
}


# ---------------- config models ----------------
class StatusPageConfig(BaseModel):
    title: str = Field(default="服务状态", max_length=120)
    description: str = Field(default="", max_length=500)
    server_ids: list[int] = Field(default=[])
    show_history_days: int = Field(default=45, ge=1, le=365)
    show_latency: bool = True
    show_gpu: bool = True
    theme: str = Field(default="auto", pattern="^(auto|light|dark)$")
    footer: str = Field(default="", max_length=300)
    published: bool = False


def _load_config(db: Session) -> dict:
    row = db.get(Setting, SETTING_KEY)
    if row and row.value:
        import json
        try:
            cfg = json.loads(row.value)
        except Exception:
            cfg = {}
        merged = {**DEFAULT_CONFIG, **cfg}
        return merged
    return dict(DEFAULT_CONFIG)


def _save_config(db: Session, cfg: dict) -> None:
    import json
    row = db.get(Setting, SETTING_KEY)
    if row:
        row.value = json.dumps(cfg)
    else:
        db.add(Setting(key=SETTING_KEY, value=json.dumps(cfg)))
    db.commit()


# ---------------- admin endpoints ----------------
@router.get("/status-page/config")
def get_config(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    cfg = _load_config(db)
    servers = (
        db.query(Server)
        .options(load_only(Server.id, Server.name, Server.enabled, Server.server_type))
        .order_by(Server.id)
        .all()
    )
    return {
        "config": cfg,
        "available_servers": [
            {"id": s.id, "name": s.name, "enabled": s.enabled, "server_type": s.server_type}
            for s in servers
        ],
    }


@router.put("/status-page/config")
def put_config(body: StatusPageConfig, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _save_config(db, body.model_dump())
    from .. import cache as app_cache

    app_cache.invalidate_prefix("status:")
    return {"ok": True}


@router.get("/status-page/preview")
def preview_payload(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Admin-only preview identical to /api/status-public, ignoring the
    published flag: previewing must not require going live."""
    cfg = _load_config(db)
    return _build_public_payload(db, cfg)


# ---------------- public data ----------------
def _bucketize(days: int, now):
    """Return list of (start, end) UTC day buckets, oldest first."""
    buckets = []
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for i in range(days - 1, -1, -1):
        start = today - timedelta(days=i)
        buckets.append((start, start + timedelta(days=1)))
    return buckets


@router.get("/status-public")
def status_public(db: Session = Depends(get_db)):
    cfg = _load_config(db)
    if not cfg.get("published"):
        return {"published": False}
    from .. import cache as app_cache

    return app_cache.cached(
        "status:public", 30.0, lambda: _build_public_payload(db, cfg)
    )


def _build_public_payload(db: Session, cfg: dict) -> dict:
    days = int(cfg.get("show_history_days", 45))
    now = datetime.now(tz.utc).replace(tzinfo=None)
    buckets = _bucketize(days, now)

    q = db.query(Server).filter(Server.enabled.is_(True))
    ids = cfg.get("server_ids") or []
    if ids:
        q = q.filter(Server.id.in_(ids))
    servers = (
        q.options(load_only(Server.id, Server.name, Server.server_type))
        .order_by(Server.id)
        .all()
    )

    server_ids = [server.id for server in servers]
    totals_by_server: dict[int, dict] = {}
    latest_by_server = {}
    day_counts: dict[tuple[int, str], dict[str, int]] = {}
    if server_ids:
        # Uptime counts come from the hourly rollup: one row per server-hour
        # instead of ~18k raw rows per server-day. Two grouped scans of the raw
        # table over the history window cost ~8s in production. The scheduler
        # only closes out the previous completed hour, so the in-flight hour is
        # absent here and a newly added server has no history until it closes.
        rollup_day = sa_func.date(ServerMetricHourly.hour).label("d")
        rollup_rows = (
            db.query(
                ServerMetricHourly.server_id,
                rollup_day,
                sa_func.sum(ServerMetricHourly.samples),
                sa_func.sum(ServerMetricHourly.ok_samples),
            )
            .filter(
                ServerMetricHourly.server_id.in_(server_ids),
                ServerMetricHourly.hour >= buckets[0][0],
            )
            .group_by(ServerMetricHourly.server_id, rollup_day)
            .all()
        )
        for server_id, day, samples, ok_samples in rollup_rows:
            key = day if isinstance(day, str) else day.strftime("%Y-%m-%d")
            total = int(samples or 0)
            ok = int(ok_samples or 0)
            day_counts[(server_id, key)] = {"total": total, "ok": ok}
            summary = totals_by_server.setdefault(
                server_id, {"total": 0, "ok": 0, "avg_latency": 0}
            )
            summary["total"] += total
            summary["ok"] += ok

        latest_times = (
            db.query(
                ServerMetric.server_id,
                sa_func.max(ServerMetric.collected_at).label("latest_at"),
            )
            .filter(ServerMetric.server_id.in_(server_ids))
            .group_by(ServerMetric.server_id)
            .subquery()
        )
        latest_rows = (
            db.query(ServerMetric)
            .options(load_only(
                ServerMetric.id,
                ServerMetric.server_id,
                ServerMetric.status,
                ServerMetric.gpus,
                ServerMetric.collected_at,
            ))
            .join(
                latest_times,
                and_(
                    ServerMetric.server_id == latest_times.c.server_id,
                    ServerMetric.collected_at == latest_times.c.latest_at,
                ),
            )
            .order_by(ServerMetric.server_id, ServerMetric.id)
            .all()
        )
        # A timestamp tie is rare; choosing the last inserted row makes the
        # result deterministic while retaining one latest row per server.
        latest_by_server = {row.server_id: row for row in latest_rows}

        # The rollup carries no latency column, so average it over a bounded
        # recent window; scanning the full history for it cost ~2.8s alone.
        latency_rows = (
            db.query(
                ServerMetric.server_id,
                sa_func.avg(ServerMetric.ssh_latency),
            )
            .filter(
                ServerMetric.server_id.in_(server_ids),
                ServerMetric.collected_at >= now - timedelta(hours=24),
                ServerMetric.status == "ok",
            )
            .group_by(ServerMetric.server_id)
            .all()
        )
        for server_id, avg_latency in latency_rows:
            totals_by_server.setdefault(
                server_id, {"total": 0, "ok": 0, "avg_latency": 0}
            )["avg_latency"] = avg_latency or 0

    result = []
    for s in servers:
        summary = totals_by_server.get(s.id, {})
        total = summary.get("total", 0)
        ok = summary.get("ok", 0)
        avg_latency = summary.get("avg_latency", 0)
        latest = latest_by_server.get(s.id)

        history = []
        for start, _end in buckets:
            key = start.strftime("%Y-%m-%d")
            counts = day_counts.get((s.id, key))
            if not counts:
                history.append({"date": key, "uptime": None, "n": 0})
                continue
            history.append({
                "date": key,
                "uptime": round(counts["ok"] / counts["total"] * 100, 1),
                "n": counts["total"],
            })

        gpus = []
        if latest and latest.status == "ok" and s.server_type != "cpu":
            for g in (latest.gpus or []):
                mem_total = g.get("mem_total_mb") or 0
                mem_used = g.get("mem_used_mb") or 0
                gpus.append({
                    "index": g.get("index", 0),
                    "name": (g.get("name") or "").replace("NVIDIA ", "").replace("GeForce ", ""),
                    "util": g.get("utilization", 0) or 0,
                    "mem_pct": round(mem_used / mem_total * 100, 0) if mem_total else 0,
                })

        result.append({
            "id": s.id,
            "name": s.name,
            "server_type": s.server_type,
            "online": bool(latest and latest.status == "ok"),
            "uptime_30d": round(ok / total * 100, 2) if total else None,
            "avg_latency_ms": round((avg_latency or 0) * 1000, 0),
            "last_check": latest.collected_at.isoformat() if latest else None,
            "history": history,
            "gpus": gpus,
        })

    overall = {
        "all_operational": all(r["online"] for r in result) if result else True,
        "servers_total": len(result),
        "servers_online": sum(1 for r in result if r["online"]),
    }
    return {
        # Always True here: the public endpoint gates on the config flag before
        # calling, and the admin preview must return a render-ready payload.
        "published": True,
        "title": cfg.get("title", ""),
        "description": cfg.get("description", ""),
        "footer": cfg.get("footer", ""),
        "theme": cfg.get("theme", "auto"),
        "show_latency": cfg.get("show_latency", True),
        "show_gpu": cfg.get("show_gpu", True),
        "overall": overall,
        "servers": result,
        "generated_at": now.isoformat(),
    }
