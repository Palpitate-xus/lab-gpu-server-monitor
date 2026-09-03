from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, Server, User
from ..schemas import ConnectionTestResult
from ..security import decrypt_text, require_admin
from ..ssh_collector import test_connection

router = APIRouter(prefix="/api/servers", tags=["servers"])


@router.post("/{server_id}/test", response_model=ConnectionTestResult)
def test_stored_server(
    server_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Test connection using the credentials already stored (encrypted) for this server."""
    server = db.get(Server, server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    ok, message = test_connection(
        host=server.host,
        port=server.port,
        username=server.username,
        password=decrypt_text(server.password or ""),
        private_key=decrypt_text(server.private_key or ""),
        passphrase=decrypt_text(server.passphrase or ""),
        server_key=f"server_{server.id}",
    )
    try:
        db.add(AuditLog(username=admin.username, action="server.test", detail=f"test {server.name}: {'ok' if ok else message}"))
        db.commit()
    except Exception:
        db.rollback()
    return ConnectionTestResult(ok=ok, message=message)
