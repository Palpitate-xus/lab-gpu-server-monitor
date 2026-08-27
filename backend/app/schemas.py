from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------- auth / users ----------------
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    email: str
    role: str
    is_active: bool
    created_at: datetime


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=72)
    display_name: str = ""
    email: str = ""
    role: Literal["admin", "viewer"] = "viewer"


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[Literal["admin", "viewer"]] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=6, max_length=72)


class PasswordChange(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=72)


# ---------------- servers ----------------
class ServerBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=22, ge=1, le=65535)
    auth_type: Literal["password", "key"] = "password"
    username: str = Field(default="root", min_length=1, max_length=64)
    password: Optional[str] = None
    private_key: Optional[str] = None
    passphrase: Optional[str] = None
    enabled: bool = True
    server_type: Literal["gpu", "cpu"] = "gpu"
    tags: list[str] = []
    note: str = ""


class ServerCreate(ServerBase):
    pass


class ServerUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    host: Optional[str] = Field(default=None, min_length=1, max_length=255)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    auth_type: Optional[Literal["password", "key"]] = None
    username: Optional[str] = Field(default=None, min_length=1, max_length=64)
    password: Optional[str] = None
    private_key: Optional[str] = None
    passphrase: Optional[str] = None
    enabled: Optional[bool] = None
    server_type: Optional[Literal["gpu", "cpu"]] = None
    tags: Optional[list[str]] = None
    note: Optional[str] = None


class ServerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    host: str
    port: int
    auth_type: str
    # username intentionally NOT returned (SSH account name is sensitive)
    enabled: bool
    server_type: str = "gpu"
    status: Optional[str] = "active"
    status_reason: Optional[str] = None
    status_until: Optional[datetime] = None
    tags: list
    note: str
    created_at: datetime
    updated_at: datetime
    has_password: bool = False
    has_key: bool = False


class ServerStatusUpdate(BaseModel):
    status: Literal["active", "maintenance", "drained", "rma"]
    reason: str = ""
    until: Optional[datetime] = None


class ConnectionTestRequest(BaseModel):
    host: str
    port: int = Field(default=22, ge=1, le=65535)
    auth_type: Literal["password", "key"] = "password"
    username: str
    password: Optional[str] = None
    private_key: Optional[str] = None
    passphrase: Optional[str] = None


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str


# ---------------- metrics ----------------
class MetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    server_id: int
    collected_at: datetime
    hostname: str
    os: str
    kernel: str
    uptime_seconds: int
    cpu_model: str
    cpu_count: int
    cpu_percent: float
    cpu_freq_avg: float
    cpu_temp_package: float
    cores: list
    load1: float
    load5: float
    load15: float
    mem_total_mb: float
    mem_used_mb: float
    mem_available_mb: float
    mem_cached_mb: float
    swap_total_mb: float
    swap_used_mb: float
    disk_total_gb: float
    disk_used_gb: float
    disks: list
    inodes: list = []
    disk_io: list
    net_rx_bytes: float
    net_tx_bytes: float
    net_ifaces: list
    users: list
    cpu_iowait: float = 0
    boot_id: str = ""
    sock_estab: int = 0
    sock_timewait: int = 0
    fd_allocated: int = 0
    fd_max: int = 0
    gpu_count: int
    gpu_driver: str
    gpus: list
    processes: list
    duration: float
    ssh_latency: float = 0
    status: str
    error_code: str = "OK"
    error: str


class DashboardStats(BaseModel):
    servers_total: int = 0
    servers_online: int = 0
    servers_error: int = 0
    servers_disabled: int = 0
    gpus_total: int = 0
    gpu_mem_total_mb: float = 0.0
    gpu_mem_used_mb: float = 0.0
    avg_gpu_util: float = 0.0
    avg_cpu_percent: float = 0.0
    mem_total_mb: float = 0.0
    mem_used_mb: float = 0.0
    disk_total_gb: float = 0.0
    disk_used_gb: float = 0.0


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    username: str
    action: str
    detail: str


# ---------------- alerts ----------------
class AlertRuleBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    metric: Literal[
        "cpu_percent", "mem_percent", "swap_percent", "disk_percent", "load_per_core",
        "gpu_util", "gpu_temp", "gpu_mem_percent", "gpu_power",
    ]
    op: Literal[">", ">=", "<", "<="] = ">"
    threshold: float
    duration_minutes: int = Field(default=0, ge=0, le=1440)
    server_id: Optional[int] = None
    enabled: bool = True


class AlertRuleCreate(AlertRuleBase):
    pass


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    metric: Optional[Literal[
        "cpu_percent", "mem_percent", "swap_percent", "disk_percent", "load_per_core",
        "gpu_util", "gpu_temp", "gpu_mem_percent", "gpu_power",
    ]] = None
    op: Optional[Literal[">", ">=", "<", "<="]] = None
    threshold: Optional[float] = None
    duration_minutes: Optional[int] = Field(default=None, ge=0, le=1440)
    server_id: Optional[int] = None
    enabled: Optional[bool] = None


class AlertRuleOut(AlertRuleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class AlertEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_id: Optional[int]
    rule_name: str
    server_id: int
    server_name: str
    metric: str
    value: float
    threshold: float
    message: str
    triggered_at: datetime
    recovered_at: Optional[datetime]
    acked_at: Optional[datetime] = None
    acked_by: str = ""
    assignee: str = ""
    notified: bool


# ---------------- process actions ----------------
class SettingsUpdate(BaseModel):
    poll_interval: Optional[int] = Field(default=None, ge=10, le=86400)
    retention_days: Optional[int] = Field(default=None, ge=0, le=3650)
    energy_price: Optional[float] = Field(default=None, ge=0, le=100)
    webhook_url: Optional[str] = None
    webhook_template: Optional[str] = None


class ProcessAction(BaseModel):
    action: Literal["kill", "renice"]
    pid: int = Field(ge=1)
    signal: str = "TERM"  # TERM | KILL | HUP ...
    nice: int = Field(default=0, ge=-20, le=19)
