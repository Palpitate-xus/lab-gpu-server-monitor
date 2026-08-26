import base64
import hashlib
import os

from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import User

settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

ALGORITHM = "HS256"


# ---------------- password hashing ----------------
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(password, hashed)
    except Exception:
        return False


# ---------------- token ----------------
def create_access_token(username: str, sub_id: int) -> str:
    from datetime import datetime, timedelta, timezone

    from . import token_revocation

    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": username,
        "uid": sub_id,
        "iat": int(now.timestamp()),
        "jti": token_revocation.new_jti(),
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])


# ---------------- fernet encryption for SSH secrets ----------------
def _derive_key() -> bytes:
    digest = hashlib.sha256((settings.SECRET_KEY + "|ssh-secret").encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_text(plain: str) -> str:
    if not plain:
        return ""
    f = Fernet(_derive_key())
    return f.encrypt(plain.encode()).decode()


class CredentialDecryptionError(Exception):
    """Stored credential cannot be decrypted — SECRET_KEY was rotated."""


def decrypt_text(token: str) -> str:
    if not token:
        return ""
    f = Fernet(_derive_key())
    try:
        return f.decrypt(token.encode()).decode()
    except Exception as e:
        raise CredentialDecryptionError(
            "stored SSH credentials cannot be decrypted (SECRET_KEY changed); "
            "re-enter this server's credentials"
        ) from e


# ---------------- dependencies ----------------
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        username: str = payload.get("sub")
        if username is None:
            raise cred_exc
    except JWTError:
        raise cred_exc
    from . import token_revocation
    if token_revocation.is_revoked(
        payload.get("jti"), payload.get("uid"), payload.get("iat")
    ):
        raise cred_exc
    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.is_active:
        raise cred_exc
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
