from datetime import datetime, timedelta, timezone
from threading import Event, Lock
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import scheduler
from backend.app.database import Base
from backend.app.models import Server, ServerMetric, ServerMetricHourly, Setting


@pytest.fixture
def legacy_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(scheduler, "SessionLocal", factory)
    monkeypatch.setattr(scheduler, "_stop_event", Event())
    monkeypatch.setattr(scheduler, "_legacy_backfill_lock", Lock())
    monkeypatch.setattr(scheduler, "_legacy_backfill_thread", None)
    with factory() as db:
        server = Server(name="legacy-test", host="192.0.2.1", enabled=True)
        db.add_all([server, Setting(key="poll_interval", value="30")])
        db.commit()
        sid = server.id
    cutoff = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    yield factory, sid, cutoff
    scheduler._stop_event.set()
    worker = scheduler._legacy_backfill_thread
    if worker is not None:
        worker.join(timeout=5)
        assert not worker.is_alive()
    engine.dispose()


def add_legacy(db, sid, hour, **kwargs):
    # Migration 016 sets old rows true; fresh ORM rows default to false.
    kwargs.setdefault("gpu_time_estimated", True)
    db.add(ServerMetricHourly(server_id=sid, hour=hour, samples=1, **kwargs))


def test_hourly_refresh_returns_while_single_backfill_is_blocked(legacy_db, monkeypatch):
    factory, sid, cutoff = legacy_db
    with factory() as db:
        add_legacy(db, sid, cutoff)
        add_legacy(db, sid, cutoff - timedelta(hours=1))
        db.commit()
    entered, release = Event(), Event()
    jobs = []
    foreground = Mock()

    def blocked_backfill(*args):
        jobs.append(args)
        entered.set()
        assert release.wait(timeout=5)

    monkeypatch.setattr(scheduler, "_roll_hour", foreground)
    monkeypatch.setattr(scheduler, "_upgrade_legacy_gpu_card_time", blocked_backfill)
    try:
        scheduler._hourly_aggregate()
        assert entered.wait(timeout=2)
        worker = scheduler._legacy_backfill_thread
        assert worker is not None and worker.is_alive()
        assert foreground.call_count == 1
        assert jobs == [((sid,), 30, cutoff)]
        # Another refresh keeps running and cannot create an overlapping job.
        scheduler._hourly_aggregate()
        assert foreground.call_count == 2
        assert scheduler._legacy_backfill_thread is worker
        assert len(jobs) == 1
    finally:
        release.set()


def test_worker_rebuilds_retained_hours_but_not_foreground_or_unknown_hours(legacy_db):
    factory, sid, cutoff = legacy_db
    oldest = cutoff - timedelta(hours=4)
    with factory() as db:
        # The oldest partial hour must retain its existing legacy aggregate.
        for hour in range(5):
            when = oldest + timedelta(hours=hour)
            add_legacy(db, sid, when, gpu_time_estimated=hour != 2)
            db.add(ServerMetric(server_id=sid, collected_at=when + timedelta(seconds=30),
                                status="ok", sample_interval_seconds=30,
                                gpus=[{"mem_total_mb": 100, "mem_used_mb": 40, "utilization": 0}]))
        disabled = Server(name="disabled", host="192.0.2.2", enabled=False)
        db.add(disabled)
        db.flush()
        disabled_id = disabled.id
        add_legacy(db, disabled_id, cutoff - timedelta(hours=1))
        db.commit()
    scheduler._upgrade_legacy_gpu_card_time([sid], 30, cutoff)
    with factory() as db:
        rows = db.query(ServerMetricHourly).filter_by(server_id=sid).order_by(ServerMetricHourly.hour).all()
        assert [row.gpu_sample_minutes for row in rows] == [None, 0.5, None, 0.5, None]
        assert rows[1].idle_held_gpu_minutes == 0.5
        assert rows[1].gpu_time_estimated is False
        assert db.query(ServerMetricHourly).filter_by(server_id=disabled_id).one().gpu_sample_minutes is None


def test_worker_keeps_the_96_hour_batch_limit(legacy_db, monkeypatch):
    factory, sid, cutoff = legacy_db
    with factory() as db:
        first = cutoff - timedelta(hours=101)
        db.add(ServerMetric(server_id=sid, collected_at=first, status="ok"))
        for index in range(1, 102):
            add_legacy(db, sid, cutoff - timedelta(hours=index))
        db.commit()
    roll = Mock()
    monkeypatch.setattr(scheduler, "_roll_hour", roll)
    scheduler._upgrade_legacy_gpu_card_time([sid], 30, cutoff)
    assert roll.call_count == 96
    assert roll.call_args_list[0].args[1] == cutoff.replace(tzinfo=None) - timedelta(hours=1)
    assert roll.call_args_list[-1].args[1] == cutoff.replace(tzinfo=None) - timedelta(hours=96)


def test_worker_cancels_between_hours_and_closes_its_session(legacy_db, monkeypatch):
    factory, sid, cutoff = legacy_db
    with factory() as db:
        db.add(ServerMetric(server_id=sid, collected_at=cutoff - timedelta(hours=3), status="ok"))
        for index in (1, 2):
            add_legacy(db, sid, cutoff - timedelta(hours=index))
        db.commit()
    owned = factory()
    close = Mock(wraps=owned.close)
    monkeypatch.setattr(owned, "close", close)
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: owned)
    roll = Mock(side_effect=lambda *args: scheduler._stop_event.set())
    monkeypatch.setattr(scheduler, "_roll_hour", roll)
    scheduler._upgrade_legacy_gpu_card_time([sid], 30, cutoff)
    assert roll.call_count == 1
    close.assert_called_once()


def test_worker_failure_rolls_back_and_closes_its_own_session(legacy_db, monkeypatch):
    factory, sid, cutoff = legacy_db
    with factory() as db:
        db.add(ServerMetric(server_id=sid, collected_at=cutoff - timedelta(hours=2), status="ok"))
        add_legacy(db, sid, cutoff - timedelta(hours=1))
        db.commit()
    owned = factory()
    rollback, close = Mock(wraps=owned.rollback), Mock(wraps=owned.close)
    monkeypatch.setattr(owned, "rollback", rollback)
    monkeypatch.setattr(owned, "close", close)
    monkeypatch.setattr(scheduler, "SessionLocal", lambda: owned)
    monkeypatch.setattr(scheduler, "_roll_hour", Mock(side_effect=RuntimeError("test-only failure")))
    scheduler._upgrade_legacy_gpu_card_time([sid], 30, cutoff)
    rollback.assert_called_once()
    close.assert_called_once()


def test_backfill_is_not_started_after_shutdown(legacy_db, monkeypatch):
    _, sid, cutoff = legacy_db
    thread = Mock()
    monkeypatch.setattr(scheduler.threading, "Thread", thread)
    scheduler._stop_event.set()
    scheduler._start_legacy_backfill([sid], 30, cutoff)
    thread.assert_not_called()


def test_hourly_refresh_does_not_start_a_worker_without_legacy_hours(legacy_db, monkeypatch):
    factory, sid, cutoff = legacy_db
    with factory() as db:
        add_legacy(db, sid, cutoff, gpu_sample_minutes=0, gpu_time_estimated=False)
        db.commit()
    start = Mock()
    monkeypatch.setattr(scheduler, "_start_legacy_backfill", start)
    scheduler._hourly_aggregate()
    start.assert_not_called()


def test_first_scheduler_sample_uses_saved_interval(legacy_db, monkeypatch):
    monkeypatch.setitem(scheduler._state, "running", False)
    monkeypatch.setitem(scheduler._state, "interval", 60)
    monkeypatch.setitem(scheduler._state, "thread", None)
    thread = Mock()

    def assert_saved_interval():
        assert scheduler._state["interval"] == 30

    thread.start.side_effect = assert_saved_interval
    constructor = Mock(return_value=thread)
    monkeypatch.setattr(scheduler.threading, "Thread", constructor)
    monkeypatch.setattr(scheduler, "start_cache_warmer", Mock())
    monkeypatch.setattr(scheduler, "_start_ipmi_loop", Mock())
    scheduler.start_scheduler()
    thread.start.assert_called_once()
    # Repeated startup must not launch another scheduler.
    scheduler.start_scheduler()
    constructor.assert_called_once()
