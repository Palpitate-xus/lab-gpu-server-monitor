from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from backend.app.api.enterprise import cluster_utilization_report
from backend.app.database import Base
from backend.app.migrate import _statements
from backend.app.models import Server, ServerMetric, ServerMetricHourly
from backend.app.scheduler import _roll_hour


@pytest.fixture
def report_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        server = Server(name="card-time", host="192.0.2.1")
        db.add(server)
        db.commit()
        yield db, server
    engine.dispose()


def current_hour():
    return datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)


def idle_gpus(count):
    return [{"index": index, "utilization": 0, "mem_total_mb": 100, "mem_used_mb": 40}
            for index in range(count)]


@pytest.mark.parametrize("gpu_count", [1, 8])
@pytest.mark.parametrize("period", [30, 60, 120])
def test_report_card_time_and_ratios_match_gpu_count_and_sampling_period(report_db, gpu_count, period):
    db, server = report_db
    start = current_hour()
    for seconds in range(0, 3600, period):
        db.add(ServerMetric(server_id=server.id, collected_at=start + timedelta(seconds=seconds),
                            status="ok", sample_interval_seconds=period, gpus=idle_gpus(gpu_count)))
    db.commit()
    # The current setting is intentionally different from the recorded one.
    _roll_hour(db, start, start + timedelta(hours=1), [server.id], 10)
    payload = cluster_utilization_report(hours=24, tag="", db=db, user=object())
    assert payload["total_gpu_hours"] == gpu_count
    assert payload["total_idle_gpu_hours"] == gpu_count
    assert payload["idle_ratio_pct"] == 100
    assert payload["servers"][0]["idle_ratio_pct"] == 100
    assert payload["card_time_complete"] is True
    assert payload["card_time_estimated"] is False


def test_duplicate_and_manual_samples_do_not_double_count_time(report_db):
    db, server = report_db
    start = current_hour()
    for seconds in [0, 0, 30]:
        db.add(ServerMetric(server_id=server.id, collected_at=start + timedelta(seconds=seconds),
                            status="ok", sample_interval_seconds=60, gpus=idle_gpus(8)))
    db.commit()
    _roll_hour(db, start, start + timedelta(hours=1), [server.id], 60)
    row = db.query(ServerMetricHourly).one()
    assert row.gpu_sample_minutes == 12  # 8 cards * 90 seconds / 60
    assert row.idle_held_gpu_minutes == 12


def test_legacy_raw_period_is_disclosed_as_estimated(report_db):
    db, server = report_db
    start = current_hour()
    db.add(ServerMetric(server_id=server.id, collected_at=start, status="ok", gpus=idle_gpus(8)))
    db.commit()
    _roll_hour(db, start, start + timedelta(hours=1), [server.id], 30)
    payload = cluster_utilization_report(hours=24, tag="", db=db, user=object())
    assert payload["card_time_complete"] is True
    assert payload["card_time_estimated"] is True
    assert payload["idle_ratio_pct"] == 100


def test_unrecoverable_legacy_hour_keeps_data_and_does_not_invent_card_time(report_db):
    db, server = report_db
    start = current_hour()
    db.add(ServerMetricHourly(server_id=server.id, hour=start, samples=60, ok_samples=60,
                              idle_held_minutes=480, gpu_time_estimated=True))
    db.commit()
    _roll_hour(db, start, start + timedelta(hours=1), [server.id], 60)
    payload = cluster_utilization_report(hours=24, tag="", db=db, user=object())
    assert payload["total_idle_gpu_hours"] == 8
    assert payload["total_gpu_hours"] is None
    assert payload["idle_ratio_pct"] is None
    assert payload["servers"][0]["idle_ratio_pct"] is None
    assert payload["card_time_complete"] is False
    assert db.query(ServerMetricHourly).one().samples == 60


def test_additive_card_time_migration_preserves_legacy_rows():
    from pathlib import Path
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE server_metrics (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE server_metrics_hourly (id INTEGER PRIMARY KEY, idle_held_minutes INTEGER)"))
        conn.execute(text("INSERT INTO server_metrics_hourly VALUES (1, 480)"))
        migration = Path(__file__).resolve().parents[1] / "migrations" / "016_gpu_card_time.sql"
        for statement in _statements(migration.read_text()):
            conn.execute(text(statement))
        row = conn.execute(text("SELECT idle_held_minutes, gpu_sample_minutes, gpu_time_estimated FROM server_metrics_hourly")).one()
        assert tuple(row) == (480, None, 1)
        assert "sample_interval_seconds" in {column["name"] for column in inspect(conn).get_columns("server_metrics")}
    engine.dispose()
