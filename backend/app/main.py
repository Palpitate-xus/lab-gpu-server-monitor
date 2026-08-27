import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .config import get_settings
from .schemas import SettingsUpdate
from .database import Base, SessionLocal, engine, get_db
from .models import AuditLog, Setting, User
from .schemas import AuditLogOut
from .security import get_current_user, hash_password, require_admin
from . import scheduler

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("gpumon")

from .api import alerts, auth, cockpit, enterprise, metrics, servers, server_test, status_page, users  # noqa: E402


@asynccontextmanager
async def lifespan(app):
    from .config import DEFAULT_SECRET_KEY
    if settings.SECRET_KEY == DEFAULT_SECRET_KEY or len(settings.SECRET_KEY) < 16:
        raise RuntimeError(
            "FATAL: SECRET_KEY is missing or still the public default. "
            "Set a strong random SECRET_KEY in .env (it signs JWTs and encrypts "
            "stored SSH credentials). Example: python3 -c 'import secrets;print(secrets.token_urlsafe(48))'"
        )
    # create tables (fresh installs), then run SQL migrations (existing DBs)
    Base.metadata.create_all(bind=engine)
    try:
        from .migrate import run_migrations

        applied = run_migrations()
        if applied:
            logger.info("applied migrations: %s", ", ".join(applied))
    except Exception:
        logger.exception("migration failed (continuing with create_all schema)")
    # create initial admin if none
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.role == "admin").first():
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
    logger.info("startup complete")
    yield
    logger.info("shutting down")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan,
    # API docs are disabled unless explicitly enabled (DOCS_ENABLED=yes) —
    # the schema maps the whole attack surface; don't hand it out unauthenticated.
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)


# ---------------- security headers ----------------
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        # SPA: no inline <script> is used by the Vite build; style-src needs
        # 'unsafe-inline' for ECharts/Element Plus runtime styles.
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; font-src 'self' data:; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        if request.url.scheme == "https":
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp


app.add_middleware(SecurityHeadersMiddleware)


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
    finally:
        db.close()
    return {
        "poll_interval": interval,
        "retention_days": retention_days,
        "webhook_url": (wh.value if wh else "") or "",
        "webhook_template": (wt.value if wt else "") or "",
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
        if body.webhook_url is not None:
            url = str(body.webhook_url or "")
            if url:
                from .notifier import _validate_webhook_url
                ok, why = _validate_webhook_url(url)
                if not ok:
                    raise HTTPException(status_code=400, detail=f"webhook url rejected: {why}")
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


# ---------------- SPA hosting ----------------
import os  # noqa: E402

DIST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")

if os.path.isdir(DIST_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST_DIR, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        root_real = os.path.realpath(DIST_DIR)
        candidate = os.path.realpath(os.path.join(DIST_DIR, full_path))
        if (
            full_path
            and candidate.startswith(root_real + os.sep)
            and os.path.isfile(candidate)
        ):
            return FileResponse(candidate)
        return FileResponse(os.path.join(DIST_DIR, "index.html"))

    logger.info("serving frontend from %s", DIST_DIR)
else:
    @app.get("/", include_in_schema=False)
    def root():
        return JSONResponse({"app": settings.APP_NAME, "message": "frontend not built; API docs at /docs"})
