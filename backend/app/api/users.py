from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, User
from ..schemas import PasswordChange, UserCreate, UserOut, UserUpdate
from ..security import get_current_user, hash_password, require_admin

router = APIRouter(prefix="/api/users", tags=["users"])


def audit(db: Session, username: str, action: str, detail: str = "") -> None:
    try:
        db.add(AuditLog(username=username, action=action, detail=detail[:500]))
        db.commit()
    except Exception:
        db.rollback()


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
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
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    from ..security import verify_password

    if not verify_password(body.old_password, current.password_hash):
        raise HTTPException(status_code=400, detail="Old password is incorrect")
    current.password_hash = hash_password(body.new_password)
    db.commit()
    audit(db, current.username, "user.password", "changed own password")
    return {"ok": True}
