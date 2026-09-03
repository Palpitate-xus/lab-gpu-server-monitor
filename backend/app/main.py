import ipaddress
import logging
import os
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl, unquote, urlsplit

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from starlette.middleware.gzip import GZipMiddleware

from .config import PUBLIC_SECRET_PLACEHOLDERS, get_settings
from .schemas import SettingsUpdate
from .database import Base, IS_MYSQL, SessionLocal, database_security_errors, engine, get_db
from .models import AuditLog, Setting, User
from .schemas import AuditLogOut
from .security import (
    get_current_user,
    has_bearer_authorization,
    hash_password,
    require_admin,
    resolve_client_ip,
)
from . import scheduler

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("gpumon")

from .api import alerts, auth, cockpit, enterprise, ipmi, metrics, servers, server_test, status_page, users  # noqa: E402


def _weak_secret(value: str) -> bool:
    normalized = value.strip().lower()
    return (
        len(value.strip()) < 32
        or normalized in PUBLIC_SECRET_PLACEHOLDERS
        or "change-me" in normalized
    )


def redis_security_errors() -> list[str]:
    """Validate optional Redis transport/auth without opening a connection."""
    raw = settings.REDIS_URL.strip()
    if not raw:
        return ["REDIS_SSL_CA requires REDIS_URL"] if settings.REDIS_SSL_CA.strip() else []
    errors: list[str] = []
    try:
        parsed = urlsplit(raw)
        scheme = parsed.scheme.casefold()
        if scheme not in {"redis", "rediss", "unix"}:
            return ["REDIS_URL must use redis://, rediss://, or unix://"]
        if parsed.fragment:
            errors.append("REDIS_URL must not contain a fragment")
        query_keys = {key.casefold() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
        if any(key.startswith("ssl_") for key in query_keys):
            errors.append(
                "REDIS_URL must not contain TLS query options; certificate verification "
                "is enforced centrally"
            )
        if scheme == "unix":
            if not parsed.path.startswith("/"):
                errors.append("unix REDIS_URL must contain an absolute socket path")
            if settings.REDIS_SSL_CA.strip():
                errors.append("REDIS_SSL_CA is valid only with rediss://")
            return errors
        if not parsed.hostname:
            errors.append("REDIS_URL must contain a host")
            return errors
        # Accessing .port validates malformed/overflowing port values.
        parsed.port
        host = parsed.hostname.strip("[]")
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = False
        if scheme == "redis" and not is_loopback:
            errors.append("non-loopback Redis requires rediss://")
        password = unquote(parsed.password or "")
        if scheme == "rediss" and len(password) < 16:
            errors.append("rediss:// requires an authentication password of at least 16 characters")
        if password.casefold() in PUBLIC_SECRET_PLACEHOLDERS:
            errors.append("REDIS_URL contains a public/default password")
        if settings.REDIS_SSL_CA.strip() and scheme != "rediss":
            errors.append("REDIS_SSL_CA is valid only with rediss://")
    except (TypeError, ValueError):
        errors.append("REDIS_URL is invalid")
    return errors


def _validate_runtime_security() -> None:
    errors: list[str] = []
    boolean_values = {"yes", "no", "1", "0", "true", "false"}
    for setting_name in (
        "AUTO_MIGRATE",
        "COOKIE_SECURE",
        "ALLOW_INSECURE_HTTP",
        "REMOTE_PROCESS_CONTROL_ENABLED",
        "ALLOW_ROOT_SSH",
        "REQUIRE_ADMIN_MFA",
        "TRUST_PROXY",
    ):
        if str(getattr(settings, setting_name)).strip().lower() not in boolean_values:
            errors.append(f"{setting_name} must be an explicit yes/no boolean value")
    if not settings.JWT_SIGNING_KEY.strip():
        errors.append("JWT_SIGNING_KEY is required (legacy SECRET_KEY fallback is not accepted at startup)")
    elif _weak_secret(settings.JWT_SIGNING_KEY):
        errors.append("JWT_SIGNING_KEY must be a strong random value of at least 32 characters")
    keys = settings.credential_encryption_keys
    if not settings.CREDENTIAL_ENCRYPTION_KEYS.strip():
        errors.append("CREDENTIAL_ENCRYPTION_KEYS is required")
    elif any(_weak_secret(key) for key in keys):
        errors.append("every CREDENTIAL_ENCRYPTION_KEYS entry must be at least 32 random characters")
    if settings.JWT_SIGNING_KEY.strip() in keys:
        errors.append("JWT_SIGNING_KEY must not be reused as a credential encryption key")
    if not settings.JWT_ISSUER.strip() or not settings.JWT_AUDIENCE.strip():
        errors.append("JWT_ISSUER and JWT_AUDIENCE must not be empty")
    if not 5 <= settings.ACCESS_TOKEN_EXPIRE_MINUTES <= 24 * 60:
        errors.append("ACCESS_TOKEN_EXPIRE_MINUTES must be between 5 and 1440")
    if settings.ARCHIVE_DIR:
        try:
            if len(settings.ARCHIVE_ENCRYPTION_KEY) != 64:
                raise ValueError
            archive_key = bytes.fromhex(settings.ARCHIVE_ENCRYPTION_KEY)
            if len(archive_key) != 32:
                raise ValueError
        except ValueError:
            errors.append("ARCHIVE_DIR requires a separate 64-hex-character ARCHIVE_ENCRYPTION_KEY")
        else:
            archive_secret = settings.ARCHIVE_ENCRYPTION_KEY.strip()
            if archive_secret == settings.JWT_SIGNING_KEY.strip() or archive_secret in keys:
                errors.append("ARCHIVE_ENCRYPTION_KEY must not reuse an authentication or credential key")
    if settings.COOKIE_SAMESITE.lower() not in {"strict", "lax", "none"}:
        errors.append("COOKIE_SAMESITE must be strict, lax, or none")
    if settings.COOKIE_SAMESITE.lower() == "none" and not settings.cookie_secure:
        errors.append("COOKIE_SAMESITE=none requires COOKIE_SECURE=yes")
    if not settings.cookie_secure and not settings.allow_insecure_http:
        errors.append(
            "COOKIE_SECURE=no requires the explicit loopback-development setting "
            "ALLOW_INSECURE_HTTP=yes"
        )
    if not 16 * 1024 <= settings.MAX_REQUEST_BODY_BYTES <= 16 * 1024 * 1024:
        errors.append("MAX_REQUEST_BODY_BYTES must be between 16 KiB and 16 MiB")
    cors_origins = [value.strip() for value in settings.CORS_ORIGINS.split(",") if value.strip()]
    if "*" in cors_origins:
        errors.append("CORS_ORIGINS must not contain a wildcard when credentials are enabled")
    for origin in cors_origins:
        try:
            parsed_origin = urlsplit(origin)
            parsed_origin.port
        except ValueError:
            errors.append(f"CORS_ORIGINS contains an invalid origin: {origin!r}")
            continue
        if (
            parsed_origin.scheme not in {"http", "https"}
            or not parsed_origin.hostname
            or parsed_origin.username
            or parsed_origin.password
            or parsed_origin.path
            or parsed_origin.query
            or parsed_origin.fragment
        ):
            errors.append(f"CORS_ORIGINS must contain exact web origins only: {origin!r}")
        elif parsed_origin.scheme != "https" and not settings.allow_insecure_http:
            errors.append("plain-HTTP CORS origins require ALLOW_INSECURE_HTTP=yes")
    try:
        proxy_networks = [
            ipaddress.ip_network(value.strip(), strict=False)
            for value in settings.TRUSTED_PROXY_CIDRS.split(",")
            if value.strip()
        ]
        if settings.trust_proxy and not proxy_networks:
            errors.append("TRUST_PROXY=yes requires at least one TRUSTED_PROXY_CIDRS entry")
        if settings.trust_proxy and any(
            network.prefixlen != network.max_prefixlen for network in proxy_networks
        ):
            errors.append(
                "TRUSTED_PROXY_CIDRS must contain exact /32 or /128 direct proxy peers"
            )
    except ValueError:
        errors.append("TRUSTED_PROXY_CIDRS contains an invalid IP network")
    if not settings.allow_insecure_http and not settings.trust_proxy:
        errors.append(
            "HTTPS deployments require TRUST_PROXY=yes and an exact direct-proxy "
            "address in TRUSTED_PROXY_CIDRS so login limits cannot collapse all "
            "clients into one shared proxy identity"
        )

    errors.extend(database_security_errors())
    errors.extend(redis_security_errors())
    if IS_MYSQL and settings.auto_migrate:
        errors.append("AUTO_MIGRATE must be disabled for MySQL runtime processes")

    if errors:
        raise RuntimeError("FATAL security configuration:\n- " + "\n- ".join(errors))


@asynccontextmanager
async def lifespan(app):
    app.state.ready = False
    _validate_runtime_security()
    from .ssh_transport import ensure_hostkey_storage

    ensure_hostkey_storage()
    if settings.ARCHIVE_DIR:
        from .archive_crypto import ensure_archive_storage

        ensure_archive_storage(settings.ARCHIVE_DIR)
    if settings.auto_migrate:
        # Explicit development/SQLite mode. Production uses the separate
        # migrate_db.py command with a DDL-only credential.
        Base.metadata.create_all(bind=engine)
        from .migrate import run_migrations

        applied = run_migrations()
        if applied:
            logger.info("applied migrations: %s", ", ".join(applied))
    else:
        schema = inspect(engine)
        required_tables = {
            "users",
            "servers",
            "server_metrics",
            "server_process_snapshots",
            "schema_migrations",
        }
        missing = required_tables.difference(schema.get_table_names())
        if missing:
            raise RuntimeError(
                "FATAL: database schema is not initialized; run scripts/migrate_db.py. "
                f"Missing tables: {', '.join(sorted(missing))}"
            )
        user_columns = {column["name"] for column in schema.get_columns("users")}
        missing_columns = {
            "auth_id",
            "token_version",
            "mfa_secret",
            "mfa_confirmed",
            "mfa_last_counter",
        }.difference(user_columns)
        if missing_columns:
            raise RuntimeError(
                "FATAL: security migration is pending; run scripts/migrate_db.py. "
                f"Missing users columns: {', '.join(sorted(missing_columns))}"
            )
        dialect = "mysql" if IS_MYSQL else "sqlite"
        required_security_migrations = {
            f"012_auth_sessions.{dialect}.sql",
            f"013_admin_mfa.{dialect}.sql",
        }
        with engine.connect() as conn:
            applied_migrations = {
                row[0]
                for row in conn.execute(text("SELECT name FROM schema_migrations"))
            }
        missing_migrations = required_security_migrations.difference(applied_migrations)
        if missing_migrations:
            raise RuntimeError(
                "FATAL: security migration records are missing; run scripts/migrate_db.py. "
                f"Missing migrations: {', '.join(sorted(missing_migrations))}"
            )
    from .notifier import secure_stored_webhook_urls

    secure_stored_webhook_urls()
    # create initial admin if none
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.role == "admin").first():
            if (
                not settings.INIT_ADMIN_USERNAME.strip()
                or len(settings.INIT_ADMIN_PASSWORD) < 16
                or len(settings.INIT_ADMIN_PASSWORD) > 72
                or settings.INIT_ADMIN_PASSWORD.lower() in PUBLIC_SECRET_PLACEHOLDERS
                or settings.INIT_ADMIN_PASSWORD.lower() == "admin123"
            ):
                raise RuntimeError(
                    "FATAL: no administrator exists; set a non-default "
                    "INIT_ADMIN_USERNAME and an INIT_ADMIN_PASSWORD of at least 16 characters"
                )
            admin = User(
                username=settings.INIT_ADMIN_USERNAME,
                password_hash=hash_password(settings.INIT_ADMIN_PASSWORD),
                display_name="Administrator",
                role="admin",
                is_active=True,
            )
            db.add(admin)
            db.commit()
            logger.info("created initial admin user %r", settings.INIT_ADMIN_USERNAME)
        # one-time move of the legacy single webhook into the channels table
        from .models import WebhookChannel
        if not db.query(WebhookChannel).count():
            wh = db.get(Setting, "alert_webhook_url")
            if wh and wh.value:
                tpl = db.get(Setting, "alert_webhook_template")
                db.add(WebhookChannel(
                    name="默认通道",
                    url=wh.value,
                    template=(tpl.value if tpl else "") or "",
                    min_severity="info",
                    enabled=True,
                ))
                db.commit()
                logger.info("migrated legacy webhook into channels table")
    finally:
        db.close()
    scheduler.start_scheduler()
    app.state.ready = True
    logger.info("startup complete")
    yield
    app.state.ready = False
    logger.info("shutting down")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan,
    # The schema maps the whole attack surface. This production service uses
    # repository documentation instead of exposing interactive docs.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


# ---------------- security headers ----------------
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402


class RequestBodyLimitMiddleware:
    """Reject oversized fixed-length or chunked bodies before parsers run."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
                if declared_length < 0:
                    raise ValueError
                if declared_length > settings.MAX_REQUEST_BODY_BYTES:
                    await JSONResponse(
                        status_code=413,
                        content={"detail": "request body too large"},
                    )(scope, receive, send)
                    return
            except ValueError:
                await JSONResponse(
                    status_code=400,
                    content={"detail": "invalid content-length"},
                )(scope, receive, send)
                return

        buffered = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            total += len(message.get("body", b""))
            if total > settings.MAX_REQUEST_BODY_BYTES:
                await JSONResponse(
                    status_code=413,
                    content={"detail": "request body too large"},
                )(scope, receive, send)
                return
            buffered.append(message)
            if not message.get("more_body", False):
                break

        index = 0

        async def replay_receive():
            nonlocal index
            if index < len(buffered):
                message = buffered[index]
                index += 1
                return message
            return await receive()

        await self.app(scope, replay_receive, send)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        client_ip = resolve_client_ip(request)
        # Browser cookie authentication requires a double-submit CSRF token.
        # Bearer clients such as MCP are not subject to browser CSRF.
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and request.url.path.startswith("/api/")
            and request.url.path not in {"/api/auth/login", "/api/auth/login-json"}
            and request.cookies.get("gpumon_access")
            and not has_bearer_authorization(request)
        ):
            from .security import valid_csrf

            if not valid_csrf(request):
                resp = JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
            else:
                resp = await call_next(request)
        else:
            resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        resp.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        # SPA: no inline <script> is used by the Vite build; style-src needs
        # 'unsafe-inline' for ECharts/Element Plus runtime styles.
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; font-src 'self' data:; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        if request.url.scheme == "https":
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
            resp.headers.setdefault("Pragma", "no-cache")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api/"):
            logger.info(
                "security_audit method=%s path=%s status=%s client=%s user=%s",
                request.method,
                request.url.path,
                resp.status_code,
                client_ip,
                getattr(request.state, "auth_username", "anonymous"),
            )
        return resp


app.add_middleware(RequestBodyLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
# Compress large JSON and static assets for direct deployments. A reverse
# proxy honors the upstream Content-Encoding header and will not recompress.
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)


if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",")],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(servers.router)
app.include_router(server_test.router)
app.include_router(metrics.router)
app.include_router(alerts.router)
app.include_router(enterprise.router)
app.include_router(cockpit.router)
app.include_router(status_page.router)
app.include_router(ipmi.router)


# ---------------- audit logs + settings ----------------
misc_router = APIRouter(prefix="/api", tags=["misc"])


@misc_router.get("/audit-logs", response_model=list[AuditLogOut])
def list_audit_logs(
    limit: int = 100,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return db.query(AuditLog).order_by(AuditLog.ts.desc()).limit(max(1, min(limit, 500))).all()


@misc_router.get("/settings")
def get_app_settings(_: User = Depends(require_admin)):
    db = SessionLocal()
    try:
        row = db.get(Setting, "poll_interval")
        interval = int(row.value) if row and row.value else settings.POLL_INTERVAL_SECONDS
        rrow = db.get(Setting, "retention_days")
        retention_days = 0
        if rrow and rrow.value:
            try:
                retention_days = int(rrow.value)
            except ValueError:
                retention_days = 0
        wh = db.get(Setting, "alert_webhook_url")
        wt = db.get(Setting, "alert_webhook_template")
        ep = db.get(Setting, "energy_price")
        try:
            energy_price = float(ep.value) if ep and ep.value else 0.0
        except ValueError:
            energy_price = 0.0
    finally:
        db.close()
    return {
        "poll_interval": interval,
        "retention_days": retention_days,
        # Webhook URLs commonly embed bearer tokens. Treat them like stored
        # credentials: write-only through the API and encrypted at rest.
        "webhook_url": "",
        "webhook_url_configured": bool(wh and wh.value),
        "webhook_template": (wt.value if wt else "") or "",
        "energy_price": energy_price,
        "scheduler": scheduler.scheduler_status(),
    }


@misc_router.put("/settings")
def update_app_settings(body: SettingsUpdate, _: User = Depends(require_admin)):
    db = SessionLocal()
    try:
        if body.poll_interval is not None:
            try:
                interval = int(body.poll_interval)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="poll_interval must be an integer")
            if interval < 10:
                raise HTTPException(status_code=400, detail="poll_interval must be >= 10 seconds")
            _set_setting(db, "poll_interval", str(interval))
        if body.retention_days is not None:
            try:
                days = int(body.retention_days)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="retention_days must be an integer")
            if days < 0:
                raise HTTPException(status_code=400, detail="retention_days must be >= 0 (0 = keep forever)")
            _set_setting(db, "retention_days", str(days))
        if body.energy_price is not None:
            price = float(body.energy_price or 0)
            if price < 0 or price > 100:
                raise HTTPException(status_code=400, detail="energy_price must be in [0, 100]")
            _set_setting(db, "energy_price", str(price))
        if body.webhook_url is not None:
            url = str(body.webhook_url or "")
            if url:
                from .notifier import _validate_webhook_url, protect_webhook_url
                ok, why = _validate_webhook_url(url)
                if not ok:
                    raise HTTPException(status_code=400, detail=f"webhook url rejected: {why}")
                url = protect_webhook_url(url)
            _set_setting(db, "alert_webhook_url", url)
        if body.webhook_template is not None:
            _set_setting(db, "alert_webhook_template", str(body.webhook_template or ""))
    finally:
        db.close()
    return {"ok": True}


def _set_setting(db, key: str, value: str) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
    db.commit()


# ---------------- detector thresholds ----------------
_THRESHOLD_KEYS = {
    "gpu_idle_vram_pct": (1.0, 95.0, 30.0),
    "gpu_idle_minutes": (5.0, 1440.0, 30.0),
    "health_cpu_pct": (50.0, 100.0, 90.0),
    "health_mem_pct": (50.0, 100.0, 92.0),
    "health_disk_pct": (50.0, 100.0, 90.0),
}


@misc_router.get("/settings/thresholds")
def get_thresholds(_: User = Depends(get_current_user)):
    db = SessionLocal()
    try:
        out = {}
        for key, (_lo, _hi, default) in _THRESHOLD_KEYS.items():
            row = db.get(Setting, key)
            try:
                out[key] = float(row.value) if row and row.value else default
            except ValueError:
                out[key] = default
        return out
    finally:
        db.close()


@misc_router.put("/settings/thresholds")
def update_thresholds(body: dict, _: User = Depends(require_admin)):
    db = SessionLocal()
    try:
        for key, (lo, hi, _default) in _THRESHOLD_KEYS.items():
            if key not in body:
                continue
            try:
                v = float(body[key])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"{key} must be a number")
            if not (lo <= v <= hi):
                raise HTTPException(status_code=400, detail=f"{key} must be in [{lo}, {hi}]")
            _set_setting(db, key, str(v))
        return {"ok": True}
    finally:
        db.close()


app.include_router(misc_router)


@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}


@app.get("/api/ready")
def ready(request: Request):
    checks_ok = bool(getattr(request.app.state, "ready", False))
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        checks_ok = False
    state = scheduler.scheduler_status()
    if not state.get("healthy"):
        checks_ok = False
    from .ssh_transport import hostkey_storage_ready

    if not hostkey_storage_ready():
        checks_ok = False
    if settings.ARCHIVE_DIR:
        from .archive_crypto import archive_storage_ready

        if not archive_storage_ready(settings.ARCHIVE_DIR):
            checks_ok = False
    if not checks_ok:
        return JSONResponse(status_code=503, content={"status": "not-ready"})
    return {"status": "ready"}


# ---------------- SPA hosting ----------------
DIST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")

@app.get("/docs", include_in_schema=False)
@app.get("/redoc", include_in_schema=False)
@app.get("/openapi.json", include_in_schema=False)
def disabled_docs():
    raise HTTPException(status_code=404, detail="Not found")

if os.path.isdir(DIST_DIR):
    class _ImmutableAssets(StaticFiles):
        """Hashed filenames are immutable: let browsers cache them for a year.
        Without this, StaticFiles sends only an ETag and browsers re-request
        every chunk on every page load."""

        def file_response(self, *args, **kwargs):
            resp = super().file_response(*args, **kwargs)
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return resp

    app.mount("/assets", _ImmutableAssets(directory=os.path.join(DIST_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        # /api/* must never fall through to the SPA: a deleted/renamed endpoint
        # returning HTML(200) makes the frontend parse JSON out of a doctype and
        # fail silently. Answer a real JSON 404 instead.
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(
                status_code=404,
                content={"detail": f"no such API endpoint: /{full_path}"},
            )
        root_real = os.path.realpath(DIST_DIR)
        candidate = os.path.realpath(os.path.join(DIST_DIR, full_path))
        if (
            full_path
            and candidate.startswith(root_real + os.sep)
            and os.path.isfile(candidate)
        ):
            resp = FileResponse(candidate)
            # hashed asset names are immutable -> cache aggressively;
            # anything else (index.html, favicon...) must revalidate
            if full_path.startswith("assets/"):
                resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                resp.headers["Cache-Control"] = "no-cache"
            return resp
        # SPA entry: MUST revalidate every time, otherwise a stale cached
        # index.html referencing dead hashed chunks = blank page after deploy
        index_resp = FileResponse(os.path.join(DIST_DIR, "index.html"))
        index_resp.headers["Cache-Control"] = "no-cache"
        return index_resp

    logger.info("serving frontend from %s", DIST_DIR)
else:
    @app.get("/", include_in_schema=False)
    def root():
        return JSONResponse({"app": settings.APP_NAME, "message": "frontend not built"})
