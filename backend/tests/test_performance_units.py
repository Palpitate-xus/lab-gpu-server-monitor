from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from backend.app.api.metrics import _latest_payload, server_latest
from backend.app.database import Base
from backend.app.models import Server, ServerMetric, ServerProcessSnapshot


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
