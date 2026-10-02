from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, Server, User
from ..schemas import ConnectionTestResult, ServerUpdate
from ..security import require_admin
from .servers import _connection_body, _run_connection_test

router = APIRouter(prefix="/api/servers", tags=["servers"])


@router.post("/{server_id}/test", response_model=ConnectionTestResult)
def test_stored_server(
    server_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    body: ServerUpdate | None = None,
):
    """Test stored credentials merged with an optional draft, without saving it."""
    server = db.get(Server, server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")
    connection = _connection_body(body or ServerUpdate(), server)
    unchanged_address = connection.host == server.host and connection.port == server.port
    result = _run_connection_test(
        connection,
        server_key=f"server_{server.id}" if unchanged_address else f"target_{connection.host}_{connection.port}",
    )
    try:
        db.add(AuditLog(username=admin.username, action="server.test", detail=f"test {server.name}: {'ok' if result.ok else result.message}"))
        db.commit()
    except Exception:
        db.rollback()
    return result
