from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, User
from ..rate_limit import limiter
from ..schemas import LoginRequest, MfaCode, MfaDisable, TokenResponse, UserOut
from ..security import (
    clear_auth_cookies,
    create_access_token,
    decrypt_text,
    enforce_login_origin,
    encrypt_text,
    get_current_user,
    hash_password,
    increment_token_version,
    new_totp_secret,
    resolve_client_ip,
    check_step_up_limit,
    record_step_up_failure,
    record_step_up_success,
    set_auth_cookies,
    totp_uri,
    verify_totp,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
INVALID_CREDENTIALS_DETAIL = "Incorrect username, password, or MFA code"

# bcrypt hash of a random string; used to equalize response timing for
# nonexistent usernames (see _authenticate)
_DUMMY_HASH = hash_password("gpumon-dummy-timing-equalizer")


def audit(db: Session, username: str, action: str, detail: str = "") -> None:
    try:
        db.add(AuditLog(username=username, action=action, detail=detail[:500]))
        db.commit()
    except Exception:
        db.rollback()


def _client_ip(request: Request) -> str:
    return resolve_client_ip(request)


def _commit_mfa_transition(db: Session, user: User, values: dict) -> bool:
    """Atomically consume one TOTP counter across concurrent login requests."""
    observed_counter = user.mfa_last_counter
    observed_version = user.token_version
    changed = (
        db.query(User)
        .filter(
            User.id == user.id,
            User.mfa_last_counter == observed_counter,
            User.token_version == observed_version,
        )
        .update(values, synchronize_session=False)
    )
    if changed != 1:
        db.rollback()
        return False
    db.commit()
    db.refresh(user)
    return True


def _authenticate(
    db: Session,
    request: Request,
    response: Response,
    username: str,
    password: str,
    otp: str = "",
) -> TokenResponse:
    enforce_login_origin(request)
    ip = _client_ip(request)

    allowed, retry_after = limiter.check(ip, username)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"尝试次数过多已锁定，请 {retry_after // 60} 分 {retry_after % 60} 秒后再试",
            headers={"Retry-After": str(max(1, retry_after))},
        )

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        # burn the same bcrypt cost as a real check so response timing does not
        # reveal whether the username exists
        verify_password(password, _DUMMY_HASH)
        limiter.record_failure(ip, username)
        audit(db, username, "login.failed", f"ip={ip}")
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS_DETAIL)
    if not verify_password(password, user.password_hash):
        limiter.record_failure(ip, username)
        audit(db, username, "login.failed", f"ip={ip}")
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS_DETAIL)
    if not user.is_active:
        # same status code as a bad password: do not confirm the account exists
        limiter.record_failure(ip, username)
        audit(db, username, "login.failed.disabled", f"ip={ip}")
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS_DETAIL)

    mfa_verified = False
    from ..config import get_settings

    if user.is_admin and get_settings().require_admin_mfa and user.mfa_enrolled:
        issued_version = user.token_version
        try:
            secret = decrypt_text(user.mfa_secret)
            counter = verify_totp(secret, otp, user.mfa_last_counter)
        except Exception:
            counter = None
        if counter is None:
            limiter.record_failure(ip, username)
            audit(db, username, "login.failed.mfa", f"ip={ip}")
            raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS_DETAIL)
        if not _commit_mfa_transition(db, user, {"mfa_last_counter": counter}):
            limiter.record_failure(ip, username)
            audit(db, username, "login.failed.mfa_replay", f"ip={ip}")
            raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS_DETAIL)
        mfa_verified = True

    limiter.record_success(ip, username)
    token = create_access_token(
        user,
        mfa_verified=mfa_verified,
        token_version=issued_version if mfa_verified else user.token_version,
    )
    set_auth_cookies(response, token)
    audit(db, user.username, "login", f"ip={ip}")
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
def login(
    request: Request,
    response: Response,
    username: Annotated[str, Form(min_length=1, max_length=64)],
    password: Annotated[str, Form(min_length=1, max_length=128)],
    otp: Annotated[str, Form(max_length=8)] = "",
    db: Session = Depends(get_db),
):
    return _authenticate(db, request, response, username, password, otp)


@router.post("/login-json", response_model=TokenResponse, include_in_schema=False)
def login_json(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    return _authenticate(db, request, response, body.username, body.password, body.otp)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


def _admin_for_enrollment(user: User) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin role required")


@router.post("/mfa/setup")
def mfa_setup(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _admin_for_enrollment(user)
    if user.mfa_enrolled:
        raise HTTPException(status_code=409, detail="MFA is already enrolled")
    secret = new_totp_secret()
    user.mfa_secret = encrypt_text(secret)
    user.mfa_confirmed = False
    user.mfa_last_counter = -1
    db.commit()
    audit(db, user.username, "mfa.setup")
    return {"secret": secret, "uri": totp_uri(user.username, secret)}


@router.post("/mfa/confirm")
def mfa_confirm(
    body: MfaCode,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _admin_for_enrollment(user)
    if not user.mfa_secret:
        raise HTTPException(status_code=400, detail="Start MFA setup first")
    secret = decrypt_text(user.mfa_secret)
    counter = verify_totp(secret, body.code, user.mfa_last_counter)
    if counter is None:
        raise HTTPException(status_code=400, detail="Invalid or already-used MFA code")
    issued_version = user.token_version + 1
    if not _commit_mfa_transition(
        db,
        user,
        {
            "mfa_confirmed": True,
            "mfa_last_counter": counter,
            "token_version": User.token_version + 1,
        },
    ):
        raise HTTPException(status_code=400, detail="Invalid or already-used MFA code")
    token = create_access_token(
        user,
        mfa_verified=True,
        token_version=issued_version,
    )
    set_auth_cookies(response, token)
    audit(db, user.username, "mfa.confirm")
    return {
        "ok": True,
        "access_token": token,
        "user": UserOut.model_validate(user),
    }


@router.post("/mfa/disable")
def mfa_disable(
    body: MfaDisable,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _admin_for_enrollment(user)
    ip, bucket = check_step_up_limit(request, user, "mfa-disable")
    if not user.mfa_enrolled or not verify_password(body.password, user.password_hash):
        record_step_up_failure(ip, bucket)
        audit(db, user.username, "mfa.disable_failed", f"ip={ip}")
        raise HTTPException(status_code=403, detail="MFA disable verification failed")
    secret = decrypt_text(user.mfa_secret)
    counter = verify_totp(secret, body.code, user.mfa_last_counter)
    if counter is None:
        record_step_up_failure(ip, bucket)
        audit(db, user.username, "mfa.disable_failed", f"ip={ip}")
        raise HTTPException(status_code=403, detail="MFA disable verification failed")
    issued_version = user.token_version + 1
    if not _commit_mfa_transition(
        db,
        user,
        {
            "mfa_secret": "",
            "mfa_confirmed": False,
            "mfa_last_counter": -1,
            "token_version": User.token_version + 1,
        },
    ):
        record_step_up_failure(ip, bucket)
        audit(db, user.username, "mfa.disable_replay", f"ip={ip}")
        raise HTTPException(status_code=403, detail="MFA disable verification failed")
    record_step_up_success(ip, bucket)
    token = create_access_token(
        user,
        mfa_verified=False,
        token_version=issued_version,
    )
    set_auth_cookies(response, token)
    audit(db, user.username, "mfa.disable")
    return {"ok": True, "access_token": token, "user": UserOut.model_validate(user)}


@router.post("/logout")
def logout(
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Incrementing the persistent version invalidates this token everywhere,
    # including after a restart and in other application replicas.
    increment_token_version(db, user)
    db.commit()
    audit(db, user.username, "logout")
    clear_auth_cookies(response)
    return {"ok": True}
