import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .config import get_settings
from .database import Base, SessionLocal, engine, get_db
from .models import AuditLog, Setting, User
from .schemas import AuditLogOut
from .security import get_current_user, hash_password, require_admin
from . import scheduler

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("gpumon")

from .api import alerts, auth, metrics, servers, server_test, users  # noqa: E402


@asynccontextmanager
async def lifespan(app):
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
    finally:
        db.close()
    scheduler.start_scheduler()
    logger.info("startup complete")
    yield
    logger.info("shutting down")


app = FastAPI(title=settings.APP_NAME, version="1.0.0", lifespan=lifespan)

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


# ---------------- audit logs + settings ----------------
misc_router = APIRouter(prefix="/api", tags=["misc"])


@misc_router.get("/audit-logs", response_model=list[AuditLogOut])
def list_audit_logs(
    limit: int = 100,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return db.query(AuditLog).order_by(AuditLog.ts.desc()).limit(min(limit, 500)).all()


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
def update_app_settings(body: dict, _: User = Depends(require_admin)):
    db = SessionLocal()
    try:
        if "poll_interval" in body and body["poll_interval"] is not None:
            try:
                interval = int(body["poll_interval"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="poll_interval must be an integer")
            if interval < 10:
                raise HTTPException(status_code=400, detail="poll_interval must be >= 10 seconds")
            _set_setting(db, "poll_interval", str(interval))
        if "retention_days" in body and body["retention_days"] is not None:
            try:
                days = int(body["retention_days"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="retention_days must be an integer")
            if days < 0:
                raise HTTPException(status_code=400, detail="retention_days must be >= 0 (0 = keep forever)")
            _set_setting(db, "retention_days", str(days))
        if "webhook_url" in body:
            _set_setting(db, "alert_webhook_url", str(body["webhook_url"] or ""))
        if "webhook_template" in body:
            _set_setting(db, "alert_webhook_template", str(body["webhook_template"] or ""))
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
        candidate = os.path.join(DIST_DIR, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(DIST_DIR, "index.html"))

    logger.info("serving frontend from %s", DIST_DIR)
else:
    @app.get("/", include_in_schema=False)
    def root():
        return JSONResponse({"app": settings.APP_NAME, "message": "frontend not built; API docs at /docs"})
