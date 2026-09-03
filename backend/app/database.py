import ipaddress
import logging
import os

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings

settings = get_settings()
logger = logging.getLogger("gpumon.db")

# Files created by SQLite and maintenance scripts must never inherit a broad
# service-manager or interactive-shell umask.
os.umask(0o077)
os.makedirs(settings.DATA_DIR, mode=0o700, exist_ok=True)
if os.path.islink(settings.DATA_DIR) or not os.path.isdir(settings.DATA_DIR):
    raise RuntimeError("FATAL: DATA_DIR must be a real directory")
os.chmod(settings.DATA_DIR, 0o700)

try:
    _configured_url = make_url(settings.DATABASE_URL)
except Exception:
    _configured_url = None
IS_MYSQL = bool(_configured_url and _configured_url.get_backend_name() == "mysql")
_sqlite_database_path = ""
if _configured_url and _configured_url.get_backend_name() == "sqlite":
    configured_database = _configured_url.database or ""
    if configured_database and configured_database != ":memory:":
        _sqlite_database_path = os.path.abspath(configured_database)
        if os.path.islink(_sqlite_database_path):
            raise RuntimeError("FATAL: SQLite database path must not be a symbolic link")
        if os.path.exists(_sqlite_database_path):
            os.chmod(_sqlite_database_path, 0o600)


def database_security_errors() -> list[str]:
    """Return transport/account errors for every process that uses the DB."""
    errors: list[str] = []
    try:
        db_url = make_url(settings.DATABASE_URL)
        if db_url.drivername not in {"sqlite", "sqlite+pysqlite", "mysql+pymysql"}:
            errors.append(
                "unsupported database driver; use sqlite, sqlite+pysqlite, or mysql+pymysql"
            )
        password = db_url.password or ""
        if password.lower() in {
            "admin123",
            "gpumon_pass_2024",
            "password",
            "changeme",
        }:
            errors.append("DATABASE_URL contains a public/default password")
        if db_url.drivername == "mysql+pymysql":
            ambiguous_tls_options = sorted(
                key
                for key in db_url.query
                if key.casefold() == "ssl" or key.casefold().startswith("ssl_")
            )
            if ambiguous_tls_options:
                errors.append(
                    "DATABASE_URL must not contain TLS query options; use the "
                    "DATABASE_SSL_* settings only (found: "
                    + ", ".join(ambiguous_tls_options)
                    + ")"
                )
            if len(password) < 16:
                errors.append("the MySQL account password must contain at least 16 characters")
            if (db_url.username or "").lower() in {"root", "admin", "administrator"}:
                errors.append("the MySQL account must not be a database administrator")
            if bool(settings.DATABASE_SSL_CERT) != bool(settings.DATABASE_SSL_KEY):
                errors.append("DATABASE_SSL_CERT and DATABASE_SSL_KEY must be configured together")
            host = (db_url.host or "").strip("[]")
            unix_socket = bool(db_url.query.get("unix_socket"))
            try:
                local_ip = bool(host and ipaddress.ip_address(host).is_loopback)
            except ValueError:
                local_ip = False
            if not settings.DATABASE_SSL_CA and not (unix_socket or local_ip):
                errors.append(
                    "non-loopback MySQL requires DATABASE_SSL_CA; plaintext database "
                    "credentials and traffic are not permitted"
                )
    except Exception:
        errors.append("DATABASE_URL is invalid")
    if settings.DB_ECHO:
        errors.append("DB_ECHO must be disabled because SQL parameters may contain secrets")
    return errors


_database_errors = database_security_errors()
if _database_errors:
    raise RuntimeError("FATAL database security configuration:\n- " + "\n- ".join(_database_errors))

if not IS_MYSQL:
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        # WAL lets collector writers and API readers proceed concurrently;
        # foreign_keys makes ON DELETE CASCADE behave like MySQL
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
        if _sqlite_database_path:
            os.chmod(_sqlite_database_path, 0o600)
else:
    connect_args = {}
    if settings.DATABASE_SSL_CA:
        ssl_options = {
            "ca": settings.DATABASE_SSL_CA,
            "check_hostname": True,
        }
        if settings.DATABASE_SSL_CERT:
            ssl_options["cert"] = settings.DATABASE_SSL_CERT
        if settings.DATABASE_SSL_KEY:
            ssl_options["key"] = settings.DATABASE_SSL_KEY
        connect_args["ssl"] = ssl_options
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_size=10,
        max_overflow=20,
        echo=settings.DB_ECHO,
        connect_args=connect_args,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
