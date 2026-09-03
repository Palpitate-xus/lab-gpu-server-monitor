from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, User
from ..schemas import PasswordChange, UserCreate, UserOut, UserUpdate
from ..security import (
    create_access_token,
    check_step_up_limit,
    get_current_user,
    hash_password,
    increment_token_version,
    record_step_up_failure,
    record_step_up_success,
    require_admin,
    set_auth_cookies,
)

router = APIRouter(prefix="/api/users", tags=["users"])


def audit(db: Session, username: str, action: str, detail: str = "") -> None:
    try:
        db.add(AuditLog(username=username, action=action, detail=detail[:500]))
        db.commit()
    except Exception:
        db.rollback()


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.query(User).order_by(User.id).all()


@router.post("", response_model=UserOut)
def create_user(body: UserCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=409, detail="Username already exists")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name or body.username,
        email=body.email,
        role=body.role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    audit(db, admin.username, "user.create", f"created user {user.username} role={user.role}")
    return user


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.email is not None:
        user.email = body.email
    if body.role is not None:
        if user.id == admin.id and body.role != "admin":
            raise HTTPException(status_code=400, detail="Cannot demote yourself")
        user.role = body.role
    if body.is_active is not None:
        if user.id == admin.id and not body.is_active:
            raise HTTPException(status_code=400, detail="Cannot disable yourself")
        user.is_active = body.is_active
    if body.password:
        user.password_hash = hash_password(body.password)
    if body.password or body.is_active is False or body.role is not None:
        increment_token_version(db, user)
    db.commit()
    db.refresh(user)
    audit(db, admin.username, "user.update", f"updated user {user.username}")
    return user


@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    username = user.username
    db.delete(user)
    db.commit()
    audit(db, admin.username, "user.delete", f"deleted user {username}")
    return {"ok": True}


@router.post("/change-password")
def change_password(
    body: PasswordChange,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    from ..security import verify_password

    ip, bucket = check_step_up_limit(request, current, "password-change")
    if not verify_password(body.old_password, current.password_hash):
        record_step_up_failure(ip, bucket)
        audit(db, current.username, "user.password_failed", f"ip={ip}")
        raise HTTPException(status_code=400, detail="Old password is incorrect")
    observed_hash = current.password_hash
    observed_version = current.token_version
    new_hash = hash_password(body.new_password)
    changed = (
        db.query(User)
        .filter(
            User.id == current.id,
            User.password_hash == observed_hash,
            User.token_version == observed_version,
        )
        .update(
            {
                User.password_hash: new_hash,
                User.token_version: User.token_version + 1,
            },
            synchronize_session=False,
        )
    )
    if changed != 1:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Account changed concurrently; sign in again and retry",
        )
    db.commit()
    db.refresh(current)
    record_step_up_success(ip, bucket)
    audit(db, current.username, "user.password", "changed own password")
    # Re-issue a token carrying the new persistent version for this session.
    token = create_access_token(
        current,
        mfa_verified=bool(getattr(request.state, "auth_mfa", False)),
        token_version=observed_version + 1,
    )
    set_auth_cookies(response, token)
    return {"ok": True, "access_token": token}


@router.post("/{user_id}/reset-mfa")
def reset_user_mfa(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Use the self-service MFA disable flow")
    user.mfa_secret = ""
    user.mfa_confirmed = False
    user.mfa_last_counter = -1
    increment_token_version(db, user)
    db.commit()
    audit(db, admin.username, "user.mfa_reset", f"reset MFA for {user.username}")
    return {"ok": True}
