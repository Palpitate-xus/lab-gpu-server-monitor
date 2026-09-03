from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


PUBLIC_SECRET_PLACEHOLDERS = frozenset(
    {
        "change-me",
        "change-me-in-production-please",
        "change-me-run-openssl-rand-hex-32",
        "changeme",
        "secret",
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "GPU Monitor"
    # JWT signing and stored-credential encryption deliberately have separate
    # key lifecycles. SECRET_KEY remains a compatibility fallback so existing
    # encrypted credentials can be migrated without data loss.
    JWT_SIGNING_KEY: str = ""
    CREDENTIAL_ENCRYPTION_KEYS: str = ""
    SECRET_KEY: str = ""
    JWT_ISSUER: str = "gpu-monitor"
    JWT_AUDIENCE: str = "gpu-monitor-api"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 2 * 60  # 2h (was 12h; no refresh flow yet)

    # Browser sessions use HttpOnly cookies. Set COOKIE_SECURE=no only for
    # loopback development; production traffic must terminate TLS first.
    COOKIE_SECURE: str = "yes"
    COOKIE_SAMESITE: str = "strict"
    # Loopback-only development escape hatch. Production must leave this off.
    ALLOW_INSECURE_HTTP: str = "no"
    MAX_REQUEST_BODY_BYTES: int = 1024 * 1024
    REMOTE_PROCESS_CONTROL_ENABLED: str = "no"
    ALLOW_ROOT_SSH: str = "no"
    REQUIRE_ADMIN_MFA: str = "yes"

    # Set to "yes" only when running behind a reverse proxy you control;
    # enables X-Forwarded-For for rate limiting.
    TRUST_PROXY: str = "no"
    TRUSTED_PROXY_CIDRS: str = "127.0.0.1/32,::1/128"

    @property
    def trust_proxy(self) -> bool:
        return str(self.TRUST_PROXY).strip().lower() in ("yes", "1", "true")

    @property
    def cookie_secure(self) -> bool:
        return str(self.COOKIE_SECURE).strip().lower() in ("yes", "1", "true")

    @property
    def allow_insecure_http(self) -> bool:
        return str(self.ALLOW_INSECURE_HTTP).strip().lower() in ("yes", "1", "true")

    @property
    def remote_process_control_enabled(self) -> bool:
        return str(self.REMOTE_PROCESS_CONTROL_ENABLED).strip().lower() in ("yes", "1", "true")

    @property
    def allow_root_ssh(self) -> bool:
        return str(self.ALLOW_ROOT_SSH).strip().lower() in ("yes", "1", "true")

    @property
    def require_admin_mfa(self) -> bool:
        return str(self.REQUIRE_ADMIN_MFA).strip().lower() in ("yes", "1", "true")

    @property
    def jwt_signing_key(self) -> str:
        # Context derivation prevents the legacy root secret itself from being
        # reused directly as a JWT HMAC key. New deployments set JWT_SIGNING_KEY.
        if self.JWT_SIGNING_KEY.strip():
            return self.JWT_SIGNING_KEY.strip()
        if self.SECRET_KEY.strip():
            import hashlib

            return hashlib.sha256((self.SECRET_KEY + "|jwt-signing").encode()).hexdigest()
        return ""

    @property
    def credential_encryption_keys(self) -> tuple[str, ...]:
        raw = self.CREDENTIAL_ENCRYPTION_KEYS.strip() or self.SECRET_KEY.strip()
        return tuple(v.strip() for v in raw.split(",") if v.strip())

    # mysql: mysql+pymysql://user:pass@host:3306/gpu_monitor?charset=utf8mb4
    # sqlite: sqlite:///./data/gpu_monitor.db
    DATABASE_URL: str = "sqlite:///./data/gpu_monitor.db"
    DATABASE_SSL_CA: str = ""
    DATABASE_SSL_CERT: str = ""
    DATABASE_SSL_KEY: str = ""
    DB_ECHO: bool = False
    DATA_DIR: str = "./data"
    AUTO_MIGRATE: str = "no"

    # Optional shared cache backend (redis://... / rediss://...). Empty =
    # in-process memory cache, which is correct for the single-worker setup.
    REDIS_URL: str = ""
    REDIS_SSL_CA: str = ""

    # Initial admin account (created on first run)
    INIT_ADMIN_USERNAME: str = ""
    INIT_ADMIN_PASSWORD: str = ""

    # Metrics polling
    POLL_INTERVAL_SECONDS: int = 60
    METRICS_RETENTION_HOURS: int = 0  # 0 = keep forever (per-metric history is the point)
    RETENTION_DAYS_SETTING: str = "retention_days"  # settings key, 0 = forever
    # Directory receiving daily tar.gz exports of metrics that retention is
    # about to delete. Empty = retention refuses to delete (no data loss).
    ARCHIVE_DIR: str = ""
    # 32-byte AES key encoded as exactly 64 hexadecimal characters.
    ARCHIVE_ENCRYPTION_KEY: str = ""
    SSH_CONNECT_TIMEOUT: int = 8
    SSH_COMMAND_TIMEOUT: int = 30

    # CORS (dev mode: frontend runs on its own port)
    # CORS: empty = same-origin only (SPA served by the API itself, safest).
    # Set a comma-separated origin list ONLY for split-domain dev deployments.
    CORS_ORIGINS: str = ""

    @property
    def auto_migrate(self) -> bool:
        return str(self.AUTO_MIGRATE).strip().lower() in ("yes", "1", "true")


@lru_cache
def get_settings() -> Settings:
    return Settings()
