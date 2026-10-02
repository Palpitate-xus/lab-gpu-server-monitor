from datetime import timezone as _tz

from fastapi import APIRouter, Depends, HTTPException, Request
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
from ..security import decrypt_text, encrypt_text, get_current_user, require_admin
from ..ssh_collector import test_connection

router = APIRouter(prefix="/api/servers", tags=["servers"])


def audit(db: Session, username: str, action: str, detail: str = "") -> None:
    try:
        db.add(AuditLog(username=username, action=action, detail=detail[:500]))
        db.commit()
    except Exception:
        db.rollback()


def _to_out(server: Server, include_management: bool = True) -> ServerOut:
    out = ServerOut.model_validate(server)
    if include_management:
        out.has_password = bool(server.password)
        out.has_key = bool(server.private_key)
        out.has_bmc = bool(server.bmc_host)
    else:
        out.host = ""
        out.port = 0
        out.auth_type = ""
        out.note = ""
        out.status_reason = None
        out.bmc_host = ""
        out.bmc_user = ""
        out.has_password = False
        out.has_key = False
        out.has_bmc = False
    return out


def _reject_root_ssh(username: str | None) -> None:
    from ..config import get_settings

    if username and username.strip().lower() == "root" and not get_settings().allow_root_ssh:
        raise HTTPException(
            status_code=400,
            detail="root SSH is disabled; provision a dedicated least-privilege gpumon account",
        )


def _connection_body(body, server: Server | None = None, *, require_credentials: bool = True) -> ConnectionTestRequest:
    """Merge a write-only draft without retaining inactive SSH credentials."""
    auth_type = body.auth_type or (server.auth_type if server else "password")
    same_auth = server is not None and auth_type == server.auth_type
    password = private_key = passphrase = ""
    if auth_type == "password":
        password = body.password or (
            decrypt_text(server.password or "") if same_auth else ""
        )
    else:
        private_key = body.private_key or (
            decrypt_text(server.private_key or "") if same_auth else ""
        )
        # A replacement key must not inherit the previous key's passphrase.
        passphrase = body.passphrase if body.passphrase is not None else (
            decrypt_text(server.passphrase or "") if same_auth and not body.private_key else ""
        )
    if require_credentials and not (password if auth_type == "password" else private_key):
        raise HTTPException(status_code=400, detail="请输入 SSH 密码" if auth_type == "password" else "请提供 SSH 私钥")
    request = ConnectionTestRequest(
        host=body.host or (server.host if server else ""),
        port=body.port if body.port is not None else (server.port if server else 22),
        username=body.username or (server.username if server else ""),
        auth_type=auth_type,
        password=password,
        private_key=private_key,
        passphrase=passphrase,
    )
    _reject_root_ssh(request.username)
    return request


@router.get("", response_model=list[ServerOut])
def list_servers(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from ..config import get_settings

    include_management = bool(
        user.is_admin
        and (
            not get_settings().require_admin_mfa
            or (user.mfa_enrolled and getattr(request.state, "auth_mfa", False))
        )
    )
    return [
        _to_out(server, include_management=include_management)
        for server in db.query(Server).order_by(Server.id).all()
    ]


@router.post("", response_model=ServerOut)
def create_server(body: ServerCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    connection = _connection_body(body)
    exists = db.query(Server).filter(Server.name == body.name).first()
    if exists:
        raise HTTPException(status_code=400, detail=f"服务器名称已存在: {body.name}")
    server = Server(
        name=body.name,
        host=body.host,
        port=body.port,
        auth_type=body.auth_type,
        username=body.username,
        password=encrypt_text(connection.password or ""),
        private_key=encrypt_text(connection.private_key or ""),
        passphrase=encrypt_text(connection.passphrase or ""),
        enabled=body.enabled,
        server_type=body.server_type,
        tags=body.tags or [],
        note=body.note or "",
        bmc_host=body.bmc_host or "",
        bmc_user=body.bmc_user or "",
        bmc_password=encrypt_text(body.bmc_password or ""),
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
    auth_changed = body.auth_type is not None and body.auth_type != server.auth_type
    credential_fields = body.model_fields_set.intersection({"auth_type", "password", "private_key", "passphrase"})
    # Turning off a server or editing metadata must remain possible even if
    # the stored credential keyring is unavailable or corrupt.
    connection = _connection_body(body, server, require_credentials=auth_changed) if credential_fields else None
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
        # Preflight storage before committing the address. The old trust file
        # remains in place until the DB transaction succeeds, so a failed
        # update can never silently downgrade the old target to first-use TOFU.
        from ..ssh_transport import ensure_hostkey_storage

        ensure_hostkey_storage()
    if body.auth_type is not None:
        server.auth_type = body.auth_type
    if body.username is not None:
        _reject_root_ssh(body.username)
        server.username = body.username
    if connection is not None:
        server.password = encrypt_text(connection.password or "")
        server.private_key = encrypt_text(connection.private_key or "")
        server.passphrase = encrypt_text(connection.passphrase or "")
    if body.enabled is not None:
        server.enabled = body.enabled
    if body.server_type is not None:
        server.server_type = body.server_type
    if body.tags is not None:
        server.tags = body.tags
    if body.note is not None:
        server.note = body.note
    if body.bmc_host is not None:
        server.bmc_host = body.bmc_host
    if body.bmc_user is not None:
        server.bmc_user = body.bmc_user
    if body.bmc_password is not None:
        server.bmc_password = encrypt_text(body.bmc_password)
    db.commit()
    db.refresh(server)
    audit(db, admin.username, "server.update", f"updated server {server.name}")
    if addr_changed:
        # New address = new host identity. Between commit and deletion the old
        # key makes connection attempts fail closed under RejectPolicy.
        from ..ssh_transport import forget_hostkey

        forget_hostkey(f"server_{server.id}")
    return _to_out(server)


@router.delete("/{server_id}")
def delete_server(server_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    server = db.get(Server, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    name = server.name
    from ..ssh_transport import ensure_hostkey_storage, forget_hostkey

    ensure_hostkey_storage()
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
    db.delete(server)
    db.add(
        AuditLog(
            username=admin.username,
            action="server.delete",
            detail=f"deleted server {name}",
        )
    )
    db.commit()
    forget_hostkey(f"server_{server_id}")
    return {"ok": True}


@router.post("/test", response_model=ConnectionTestResult)
def test_server_connection(
    body: ConnectionTestRequest,
    _: User = Depends(require_admin),
):
    return _run_connection_test(body, server_key=f"target_{body.host}_{body.port}")


def _run_connection_test(body: ConnectionTestRequest, *, server_key: str) -> ConnectionTestResult:
    _reject_root_ssh(body.username)
    import ipaddress
    import socket

    # SSRF guard: refuse loopback/link-local (incl. cloud metadata
    # 169.254.169.254)/multicast targets, both as literal IPs and behind
    # hostnames. Private ranges stay allowed: lab servers live there.
    def _bad_ip(ip) -> bool:
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            return _bad_ip(ip.ipv4_mapped)
        return ip.is_loopback or ip.is_multicast or ip.is_unspecified or ip.is_link_local

    # Resolve once and connect to the validated address: a second lookup
    # inside test_connection would let a short-TTL name swap to loopback or
    # the metadata address between check and connect.
    target = ""
    try:
        literal = ipaddress.ip_address(body.host)
        if _bad_ip(literal):
            return ConnectionTestResult(ok=False, message=f"非法目标地址: {body.host}")
        target = str(literal)
    except ValueError:
        try:
            infos = socket.getaddrinfo(body.host, body.port or 22, proto=socket.IPPROTO_TCP)
        except OSError:
            return ConnectionTestResult(ok=False, message=f"DNS 解析失败: {body.host}")
        answers = [ipaddress.ip_address(info[4][0]) for info in infos]
        if not answers or any(_bad_ip(ip) for ip in answers):
            return ConnectionTestResult(ok=False, message=f"非法目标地址: {body.host}")
        target = str(answers[0])
    ok, message = test_connection(
        host=body.host,
        port=body.port,
        username=body.username,
        password=(body.password or "") if body.auth_type == "password" else "",
        private_key=(body.private_key or "") if body.auth_type == "key" else "",
        passphrase=(body.passphrase or "") if body.auth_type == "key" else "",
        server_key=server_key,
        connect_address=target,
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
