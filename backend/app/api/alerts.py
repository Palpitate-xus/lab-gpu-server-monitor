from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AlertEvent, AlertRule, AuditLog, Server, User
from ..schemas import AlertEventOut, AlertRuleCreate, AlertRuleOut, AlertRuleUpdate
from ..security import get_current_user, require_admin

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def audit(db: Session, username: str, action: str, detail: str = "") -> None:
    try:
        db.add(AuditLog(username=username, action=action, detail=detail[:500]))
        db.commit()
    except Exception:
        db.rollback()


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/rules", response_model=list[AlertRuleOut])
def list_rules(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.query(AlertRule).order_by(AlertRule.id).all()


@router.post("/rules", response_model=AlertRuleOut)
def create_rule(body: AlertRuleCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if body.server_id is not None and db.get(Server, body.server_id) is None:
        raise HTTPException(status_code=404, detail="Server not found")
    rule = AlertRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    audit(db, admin.username, "alert.create", f"rule {rule.name}")
    return rule


@router.put("/rules/{rule_id}", response_model=AlertRuleOut)
def update_rule(
    rule_id: int,
    body: AlertRuleUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    data = body.model_dump(exclude_unset=True)
    if data.get("server_id") is not None:
        if db.get(Server, data["server_id"]) is None:
            raise HTTPException(status_code=404, detail="Server not found")
    for k, v in data.items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    audit(db, admin.username, "alert.update", f"rule {rule.name}")
    return rule


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    name = rule.name
    db.delete(rule)
    db.commit()
    audit(db, admin.username, "alert.delete", f"rule {name}")
    return {"ok": True}


@router.get("/events", response_model=list[AlertEventOut])
def list_events(
    open_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    server_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(AlertEvent).order_by(AlertEvent.triggered_at.desc())
    if open_only:
        q = q.filter(AlertEvent.recovered_at.is_(None))
    if server_id is not None:
        q = q.filter(AlertEvent.server_id == server_id)
    return q.offset(offset).limit(limit).all()


@router.post("/events/{event_id}/ack")
def ack_event(event_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    ev = db.get(AlertEvent, event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="Event not found")
    if ev.recovered_at is not None:
        raise HTTPException(status_code=400, detail="Event already recovered")
    if ev.acked_at is None:
        ev.acked_at = _now()
        ev.acked_by = admin.username
        db.commit()
    audit(db, admin.username, "alert.ack", f"event {event_id} ({ev.rule_name})")
    return {"ok": True}


@router.post("/events/{event_id}/resolve")
def resolve_event(event_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Manually close an open event (acknowledged problems that need a hard stop)."""
    ev = db.get(AlertEvent, event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="Event not found")
    if ev.recovered_at is None:
        ev.recovered_at = _now()
        db.commit()
    audit(db, admin.username, "alert.resolve", f"event {event_id} ({ev.rule_name})")
    return {"ok": True}


@router.post("/events/{event_id}/assign")
def assign_event(event_id: int, body: dict, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """Claim an event (visible to everyone; no admin required to take work)."""
    ev = db.get(AlertEvent, event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="Event not found")
    assignee = str(body.get("assignee") or "").strip()[:64]
    ev.assignee = assignee or user.username
    db.commit()
    audit(db, user.username, "alert.assign", f"event {event_id} -> {ev.assignee}")
    return {"ok": True, "assignee": ev.assignee}


# ---------------- webhook channels ----------------

from pydantic import BaseModel as _BM, Field as _F  # noqa: E402
from ..models import WebhookChannel  # noqa: E402


class _ChannelIn(_BM):
    name: str = _F(default="", max_length=128)
    url: str
    template: str = ""
    min_severity: str = "info"
    enabled: bool = True


@router.get("/channels")
def list_channels(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.query(WebhookChannel).order_by(WebhookChannel.id).all()
    return [
        {"id": r.id, "name": r.name, "url": r.url, "template": r.template,
         "min_severity": r.min_severity, "enabled": r.enabled}
        for r in rows
    ]


@router.post("/channels")
def create_channel(body: _ChannelIn, db: Session = Depends(get_db),
                   admin: User = Depends(require_admin)):
    from ..notifier import _validate_webhook_url

    if body.min_severity not in ("info", "warning", "critical"):
        raise HTTPException(status_code=400, detail="min_severity must be info|warning|critical")
    ok, why = _validate_webhook_url(body.url)
    if not ok:
        raise HTTPException(status_code=400, detail=f"webhook url rejected: {why}")
    ch = WebhookChannel(name=body.name, url=body.url, template=body.template,
                        min_severity=body.min_severity, enabled=body.enabled)
    db.add(ch)
    db.commit()
    db.refresh(ch)
    audit(db, admin.username, "webhook.create", f"channel {ch.id}")
    return {"ok": True, "id": ch.id}


@router.delete("/channels/{channel_id}")
def delete_channel(channel_id: int, db: Session = Depends(get_db),
                   admin: User = Depends(require_admin)):
    ch = db.get(WebhookChannel, channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    db.delete(ch)
    db.commit()
    audit(db, admin.username, "webhook.delete", f"channel {channel_id}")
    return {"ok": True}


@router.post("/test-webhook")
def test_webhook(
    body: dict | None = None,
    _: User = Depends(require_admin),
):
    from .. import notifier

    url = (body or {}).get("url") or ""
    template = (body or {}).get("template") or ""
    ctx = {
        "level": "ALERT",
        "server_name": "test-server",
        "metric": "gpu_temp",
        "value": 88.0,
        "op": ">",
        "threshold": 80,
        "rule_name": "测试规则",
        "time": _now().strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    if url:
        ok, msg = notifier.send_webhook(url, template or notifier.DEFAULT_TEMPLATE, ctx)
    else:
        ok, msg = notifier.notify_alert("test-server", "gpu_temp", 88.0, ">", 80, "测试规则")
    if not ok:
        raise HTTPException(status_code=400, detail=f"发送失败: {msg}")
    return {"ok": True, "message": msg}
