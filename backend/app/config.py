from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "GPU Monitor"
    SECRET_KEY: str = "change-me-in-production-please"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 2 * 60  # 2h (was 12h; no refresh flow yet)

    # Set to "yes" only when running behind a reverse proxy you control;
    # enables X-Forwarded-For for rate limiting.
    TRUST_PROXY: str = "no"

    # mysql: mysql+pymysql://user:pass@host:3306/gpu_monitor?charset=utf8mb4
    # sqlite: sqlite:///./data/gpu_monitor.db
    DATABASE_URL: str = "mysql+pymysql://gpumon:gpumon_pass_2024@172.17.0.1:3306/gpu_monitor?charset=utf8mb4"
    DB_ECHO: bool = False
    DATA_DIR: str = "./data"

    # Initial admin account (created on first run)
    INIT_ADMIN_USERNAME: str = "admin"
    INIT_ADMIN_PASSWORD: str = "admin123"

    # Metrics polling
    POLL_INTERVAL_SECONDS: int = 60
    METRICS_RETENTION_HOURS: int = 0  # 0 = keep forever (per-metric history is the point)
    RETENTION_DAYS_SETTING: str = "retention_days"  # settings key, 0 = forever
    SSH_CONNECT_TIMEOUT: int = 8
    SSH_COMMAND_TIMEOUT: int = 30

    # CORS (dev mode: frontend runs on its own port)
    # CORS: empty = same-origin only (SPA served by the API itself, safest).
    # Set a comma-separated origin list ONLY for split-domain dev deployments.
    CORS_ORIGINS: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
