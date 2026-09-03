from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker

from backend.app import health as health_module
from backend.app import scheduler as scheduler_module
from backend.app.api.cockpit import _cluster_history
from backend.app.api.metrics import _latest_payload, server_latest
from backend.app.api.enterprise import cluster_utilization_report
from backend.app.api.status_page import _build_public_payload
from backend.app.cache import InMemoryBackend
from backend.app.database import Base
from backend.app.models import (
    Server,
    AlertRule,
    GpuBaseline,
    KernelEventRow,
    ServerMetric,
    ServerMetricHourly,
    ServerProcessSnapshot,
    Setting,
)


def test_latest_metric_hydrates_latest_only_process_snapshot():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    assert "ix_server_metrics_server_time" in {
        item["name"] for item in inspect(engine).get_indexes("server_metrics")
    }
    assert "idx_alert_open_time" in {
        item["name"] for item in inspect(engine).get_indexes("alert_events")
    }
    db = sessionmaker(bind=engine)()
    try:
        server = Server(name="perf-test", host="127.0.0.1")
        db.add(server)
        db.flush()
        collected_at = datetime(2026, 1, 2, 3, 4, 5)
        db.add(ServerMetric(
            server_id=server.id,
            collected_at=collected_at,
            processes=[],
        ))
        db.add(ServerProcessSnapshot(
            server_id=server.id,
            collected_at=collected_at,
            processes=[{
                "pid": 42,
                "cpu": 12.5,
                "user": "private-user",
                "command": "private command --secret",
            }],
        ))
        db.commit()

        full = _latest_payload(db, slim=False)
        assert full[0]["processes"][0]["pid"] == 42
        assert _latest_payload(db, slim=True)[0]["processes"] == []
        # Public metric responses retain resource data but keep process
        # identity/argv minimization unchanged.
        assert server_latest(server.id, db, object())["processes"] == [
            {"pid": 42, "cpu": 12.5}
        ]

        snapshot = db.get(ServerProcessSnapshot, server.id)
        snapshot.collected_at = collected_at + timedelta(seconds=1)
        db.commit()
        # A concurrent/newer snapshot must never be attached to an older row.
        assert server_latest(server.id, db, object())["processes"] == []
    finally:
        db.close()
        engine.dispose()


def test_public_status_uses_fixed_bulk_query_count():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        gpu_server = Server(name="gpu-node", host="127.0.0.1", server_type="gpu")
        cpu_server = Server(name="cpu-node", host="127.0.0.2", server_type="cpu")
        db.add_all([gpu_server, cpu_server])
        db.flush()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        db.add_all([
            ServerMetric(
                server_id=gpu_server.id,
                collected_at=now - timedelta(days=1),
                status="ok",
                ssh_latency=0.1,
            ),
            ServerMetric(
                server_id=gpu_server.id,
                collected_at=now,
                status="error",
                ssh_latency=0.2,
            ),
            ServerMetric(
                server_id=cpu_server.id,
                collected_at=now,
                status="ok",
                ssh_latency=0.3,
            ),
        ])
        db.commit()

        selects = []

        def record_select(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        event.listen(engine, "before_cursor_execute", record_select)
        payload = _build_public_payload(db, {"show_history_days": 2})
        event.remove(engine, "before_cursor_execute", record_select)

        assert len(selects) == 4
        assert payload["overall"] == {
            "all_operational": False,
            "servers_total": 2,
            "servers_online": 1,
        }
        first = payload["servers"][0]
        assert first["online"] is False
        assert first["uptime_30d"] == 50.0
        assert sum(day["n"] for day in first["history"]) == 2
    finally:
        db.close()
        engine.dispose()


def test_utilization_report_fetches_all_servers_in_one_data_query():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        first = Server(
            name="gpu-a", host="127.0.0.1", server_type="gpu", tags=["team-a"]
        )
        second = Server(
            name="gpu-b", host="127.0.0.2", server_type="gpu", tags=["team-a"]
        )
        db.add_all([first, second])
        db.flush()
        hour = datetime.now(timezone.utc).replace(tzinfo=None, minute=0, second=0)
        db.add_all([
            ServerMetricHourly(
                server_id=first.id,
                hour=hour,
                samples=10,
                ok_samples=8,
                gpu_util_avg=50,
                gpu_power_avg=100,
                idle_held_minutes=30,
            ),
            ServerMetricHourly(
                server_id=second.id,
                hour=hour,
                samples=10,
                ok_samples=10,
                gpu_util_avg=25,
                gpu_power_avg=200,
                idle_held_minutes=0,
            ),
        ])
        db.commit()

        selects = []

        def record_select(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        event.listen(engine, "before_cursor_execute", record_select)
        payload = cluster_utilization_report(hours=24, tag="team-a", db=db, user=object())
        event.remove(engine, "before_cursor_execute", record_select)

        assert len(selects) == 2
        assert [row["server_name"] for row in payload["servers"]] == ["gpu-a", "gpu-b"]
        assert payload["servers"][0]["gpu_util_avg"] == 50.0
        assert payload["total_idle_gpu_hours"] == 0.5
    finally:
        db.close()
        engine.dispose()


def test_memory_cache_periodically_releases_expired_variants(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("backend.app.cache.time.monotonic", lambda: now[0])
    cache = InMemoryBackend()

    cache.set("old-variant", {"large": "payload"}, ttl=1)
    assert "old-variant" in cache._data

    now[0] = 161.0
    cache.set("current-variant", {"small": "payload"}, ttl=30)

    assert "old-variant" not in cache._data
    assert cache.get("current-variant") == {"small": "payload"}


def test_alert_evaluation_loads_latest_metrics_in_one_query(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()
    try:
        servers = [
            Server(name=f"node-{index}", host=f"127.0.0.{index + 1}")
            for index in range(3)
        ]
        db.add_all(servers)
        db.flush()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        db.add_all([
            ServerMetric(
                server_id=server.id,
                collected_at=now,
                status="ok",
                cpu_percent=10,
            )
            for server in servers
        ])
        db.add(AlertRule(
            name="never-breached",
            metric="cpu_percent",
            op=">",
            threshold=100,
            enabled=True,
        ))
        db.commit()

        metric_selects = []

        def record_metric_select(_conn, _cursor, statement, _params, _context, _many):
            normalized = statement.lower()
            if normalized.lstrip().startswith("select") and "from server_metrics" in normalized:
                metric_selects.append(statement)

        event.listen(engine, "before_cursor_execute", record_metric_select)
        monkeypatch.setattr(scheduler_module, "SessionLocal", session_factory)
        scheduler_module._eval_alerts()
        event.remove(engine, "before_cursor_execute", record_metric_select)

        assert len(metric_selects) == 1
    finally:
        db.close()
        engine.dispose()


def test_hourly_rollup_batches_server_metric_reads(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()
    try:
        first = Server(name="rollup-a", host="127.0.0.1")
        second = Server(name="rollup-b", host="127.0.0.2")
        db.add_all([first, second])
        db.flush()
        hour_end = datetime.now(timezone.utc).replace(
            tzinfo=None, minute=0, second=0, microsecond=0
        )
        hour_start = hour_end - timedelta(hours=1)
        gpu = {
            "uuid": "GPU-1",
            "utilization": 0,
            "mem_used_mb": 40,
            "mem_total_mb": 100,
            "power_draw": 50,
        }
        db.add_all([
            ServerMetric(
                server_id=first.id,
                collected_at=hour_start + timedelta(minutes=10),
                status="ok",
                cpu_percent=10,
                mem_used_mb=50,
                mem_total_mb=100,
                gpus=[gpu],
            ),
            ServerMetric(
                server_id=first.id,
                collected_at=hour_start + timedelta(minutes=40),
                status="ok",
                cpu_percent=30,
                mem_used_mb=70,
                mem_total_mb=100,
                gpus=[gpu],
            ),
            ServerMetric(
                server_id=second.id,
                collected_at=hour_start + timedelta(minutes=20),
                status="error",
            ),
            ServerMetricHourly(
                server_id=first.id,
                hour=hour_start,
                samples=999,
            ),
            Setting(key="poll_interval", value="30"),
        ])
        db.commit()

        metric_selects = []

        def record_metric_select(_conn, _cursor, statement, _params, _context, _many):
            normalized = statement.lower()
            if normalized.lstrip().startswith("select") and "from server_metrics " in normalized:
                metric_selects.append(statement)

        event.listen(engine, "before_cursor_execute", record_metric_select)
        monkeypatch.setattr(scheduler_module, "SessionLocal", session_factory)
        scheduler_module._hourly_aggregate()
        event.remove(engine, "before_cursor_execute", record_metric_select)

        db.expire_all()
        rows = db.query(ServerMetricHourly).order_by(ServerMetricHourly.server_id).all()
        assert len(metric_selects) == 1
        assert len(rows) == 2
        assert (rows[0].samples, rows[0].ok_samples, rows[0].cpu_avg) == (2, 2, 20.0)
        assert rows[0].mem_avg_pct == 60.0
        assert rows[0].idle_held_minutes == 1
        assert (rows[1].samples, rows[1].ok_samples) == (1, 0)
    finally:
        db.close()
        engine.dispose()


def test_kernel_event_dedup_uses_one_lookup_per_batch(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()
    try:
        kernel_event = SimpleNamespace(
            event_type="GPU_XID",
            severity="critical",
            gpu_uuid="GPU-1",
            xid=79,
            message="GPU error",
            raw_message="NVRM: Xid 79",
        )
        selects = []

        def record_select(_conn, _cursor, statement, _params, _context, _many):
            normalized = statement.lower()
            if normalized.lstrip().startswith("select") and "from kernel_events" in normalized:
                selects.append(statement)

        event.listen(engine, "before_cursor_execute", record_select)
        monkeypatch.setattr(scheduler_module, "SessionLocal", session_factory)
        scheduler_module._store_kernel_events(7, "boot-a", [kernel_event, kernel_event])
        scheduler_module._store_kernel_events(7, "boot-a", [kernel_event, kernel_event])
        event.remove(engine, "before_cursor_execute", record_select)

        assert len(selects) == 2
        assert db.query(KernelEventRow).count() == 1
    finally:
        db.close()
        engine.dispose()


def test_gpu_baseline_refresh_uses_one_lookup_per_server(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()
    try:
        selects = []

        def record_select(_conn, _cursor, statement, _params, _context, _many):
            normalized = statement.lower()
            if normalized.lstrip().startswith("select") and "from gpu_baseline" in normalized:
                selects.append(statement)

        gpus = [
            {
                "uuid": f"GPU-{index}",
                "name": "NVIDIA Test",
                "serial": str(index),
                "pci_bus_id": f"0000:0{index}:00.0",
            }
            for index in range(3)
        ]
        event.listen(engine, "before_cursor_execute", record_select)
        monkeypatch.setattr(health_module, "SessionLocal", session_factory)
        health_module.update_gpu_baseline(9, gpus)
        health_module.update_gpu_baseline(9, gpus)
        event.remove(engine, "before_cursor_execute", record_select)

        assert len(selects) == 2
        assert db.query(GpuBaseline).count() == 3
    finally:
        db.close()
        engine.dispose()


def test_cluster_history_online_aggregation_preserves_bucket_math():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        first = Server(name="history-a", host="127.0.0.1")
        second = Server(name="history-b", host="127.0.0.2")
        db.add_all([first, second])
        db.flush()
        minute = datetime.now(timezone.utc).replace(
            tzinfo=None, second=0, microsecond=0
        ) - timedelta(minutes=2)
        db.add_all([
            ServerMetric(
                server_id=first.id,
                collected_at=minute + timedelta(seconds=1),
                status="ok",
                cpu_percent=10,
                mem_used_mb=50,
                mem_total_mb=100,
                gpus=[{
                    "utilization": 20,
                    "mem_used_mb": 20,
                    "mem_total_mb": 100,
                    "temperature": 60,
                    "power_draw": 100,
                }],
                net_rx_bytes=100,
                net_tx_bytes=50,
                disk_io=[{"read_bps": 10, "write_bps": 20}],
            ),
            ServerMetric(
                server_id=first.id,
                collected_at=minute + timedelta(seconds=20),
                status="ok",
                cpu_percent=30,
                mem_used_mb=70,
                mem_total_mb=100,
                gpus=[{
                    "utilization": 40,
                    "mem_used_mb": 40,
                    "mem_total_mb": 100,
                    "temperature": 70,
                    "power_draw": 120,
                }],
                net_rx_bytes=200,
                net_tx_bytes=100,
                disk_io=[{"read_bps": 30, "write_bps": 40}],
            ),
            ServerMetric(
                server_id=second.id,
                collected_at=minute + timedelta(seconds=30),
                status="ok",
                cpu_percent=50,
                mem_used_mb=90,
                mem_total_mb=100,
                gpus=[{
                    "utilization": 60,
                    "mem_used_mb": 60,
                    "mem_total_mb": 100,
                    "temperature": 80,
                    "power_draw": 200,
                }],
                net_rx_bytes=300,
                net_tx_bytes=150,
                disk_io=[{"read_bps": 50, "write_bps": 60}],
            ),
        ])
        db.commit()

        history = _cluster_history(db, 1)

        assert len(history) == 1
        assert history[0] == {
            "time": minute.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
            "cpu_percent": 30.0,
            "mem_percent": 70.0,
            "gpu_util": 40.0,
            "gpu_mem_percent": 40.0,
            "gpu_temp": 80.0,
            "gpu_power": 310.0,
            "net_bps": 600.0,
            "net_bps_tx": 300.0,
            "disk_bps": 90.0,
            "disk_bps_write": 120.0,
        }
    finally:
        db.close()
        engine.dispose()
