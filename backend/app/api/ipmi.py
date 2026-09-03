"""IPMI (out-of-band BMC) API: latest full snapshot, power history, live test."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, load_only

from ..database import get_db
from ..ipmi_collector import collect_ipmi, ipmitool_available, summarize
from ..models import AuditLog, IpmiSnapshot, Server, User
from ..security import decrypt_text, get_current_user, require_admin

router = APIRouter(prefix="/api/servers/{server_id}/ipmi", tags=["ipmi"])


def _server_or_404(db: Session, server_id: int) -> Server:
    server = db.get(Server, server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return server


def _bmc_creds(server: Server) -> tuple[str, str, str]:
    if not server.bmc_host:
        raise HTTPException(status_code=400, detail="该服务器未配置 BMC 带外管理地址")
    return server.bmc_host, server.bmc_user, decrypt_text(server.bmc_password or "")


def _snap_to_dict(s: IpmiSnapshot) -> dict:
    return {
        "id": s.id,
        "server_id": s.server_id,
        "collected_at": s.collected_at,
        "ok": s.ok,
        "error": s.error,
        "mc_info": s.mc_info,
        "chassis": s.chassis,
        "power": s.power,
        "sensors": s.sensors,
        "sel": s.sel,
        "sel_info": s.sel_info,
        "fru": s.fru,
        "lan": s.lan,
        "duration": s.duration,
    }


@router.get("/latest")
def ipmi_latest(server_id: int, db: Session = Depends(get_db),
                _: User = Depends(require_admin)):
    """Full most-recent IPMI dump + derived summary."""
    _server_or_404(db, server_id)
    s = (
        db.query(IpmiSnapshot)
        .filter(IpmiSnapshot.server_id == server_id)
        .order_by(IpmiSnapshot.collected_at.desc())
        .first()
    )
    if s is None:
        return {"available": ipmitool_available(), "snapshot": None, "summary": None}
    snap = _snap_to_dict(s)
    return {
        "available": ipmitool_available(),
        "snapshot": snap,
        "summary": summarize(snap),
    }


@router.get("/history")
def ipmi_history(
    server_id: int,
    hours: int = Query(default=24, ge=1, le=720),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Power draw + reachability trend for charts."""
    from ..ipmi_collector import summarize as _sum

    _server_or_404(db, server_id)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        db.query(IpmiSnapshot)
        .options(load_only(
            IpmiSnapshot.collected_at,
            IpmiSnapshot.ok,
            IpmiSnapshot.chassis,
            IpmiSnapshot.power,
        ))
        .filter(IpmiSnapshot.server_id == server_id,
                IpmiSnapshot.collected_at >= since)
        .order_by(IpmiSnapshot.collected_at.asc())
        .execution_options(stream_results=True)
        .yield_per(500)
    )
    out = []
    for s in rows:
        summ = _sum({"chassis": s.chassis or {}, "power": s.power or {}})
        out.append({
            "time": (s.collected_at.replace(tzinfo=timezone.utc)
                     if s.collected_at.tzinfo is None else s.collected_at).isoformat(),
            "ok": s.ok,
            "power_on": summ["power_on"],
            "power_w": summ["power_w"],
        })
    return out


@router.post("/test")
def ipmi_test(server_id: int, db: Session = Depends(get_db),
              admin: User = Depends(require_admin)):
    """Live connectivity test: runs a full collection now and stores it."""
    server = _server_or_404(db, server_id)
    host, user, pwd = _bmc_creds(server)
    res = collect_ipmi(host, user, pwd)
    summ = summarize(res)
    snap = IpmiSnapshot(
        server_id=server.id,
        collected_at=datetime.now(timezone.utc),
        ok=res.get("ok", False),
        error=res.get("error", ""),
        mc_info=res.get("mc_info", {}),
        chassis=res.get("chassis", {}),
        power=res.get("power", {}),
        sensors=res.get("sensors", []),
        sel=res.get("sel", []),
        sel_info=res.get("sel_info", {}),
        fru=res.get("fru", []),
        lan=res.get("lan", {}),
        power_w=float(summ["power_w"]),
        duration=res.get("duration", 0),
    )
    db.add(snap)
    try:
        db.add(AuditLog(username=admin.username, action="ipmi.test",
                        detail=f"{server.name}: {'ok' if res.get('ok') else res.get('error', '')[:200]}"))
    except Exception:
        pass
    db.commit()
    db.refresh(snap)
    return {
        "ok": bool(res.get("ok")),
        "error": res.get("error", ""),
        "duration": res.get("duration", 0),
        "summary": summ,
        "snapshot": _snap_to_dict(snap),
    }
