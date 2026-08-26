import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), default="")
    email: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[str] = mapped_column(String(16), default="viewer")  # admin | viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

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
    username: Mapped[str] = mapped_column(String(64), nullable=False, default="root")
    password: Mapped[str] = mapped_column(Text, default="")  # encrypted
    private_key: Mapped[str] = mapped_column(Text, default="")  # encrypted
    passphrase: Mapped[str] = mapped_column(Text, default="")  # encrypted
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str] = mapped_column(Text, default="")
    expected_gpu_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    metrics: Mapped[list["ServerMetric"]] = relationship(
        back_populates="server", cascade="all, delete-orphan"
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
    fd_allocated: Mapped[int] = mapped_column(Integer, default=0)
    fd_max: Mapped[int] = mapped_column(Integer, default=0)

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


def new_token(n: int = 32) -> str:
    return secrets.token_urlsafe(n)
