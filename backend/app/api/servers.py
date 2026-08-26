from datetime import timezone as _tz

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, Server, ServerNote, User
from ..schemas import (
    ConnectionTestRequest,
    ConnectionTestResult,
    ServerCreate,
    ServerOut,
    ServerStatusUpdate,
    ServerUpdate,
)
from ..security import encrypt_text, get_current_user, require_admin
from ..ssh_collector import test_connection

router = APIRouter(prefix="/api/servers", tags=["servers"])


def audit(db: Session, username: str, action: str, detail: str = "") -> None:
    try:
        db.add(AuditLog(username=username, action=action, detail=detail[:500]))
        db.commit()
    except Exception:
        db.rollback()


def _to_out(server: Server) -> ServerOut:
    out = ServerOut.model_validate(server)
    out.has_password = bool(server.password)
    out.has_key = bool(server.private_key)
    return out


@router.get("", response_model=list[ServerOut])
def list_servers(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return [_to_out(s) for s in db.query(Server).order_by(Server.id).all()]


@router.post("", response_model=ServerOut)
def create_server(body: ServerCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    exists = db.query(Server).filter(Server.name == body.name).first()
    if exists:
        raise HTTPException(status_code=400, detail=f"服务器名称已存在: {body.name}")
    server = Server(
        name=body.name,
        host=body.host,
        port=body.port,
        auth_type=body.auth_type,
        username=body.username,
        password=encrypt_text(body.password or ""),
        private_key=encrypt_text(body.private_key or ""),
        passphrase=encrypt_text(body.passphrase or ""),
        enabled=body.enabled,
        tags=body.tags or [],
        note=body.note or "",
    )
    db.add(server)
    db.commit()
    db.refresh(server)
    audit(db, admin.username, "server.create", f"added server {server.name} ({server.host})")
    return _to_out(server)


@router.put("/{server_id}", response_model=ServerOut)
def update_server(
    server_id: int,
    body: ServerUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    server = db.get(Server, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    if body.name is not None and body.name != server.name:
        exists = db.query(Server).filter(Server.name == body.name).first()
        if exists:
            raise HTTPException(status_code=400, detail=f"服务器名称已存在: {body.name}")
        server.name = body.name
    addr_changed = False
    if body.host is not None and body.host != server.host:
        server.host = body.host
        addr_changed = True
    if body.port is not None and body.port != server.port:
        server.port = body.port
        addr_changed = True
    if addr_changed:
        # new address = new host identity; drop stale TOFU trust
        from ..ssh_transport import forget_hostkey
        forget_hostkey(f"server_{server.id}")
    if body.auth_type is not None:
        server.auth_type = body.auth_type
    if body.username is not None:
        server.username = body.username
    if body.password is not None:
        server.password = encrypt_text(body.password)
    if body.private_key is not None:
        server.private_key = encrypt_text(body.private_key)
    if body.passphrase is not None:
        server.passphrase = encrypt_text(body.passphrase)
    if body.enabled is not None:
        server.enabled = body.enabled
    if body.server_type is not None:
        server.server_type = body.server_type
    if body.tags is not None:
        server.tags = body.tags
    if body.note is not None:
        server.note = body.note
    db.commit()
    db.refresh(server)
    audit(db, admin.username, "server.update", f"updated server {server.name}")
    return _to_out(server)


@router.delete("/{server_id}")
def delete_server(server_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    server = db.get(Server, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    name = server.name
    from ..models import (
        GpuBaseline,
        HostInventory,
        KernelEventRow,
        ServerMetric,
        ServerMetricHourly,
        ServerNote,
        SlowHealth,
    )
    # bulk SQL deletes (passive_deletes): no ORM load of the full history
    for model in (ServerMetricHourly, ServerMetric, KernelEventRow, SlowHealth,
                  HostInventory, GpuBaseline, ServerNote):
        db.query(model).filter(model.server_id == server_id).delete(
            synchronize_session=False
        )
    from ..ssh_transport import forget_hostkey
    forget_hostkey(f"server_{server_id}")
    db.delete(server)
    db.commit()
    audit(db, admin.username, "server.delete", f"deleted server {name}")
    return {"ok": True}


@router.post("/test", response_model=ConnectionTestResult)
def test_server_connection(
    body: ConnectionTestRequest,
    _: User = Depends(require_admin),
):
    import ipaddress
    # crude SSRF guard: if the host is a literal IP, refuse non-public targets;
    # hostnames still resolve during connect (this endpoint is admin-only and
    # is meant for real servers the admin manages)
    try:
        ip = ipaddress.ip_address(body.host)
        if ip.is_loopback or ip.is_multicast or ip.is_unspecified:
            return ConnectionTestResult(ok=False, message=f"非法目标地址: {body.host}")
    except ValueError:
        pass
    ok, message = test_connection(
        host=body.host,
        port=body.port,
        username=body.username,
        password=body.password or "",
        private_key=body.private_key or "",
        passphrase=body.passphrase or "",
    )
    return ConnectionTestResult(ok=ok, message=message)


# ---------------- lifecycle (maintenance / drained / rma) ----------------

@router.post("/{server_id}/status", response_model=ServerOut)
def set_server_status(
    server_id: int,
    body: ServerStatusUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    server = db.get(Server, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    server.status = body.status
    server.status_reason = body.reason or ""
    server.status_until = body.until
    # lifecycle changes are ledger entries too
    db.add(ServerNote(
        server_id=server.id,
        username=admin.username,
        kind="maintenance" if body.status == "maintenance" else "note",
        content=f"状态变更为 {body.status}" + (f"：{body.reason}" if body.reason else ""),
    ))
    db.commit()
    db.refresh(server)
    audit(db, admin.username, "server.status", f"{server.name} -> {body.status}")
    return _to_out(server)


class NoteCreate(BaseModel):
    kind: str = "note"  # note | maintenance | repair
    content: str


@router.get("/{server_id}/notes")
def list_notes(server_id: int, db: Session = Depends(get_db),
               _: User = Depends(get_current_user)):
    rows = (
        db.query(ServerNote)
        .filter(ServerNote.server_id == server_id)
        .order_by(ServerNote.ts.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "id": r.id,
            "ts": (r.ts if r.ts.tzinfo else r.ts.replace(tzinfo=_tz.utc)).isoformat(),
            "username": r.username,
            "kind": r.kind,
            "content": r.content,
        }
        for r in rows
    ]


@router.post("/{server_id}/notes")
def add_note(
    server_id: int,
    body: NoteCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    server = db.get(Server, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    if body.kind not in ("note", "maintenance", "repair"):
        raise HTTPException(status_code=400, detail="invalid kind")
    if not body.content.strip():
        raise HTTPException(status_code=400, detail="content required")
    db.add(ServerNote(server_id=server_id, username=user.username,
                      kind=body.kind, content=body.content.strip()[:2000]))
    db.commit()
    audit(db, user.username, "server.note", f"{server.name}: {body.kind}")
    return {"ok": True}
