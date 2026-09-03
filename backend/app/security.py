import base64
import hashlib
import hmac
import ipaddress
import os
import secrets
import struct
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt import InvalidTokenError
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .models import User

settings = get_settings()

pwd_context = CryptContext(
    schemes=["bcrypt_sha256", "bcrypt"],
    deprecated=["bcrypt"],
)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

ALGORITHM = "HS256"


def resolve_client_ip(request: Request) -> str:
    """Resolve a client address only through an explicitly trusted proxy chain."""
    resolved = getattr(request.state, "resolved_client_ip", "")
    if resolved:
        return resolved
    peer = request.client.host if request.client else "unknown"
    try:
        peer_ip = ipaddress.ip_address(peer)
        trusted = tuple(
            ipaddress.ip_network(value.strip(), strict=False)
            for value in settings.TRUSTED_PROXY_CIDRS.split(",")
            if value.strip()
        )
    except ValueError:
        trusted = ()
        peer_ip = None
    if settings.trust_proxy and peer_ip is not None and any(
        peer_ip in network for network in trusted
    ):
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            try:
                chain = [
                    ipaddress.ip_address(value.strip())
                    for value in forwarded.split(",")
                ]
            except ValueError:
                peer = "invalid-forwarded-address"
            else:
                current = peer_ip
                for candidate in reversed(chain):
                    if not any(current in network for network in trusted):
                        break
                    current = candidate
                peer = str(current)
    request.state.resolved_client_ip = peer
    return peer


# ---------------- password hashing ----------------
def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    # Legacy raw bcrypt silently truncates after 72 bytes. Refuse ambiguous
    # long inputs for old hashes; all newly written hashes use bcrypt_sha256.
    if hashed.startswith(("$2a$", "$2b$", "$2x$", "$2y$")) and len(
        password.encode("utf-8")
    ) > 72:
        try:
            # Still burn the normal bcrypt work factor so this fail-closed
            # compatibility rule cannot become a username timing oracle.
            pwd_context.verify(password, hashed)
        except Exception:
            pass
        return False
    try:
        return pwd_context.verify(password, hashed)
    except Exception:
        return False


def increment_token_version(db: Session, user: User) -> None:
    """Atomically revoke existing sessions, including concurrent revocations."""
    db.flush()
    changed = (
        db.query(User)
        .filter(User.id == user.id)
        .update(
            {User.token_version: User.token_version + 1},
            synchronize_session=False,
        )
    )
    if changed != 1:
        raise RuntimeError("cannot revoke sessions for a missing user")
    db.flush()
    db.expire(user, ["token_version"])


def has_bearer_authorization(request: Request) -> bool:
    """True only for a syntactically non-empty Bearer Authorization header."""
    raw = request.headers.get("authorization", "")
    scheme, separator, credential = raw.partition(" ")
    return bool(
        separator
        and scheme.casefold() == "bearer"
        and credential.strip()
    )


def enforce_login_origin(request: Request) -> None:
    """Reject cross-site browser login CSRF while retaining CLI/MCP clients."""
    fetch_site = request.headers.get("sec-fetch-site", "").casefold()
    if fetch_site == "cross-site":
        raise HTTPException(status_code=403, detail="Cross-site login is not allowed")
    origin = request.headers.get("origin", "").strip()
    if not origin:
        return
    try:
        parsed = urlsplit(origin)
        origin_port = parsed.port
        target = urlsplit("//" + request.headers.get("host", ""))
        target_port = target.port
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid login origin") from None
    default_origin_port = 443 if parsed.scheme == "https" else 80
    effective_origin_port = origin_port or default_origin_port
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or not target.hostname
        or target.username
        or target.password
        or target.path
        or target.query
        or target.fragment
        or (parsed.hostname or "").casefold()
        != (target.hostname or "").casefold()
        # The TLS reverse proxy overwrites Host but the private application
        # hop is deliberately plain HTTP. Compare Origin with that external
        # Host, not request.url.scheme/port from the private hop.
        or (target_port is not None and effective_origin_port != target_port)
        or (
            target_port is None
            and origin_port is not None
            and origin_port != default_origin_port
        )
        or (parsed.scheme != "https" and not settings.allow_insecure_http)
    ):
        raise HTTPException(status_code=403, detail="Cross-site login is not allowed")


def check_step_up_limit(request: Request, user: User, purpose: str) -> tuple[str, str]:
    from .rate_limit import step_up_limiter

    ip = resolve_client_ip(request)
    bucket = f"{user.username}:{purpose}"
    allowed, retry_after = step_up_limiter.check(ip, bucket)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many verification failures; retry later",
            headers={"Retry-After": str(max(1, retry_after))},
        )
    return ip, bucket


def record_step_up_failure(ip: str, bucket: str) -> None:
    from .rate_limit import step_up_limiter

    step_up_limiter.record_failure(ip, bucket)


def record_step_up_success(ip: str, bucket: str) -> None:
    from .rate_limit import step_up_limiter

    step_up_limiter.record_success(ip, bucket)


# ---------------- token ----------------
def create_access_token(
    user: User,
    *,
    mfa_verified: bool = False,
    token_version: int | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user.username,
        "uid": user.id,
        "aid": user.auth_id,
        # Callers that mutate the version pass the value owned by their
        # transaction. Never let a later concurrent revocation be inherited
        # merely because SQLAlchemy refreshed the object after commit.
        "ver": user.token_version if token_version is None else token_version,
        "mfa": bool(mfa_verified),
        "iat": int(now.timestamp()),
        "jti": secrets.token_urlsafe(24),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_signing_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(
        token,
        settings.jwt_signing_key,
        algorithms=[ALGORITHM],
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
        options={
            "require": ["sub", "uid", "aid", "ver", "iat", "jti", "iss", "aud", "exp"],
        },
    )


# ---------------- fernet encryption for SSH secrets ----------------
def _derive_key(secret: str) -> bytes:
    digest = hashlib.sha256((secret + "|ssh-secret").encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_text(plain: str) -> str:
    if not plain:
        return ""
    keys = settings.credential_encryption_keys
    if not keys:
        raise RuntimeError("credential encryption key is not configured")
    f = Fernet(_derive_key(keys[0]))
    return f.encrypt(plain.encode()).decode()


class CredentialDecryptionError(Exception):
    """Stored credential cannot be decrypted with the configured keyring."""


def decrypt_text(token: str) -> str:
    if not token:
        return ""
    last_error: Exception | None = None
    for secret in settings.credential_encryption_keys:
        try:
            return Fernet(_derive_key(secret)).decrypt(token.encode()).decode()
        except Exception as exc:
            last_error = exc
    raise CredentialDecryptionError(
        "stored SSH credentials cannot be decrypted; configure the previous "
        "credential key or re-enter this server's credentials"
    ) from last_error


# ---------------- browser cookie session ----------------
ACCESS_COOKIE = "gpumon_access"
CSRF_COOKIE = "gpumon_csrf"


def set_auth_cookies(response: Response, token: str) -> str:
    csrf = secrets.token_urlsafe(32)
    max_age = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    same_site = settings.COOKIE_SAMESITE.lower()
    if same_site not in {"strict", "lax", "none"}:
        same_site = "strict"
    response.set_cookie(
        ACCESS_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=same_site,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=max_age,
        httponly=False,
        secure=settings.cookie_secure,
        samesite=same_site,
        path="/",
    )
    return csrf


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        ACCESS_COOKIE,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
    )
    response.delete_cookie(CSRF_COOKIE, path="/", secure=settings.cookie_secure)


def valid_csrf(request: Request) -> bool:
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get("x-csrf-token", "")
    return bool(cookie and header and hmac.compare_digest(cookie, header))


# ---------------- TOTP MFA ----------------
def new_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def _totp_at(secret: str, counter: int) -> str:
    padded = secret.upper() + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    # RFC 6238 authenticator compatibility requires HMAC-SHA1 here; this is
    # not a collision-resistance use of SHA-1.
    digest = hmac.new(  # nosec B324
        key, struct.pack(">Q", counter), hashlib.sha1
    ).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{number % 1_000_000:06d}"


def verify_totp(secret: str, code: str, last_counter: int = -1) -> int | None:
    if len(code) != 6 or not code.isdigit():
        return None
    current = int(time.time()) // 30
    for counter in (current, current - 1, current + 1):
        if counter > last_counter and hmac.compare_digest(_totp_at(secret, counter), code):
            return counter
    return None


def totp_uri(username: str, secret: str) -> str:
    from urllib.parse import quote

    issuer = quote(settings.APP_NAME, safe="")
    label = quote(f"{settings.APP_NAME}:{username}", safe="")
    return f"otpauth://totp/{label}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"


# ---------------- dependencies ----------------
def get_current_user(
    request: Request,
    bearer_token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        authorization_supplied = bool(request.headers.get("authorization", "").strip())
        # Never fall back to a browser cookie when a caller supplied another
        # Authorization scheme. This keeps CSRF and authentication selection
        # aligned and prevents e.g. a dummy Basic header bypassing CSRF.
        if authorization_supplied and not bearer_token:
            raise cred_exc
        token = bearer_token or request.cookies.get(ACCESS_COOKIE, "")
        if not token:
            raise cred_exc
        payload = decode_token(token)
        username = payload.get("sub")
        uid = payload.get("uid")
        auth_id = payload.get("aid")
        token_version = payload.get("ver")
        if not isinstance(username, str) or not isinstance(uid, int):
            raise cred_exc
    except (InvalidTokenError, ValueError, TypeError):
        raise cred_exc
    user = db.get(User, uid)
    if (
        user is None
        or not user.is_active
        or user.username != username
        or user.auth_id != auth_id
        or user.token_version != token_version
    ):
        raise cred_exc
    request.state.auth_mfa = bool(payload.get("mfa", False))
    request.state.auth_username = user.username
    request.state.auth_user_id = user.id
    return user


def require_admin(request: Request, user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin role required")
    if settings.require_admin_mfa:
        if not user.mfa_enrolled:
            raise HTTPException(status_code=403, detail="Administrator MFA enrollment required")
        if not getattr(request.state, "auth_mfa", False):
            raise HTTPException(status_code=403, detail="Administrator MFA verification required")
    return user
