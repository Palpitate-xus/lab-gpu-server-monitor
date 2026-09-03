import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_token(n: int = 32) -> str:
    return secrets.token_urlsafe(n)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), default="")
    email: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[str] = mapped_column(String(16), default="viewer")  # admin | viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # auth_id cannot be reused after deletion; token_version persists session
    # invalidation across restarts and multiple application replicas.
    auth_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False, default=lambda: new_token(24)
    )
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    mfa_secret: Mapped[str] = mapped_column(Text, default="")  # encrypted TOTP seed
    mfa_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mfa_last_counter: Mapped[int] = mapped_column(BigInteger, nullable=False, default=-1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def mfa_enrolled(self) -> bool:
        return bool(self.mfa_secret and self.mfa_confirmed)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class Server(Base):
    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, default=22)
    auth_type: Mapped[str] = mapped_column(String(16), default="password")  # password | key
    username: Mapped[str] = mapped_column(String(64), nullable=False, default="gpumon")
    password: Mapped[str] = mapped_column(Text, default="")  # encrypted
    private_key: Mapped[str] = mapped_column(Text, default="")  # encrypted
    passphrase: Mapped[str] = mapped_column(Text, default="")  # encrypted
    # out-of-band BMC (IPMI lanplus), collected from the monitor host
    bmc_host: Mapped[str] = mapped_column(String(255), default="")
    bmc_user: Mapped[str] = mapped_column(String(64), default="")
    bmc_password: Mapped[str] = mapped_column(Text, default="")  # encrypted
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    server_type: Mapped[str] = mapped_column(String(8), default="gpu")  # gpu | cpu
    tags: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str] = mapped_column(Text, default="")
    expected_gpu_count: Mapped[int] = mapped_column(Integer, default=0)
    # lifecycle: active | maintenance | drained | rma
    status: Mapped[str] = mapped_column(String(16), default="active")
    status_reason: Mapped[str] = mapped_column(Text, default="")
    status_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    metrics: Mapped[list["ServerMetric"]] = relationship(
        back_populates="server", cascade="all, delete-orphan", passive_deletes=True
    )


class ServerMetric(Base):
    __tablename__ = "server_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("servers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    # host-level
    hostname: Mapped[str] = mapped_column(String(255), default="")
    os: Mapped[str] = mapped_column(String(255), default="")
    kernel: Mapped[str] = mapped_column(String(255), default="")
    uptime_seconds: Mapped[int] = mapped_column(Integer, default=0)
    boot_id: Mapped[str] = mapped_column(String(128), default="")
    cpu_model: Mapped[str] = mapped_column(String(255), default="")
    cpu_count: Mapped[int] = mapped_column(Integer, default=0)
    cpu_percent: Mapped[float] = mapped_column(Float, default=0)
    cpu_iowait: Mapped[float] = mapped_column(Float, default=0)
    cpu_freq_avg: Mapped[float] = mapped_column(Float, default=0)
    cpu_temp_package: Mapped[float] = mapped_column(Float, default=0)
    cores: Mapped[list] = mapped_column(JSON, default=list)  # [{id,util,freq_mhz,temp}]
    load1: Mapped[float] = mapped_column(Float, default=0)
    load5: Mapped[float] = mapped_column(Float, default=0)
    load15: Mapped[float] = mapped_column(Float, default=0)
    mem_total_mb: Mapped[float] = mapped_column(Float, default=0)
    mem_used_mb: Mapped[float] = mapped_column(Float, default=0)
    mem_available_mb: Mapped[float] = mapped_column(Float, default=0)
    mem_cached_mb: Mapped[float] = mapped_column(Float, default=0)
    swap_total_mb: Mapped[float] = mapped_column(Float, default=0)
    swap_used_mb: Mapped[float] = mapped_column(Float, default=0)
    disk_total_gb: Mapped[float] = mapped_column(Float, default=0)
    disk_used_gb: Mapped[float] = mapped_column(Float, default=0)
    disks: Mapped[list] = mapped_column(JSON, default=list)
    inodes: Mapped[list] = mapped_column(JSON, default=list)
    disk_io: Mapped[list] = mapped_column(JSON, default=list)
    net_rx_bytes: Mapped[float] = mapped_column(Float, default=0)
    net_tx_bytes: Mapped[float] = mapped_column(Float, default=0)
    net_ifaces: Mapped[list] = mapped_column(JSON, default=list)
    users: Mapped[list] = mapped_column(JSON, default=list)
    sock_estab: Mapped[int] = mapped_column(Integer, default=0)
    sock_timewait: Mapped[int] = mapped_column(Integer, default=0)
    fd_allocated: Mapped[int] = mapped_column(BigInteger, default=0)
    fd_max: Mapped[int] = mapped_column(BigInteger, default=0)

    # gpu summary
    gpu_count: Mapped[int] = mapped_column(Integer, default=0)
    gpu_driver: Mapped[str] = mapped_column(String(128), default="")
    gpus: Mapped[list] = mapped_column(JSON, default=list)
    processes: Mapped[list] = mapped_column(JSON, default=list)
    duration: Mapped[float] = mapped_column(Float, default=0)
    ssh_latency: Mapped[float] = mapped_column(Float, default=0)

    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | error
    error_code: Mapped[str] = mapped_column(String(32), default="OK")
    error: Mapped[str] = mapped_column(Text, default="")

    server: Mapped["Server"] = relationship(back_populates="metrics")


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    op: Mapped[str] = mapped_column(String(2), default=">")
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    server_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("servers.id", ondelete="CASCADE"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True
    )
    rule_name: Mapped[str] = mapped_column(String(128), default="")
    server_id: Mapped[int] = mapped_column(Integer, nullable=False)
    server_name: Mapped[str] = mapped_column(String(128), default="")
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[float] = mapped_column(Float, default=0)
    threshold: Mapped[float] = mapped_column(Float, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    recovered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_by: Mapped[str] = mapped_column(String(64), default="")
    assignee: Mapped[str] = mapped_column(String(64), default="")
    notified: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(Text, default="")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class HostInventory(Base):
    __tablename__ = "host_inventory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    machine_id: Mapped[str] = mapped_column(String(128), default="")
    dmi: Mapped[dict] = mapped_column(JSON, default=dict)
    lscpu: Mapped[dict] = mapped_column(JSON, default=dict)
    numa: Mapped[dict] = mapped_column(JSON, default=dict)
    gpu_topology: Mapped[str] = mapped_column(Text, default="")
    pci_numa: Mapped[list] = mapped_column(JSON, default=list)
    disks: Mapped[list] = mapped_column(JSON, default=list)
    nics: Mapped[list] = mapped_column(JSON, default=list)
    ip_addrs: Mapped[list] = mapped_column(JSON, default=list)
    ib: Mapped[dict] = mapped_column(JSON, default=dict)
    time_info: Mapped[dict] = mapped_column(JSON, default=dict)
    gpu_baseline: Mapped[list] = mapped_column(JSON, default=list)


class KernelEventRow(Base):
    __tablename__ = "kernel_events"
    __table_args__ = (UniqueConstraint("server_id", "dedup_hash", name="uq_kernel_dedup"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    boot_id: Mapped[str] = mapped_column(String(128), default="")
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    gpu_uuid: Mapped[str] = mapped_column(String(64), default="")
    xid: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    raw_message: Mapped[str] = mapped_column(Text, default="")
    dedup_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class SlowHealth(Base):
    __tablename__ = "slow_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    nvme_smart: Mapped[list] = mapped_column(JSON, default=list)
    mdraid: Mapped[dict] = mapped_column(JSON, default=dict)
    nfs_mounts: Mapped[list] = mapped_column(JSON, default=list)
    systemd_failed: Mapped[list] = mapped_column(JSON, default=list)
    services: Mapped[dict] = mapped_column(JSON, default=dict)
    mig: Mapped[list] = mapped_column(JSON, default=list)
    nvlink: Mapped[dict] = mapped_column(JSON, default=dict)
    ipmi: Mapped[list] = mapped_column(JSON, default=list)
    duration: Mapped[float] = mapped_column(Float, default=0)


class GpuBaseline(Base):
    __tablename__ = "gpu_baseline"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(Integer, nullable=False)
    gpu_uuid: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), default="")
    serial: Mapped[str] = mapped_column(String(128), default="")
    pci_bus_id: Mapped[str] = mapped_column(String(32), default="")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    missing_since: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ecc_uncorrected_baseline: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class ServerNote(Base):
    """Maintenance / repair ledger entries attached to a server."""

    __tablename__ = "server_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    kind: Mapped[str] = mapped_column(String(16), default="note")  # note | maintenance | repair
    content: Mapped[str] = mapped_column(Text, default="")


class ServerMetricHourly(Base):
    """Downsampled hourly aggregates for long-range trends and utilization reports."""

    __tablename__ = "server_metrics_hourly"
    __table_args__ = (UniqueConstraint("server_id", "hour", name="uq_metric_hourly"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    hour: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    samples: Mapped[int] = mapped_column(Integer, default=0)
    ok_samples: Mapped[int] = mapped_column(Integer, default=0)
    cpu_avg: Mapped[float] = mapped_column(Float, default=0)
    cpu_max: Mapped[float] = mapped_column(Float, default=0)
    mem_avg_pct: Mapped[float] = mapped_column(Float, default=0)
    gpu_util_avg: Mapped[float] = mapped_column(Float, default=0)
    gpu_util_max: Mapped[float] = mapped_column(Float, default=0)
    gpu_mem_pct_avg: Mapped[float] = mapped_column(Float, default=0)
    gpu_power_avg: Mapped[float] = mapped_column(Float, default=0)
    net_rx_avg_bps: Mapped[float] = mapped_column(Float, default=0)
    net_tx_avg_bps: Mapped[float] = mapped_column(Float, default=0)
    idle_held_minutes: Mapped[int] = mapped_column(Integer, default=0)  # 空占样本分钟数


class IpmiSnapshot(Base):
    """Full out-of-band IPMI dump (everything ipmitool returned)."""

    __tablename__ = "ipmi_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str] = mapped_column(Text, default="")
    mc_info: Mapped[dict] = mapped_column(JSON, default=dict)
    chassis: Mapped[dict] = mapped_column(JSON, default=dict)
    power: Mapped[dict] = mapped_column(JSON, default=dict)
    sensors: Mapped[list] = mapped_column(JSON, default=list)
    sel: Mapped[list] = mapped_column(JSON, default=list)
    sel_info: Mapped[dict] = mapped_column(JSON, default=dict)
    fru: Mapped[list] = mapped_column(JSON, default=list)
    lan: Mapped[dict] = mapped_column(JSON, default=dict)
    power_w: Mapped[float] = mapped_column(Float, default=0)
    duration: Mapped[float] = mapped_column(Float, default=0)


class WebhookChannel(Base):
    """Notification targets; each channel filters by severity."""

    __tablename__ = "webhook_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    template: Mapped[str] = mapped_column(Text, default="")
    min_severity: Mapped[str] = mapped_column(String(16), default="info")  # info | warning | critical
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
