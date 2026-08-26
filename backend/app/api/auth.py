from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, User
from ..rate_limit import limiter
from ..schemas import LoginRequest, TokenResponse, UserOut
from ..security import create_access_token, get_current_user, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def audit(db: Session, username: str, action: str, detail: str = "") -> None:
    try:
        db.add(AuditLog(username=username, action=action, detail=detail[:500]))
        db.commit()
    except Exception:
        db.rollback()


def _client_ip(request: Request) -> str:
    # single-container deployment: the direct peer is the real client
    # (no reverse proxy in front by default). Honor X-Forwarded-For only if
    # explicitly trusted via env TRUST_PROXY=yes.
    from ..config import get_settings
    if get_settings().TRUST_PROXY:
        xf = request.headers.get("x-forwarded-for")
        if xf:
            return xf.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _authenticate(db: Session, request: Request, username: str, password: str) -> TokenResponse:
    ip = _client_ip(request)

    allowed, retry_after = limiter.check(ip, username)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"尝试次数过多已锁定，请 {retry_after // 60} 分 {retry_after % 60} 秒后再试",
        )

    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        limiter.record_failure(ip, username)
        audit(db, username, "login.failed", f"ip={ip}")
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    limiter.record_success(ip, username)
    token = create_access_token(user.username, user.id)
    audit(db, user.username, "login", f"ip={ip}")
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    return _authenticate(db, request, form.username, form.password)


@router.post("/login-json", response_model=TokenResponse, include_in_schema=False)
def login_json(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    return _authenticate(db, request, body.username, body.password)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
