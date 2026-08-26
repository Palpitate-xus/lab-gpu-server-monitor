from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, Server, User
from ..schemas import (
    ConnectionTestRequest,
    ConnectionTestResult,
    ServerCreate,
    ServerOut,
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
    if body.name is not None:
        server.name = body.name
    if body.host is not None:
        server.host = body.host
    if body.port is not None:
        server.port = body.port
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
    db.delete(server)
    db.commit()
    audit(db, admin.username, "server.delete", f"deleted server {name}")
    return {"ok": True}


@router.post("/test", response_model=ConnectionTestResult)
def test_server_connection(
    body: ConnectionTestRequest,
    _: User = Depends(require_admin),
):
    ok, message = test_connection(
        host=body.host,
        port=body.port,
        username=body.username,
        password=body.password or "",
        private_key=body.private_key or "",
        passphrase=body.passphrase or "",
    )
    return ConnectionTestResult(ok=ok, message=message)
