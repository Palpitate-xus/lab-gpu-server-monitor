from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event, inspect, text
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


@pytest.mark.parametrize("gpu_count", [1, 8])
@pytest.mark.parametrize("period,offset", [(30, 15), (60, 30), (120, 60)])
def test_card_time_carries_in_samples_before_a_non_aligned_hour(report_db, gpu_count, period, offset):
    db, server = report_db
    start = current_hour()
    previous_gpus = idle_gpus(gpu_count)
    for gpu in previous_gpus:
        gpu["utilization"] = 4
    db.add(ServerMetric(server_id=server.id, collected_at=start + timedelta(seconds=offset - period),
                        status="ok", sample_interval_seconds=period,
                        cpu_percent=999, gpus=previous_gpus))
    for seconds in range(offset, 3600, period):
        db.add(ServerMetric(server_id=server.id, collected_at=start + timedelta(seconds=seconds),
                            status="ok", sample_interval_seconds=period,
                            cpu_percent=10, gpus=idle_gpus(gpu_count)))
    db.commit()
    _roll_hour(db, start, start + timedelta(hours=1), [server.id], 10)
    row = db.query(ServerMetricHourly).one()
    assert row.gpu_sample_minutes == pytest.approx(gpu_count * 60)
    assert row.idle_held_gpu_minutes == pytest.approx(gpu_count * 60)
    assert (row.samples, row.ok_samples) == (3600 // period, 3600 // period)
    assert row.cpu_avg == 10
    assert row.gpu_util_avg == 0, "carry-in must not change the existing hourly averages"
    payload = cluster_utilization_report(hours=24, tag="", db=db, user=object())
    assert payload["total_gpu_hours"] == gpu_count
    assert payload["total_idle_gpu_hours"] == gpu_count
    assert payload["idle_ratio_pct"] == 100


def test_cross_hour_manual_duplicates_use_the_last_sample_and_never_overlap(report_db):
    db, server = report_db
    start = current_hour()
    for seconds, gpu_count in [(-30, 1), (-30, 8), (15, 1), (15, 8), (60, 8)]:
        db.add(ServerMetric(server_id=server.id, collected_at=start + timedelta(seconds=seconds),
                            status="ok", sample_interval_seconds=60, gpus=idle_gpus(gpu_count)))
    db.commit()
    _roll_hour(db, start - timedelta(hours=1), start, [server.id], 60)
    _roll_hour(db, start, start + timedelta(hours=1), [server.id], 60)
    rows = db.query(ServerMetricHourly).order_by(ServerMetricHourly.hour).all()
    assert rows[0].gpu_sample_minutes == 4  # Last prior sample covers [-30, 0).
    assert rows[1].gpu_sample_minutes == 16  # Carry 15s + 45s + 60s, on eight cards.
    assert sum(row.gpu_sample_minutes for row in rows) == 20
    assert (rows[0].samples, rows[1].samples) == (2, 3)


@pytest.mark.parametrize("previous_status,previous_seconds", [("error", -30), ("ok", -90)])
def test_error_or_expired_preceding_sample_cannot_bridge_an_hour_boundary(report_db, previous_status, previous_seconds):
    db, server = report_db
    start = current_hour()
    # A later error must override, rather than skip back to, a successful sample.
    db.add(ServerMetric(server_id=server.id, collected_at=start + timedelta(seconds=previous_seconds - 10),
                        status="ok", sample_interval_seconds=60, gpus=idle_gpus(8)))
    db.add(ServerMetric(server_id=server.id, collected_at=start + timedelta(seconds=previous_seconds),
                        status=previous_status, sample_interval_seconds=60, gpus=idle_gpus(8)))
    db.add(ServerMetric(server_id=server.id, collected_at=start + timedelta(seconds=30),
                        status="ok", sample_interval_seconds=60, gpus=idle_gpus(8)))
    db.commit()
    _roll_hour(db, start, start + timedelta(hours=1), [server.id], 60)
    row = db.query(ServerMetricHourly).one()
    assert row.gpu_sample_minutes == 8
    assert row.idle_held_gpu_minutes == 8
    assert (row.samples, row.ok_samples) == (1, 1)


def test_carry_in_stops_at_an_error_even_when_no_current_hour_sample_succeeds(report_db):
    db, server = report_db
    start = current_hour()
    db.add(ServerMetric(server_id=server.id, collected_at=start - timedelta(seconds=30),
                        status="ok", sample_interval_seconds=60, gpus=idle_gpus(8)))
    db.add(ServerMetric(server_id=server.id, collected_at=start + timedelta(seconds=10),
                        status="error", sample_interval_seconds=60))
    db.commit()
    _roll_hour(db, start, start + timedelta(hours=1), [server.id], 60)
    row = db.query(ServerMetricHourly).one()
    assert row.gpu_sample_minutes == pytest.approx(8 * 10 / 60)
    assert row.idle_held_gpu_minutes == pytest.approx(8 * 10 / 60)
    assert (row.samples, row.ok_samples, row.cpu_avg) == (1, 0, 0)


def test_legacy_carry_in_period_is_disclosed_as_estimated(report_db):
    db, server = report_db
    start = current_hour()
    db.add(ServerMetric(server_id=server.id, collected_at=start - timedelta(seconds=10),
                        status="ok", gpus=idle_gpus(8)))
    db.add(ServerMetric(server_id=server.id, collected_at=start + timedelta(seconds=40),
                        status="ok", sample_interval_seconds=30, gpus=idle_gpus(8)))
    db.commit()
    _roll_hour(db, start, start + timedelta(hours=1), [server.id], 30)
    row = db.query(ServerMetricHourly).one()
    assert row.gpu_sample_minutes == pytest.approx(8 * 50 / 60)
    assert row.gpu_time_estimated is True


def test_carry_in_lookup_uses_fixed_batch_query_count(report_db):
    db, first = report_db
    start = current_hour()
    servers = [first] + [Server(name=f"batch-{index}", host=f"192.0.2.{index + 20}") for index in range(20)]
    db.add_all(servers)
    db.commit()
    server_ids = [server.id for server in servers]
    for server_id in server_ids:
        for seconds in [-30, 30]:
            db.add(ServerMetric(server_id=server_id, collected_at=start + timedelta(seconds=seconds),
                                status="ok", sample_interval_seconds=60, gpus=idle_gpus(1)))
    db.commit()
    selects = []

    def record(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().lower().startswith("select") and "from server_metrics " in statement.lower():
            selects.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        _roll_hour(db, start, start + timedelta(hours=1), server_ids, 60)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(selects) == 2, "one hourly-samples query plus one predecessor batch, regardless of server count"


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
