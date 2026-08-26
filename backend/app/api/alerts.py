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
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(AlertEvent).order_by(AlertEvent.triggered_at.desc())
    if open_only:
        q = q.filter(AlertEvent.recovered_at.is_(None))
    return q.limit(limit).all()


@router.post("/events/{event_id}/ack")
def ack_event(event_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    ev = db.get(AlertEvent, event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="Event not found")
    if ev.recovered_at is None:
        ev.recovered_at = _now()
        db.commit()
    audit(db, admin.username, "alert.ack", f"event {event_id} ({ev.rule_name})")
    return {"ok": True}


@router.post("/test-webhook")
def test_webhook(_: User = Depends(require_admin)):
    from .. import notifier

    ok, msg = notifier.notify_alert("test-server", "gpu_temp", 88.0, ">", 80, "测试规则")
    if not ok:
        raise HTTPException(status_code=400, detail=f"发送失败: {msg}")
    return {"ok": True, "message": msg}
