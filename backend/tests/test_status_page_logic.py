from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api.status_page import _build_public_payload, router
from backend.app.database import Base, get_db
from backend.app.main import SecurityHeadersMiddleware
from backend.app.models import Server, ServerMetric, Setting, User
from backend.app.security import create_access_token


@pytest.fixture
def isolated_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    try:
        yield db, factory
    finally:
        db.close()
        engine.dispose()


def test_status_freshness_and_explicit_utc(isolated_db):
    db, _ = isolated_db
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    servers = [Server(name=name, host="127.0.0.1") for name in ["fresh", "stale", "unknown", "future"]]
    db.add_all(servers)
    db.flush()
    for server, when in [(servers[0], now - timedelta(seconds=30)),
                         (servers[1], now - timedelta(hours=1)),
                         (servers[3], now + timedelta(hours=1))]:
        db.add(ServerMetric(server_id=server.id, status="ok", collected_at=when,
                            gpus=[{"index": 0, "utilization": 15, "mem_used_mb": 20, "mem_total_mb": 100}]))
    db.commit()
    payload = _build_public_payload(db, {"show_history_days": 1})
    states = {row["name"]: row for row in payload["servers"]}
    assert states["fresh"]["state"] == "online"
    assert states["fresh"]["online"] is True
    assert states["fresh"]["gpus"]
    assert states["fresh"]["last_check"].endswith("Z")
    for name, state in [("stale", "stale"), ("unknown", "unknown"), ("future", "stale")]:
        assert states[name]["state"] == state
        assert states[name]["online"] is False
        assert states[name]["gpus"] == []
    assert payload["overall"]["all_operational"] is False
    assert payload["overall"]["servers_online"] == 1
    assert payload["generated_at"].endswith("Z")
    assert payload["freshness_limit_seconds"] == 180


def test_status_freshness_respects_collection_interval_and_empty_is_unknown(isolated_db):
    db, _ = isolated_db
    server = Server(name="slow-cadence", host="127.0.0.1")
    db.add_all([server, Setting(key="poll_interval", value="600")])
    db.flush()
    db.add(ServerMetric(server_id=server.id, status="ok",
                        collected_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1000)))
    db.commit()
    payload = _build_public_payload(db, {"show_history_days": 1})
    assert payload["freshness_limit_seconds"] == 1800
    assert payload["servers"][0]["state"] == "online"
    empty = _build_public_payload(db, {"show_history_days": 1, "server_ids": [-1]})
    assert empty["overall"]["all_operational"] is False


def test_status_preview_draft_requires_admin_csrf_and_does_not_persist(isolated_db):
    db, factory = isolated_db
    admin = User(username="draft-admin", password_hash="not-used", role="admin",
                 mfa_secret="test-enrollment-marker", mfa_confirmed=True)
    viewer = User(username="draft-viewer", password_hash="not-used", role="viewer")
    published = json.dumps({"published": False, "title": "Saved title"})
    db.add_all([admin, viewer, Setting(key="status_page", value=published)])
    db.commit()
    admin_token = create_access_token(admin, mfa_verified=True)
    viewer_token = create_access_token(viewer)

    app = FastAPI()
    app.include_router(router)
    app.add_middleware(SecurityHeadersMiddleware)

    def request_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = request_db
    draft = {"title": "Unsaved draft", "published": True, "show_history_days": 1}
    with TestClient(app) as client:
        assert client.post("/api/status-page/preview", json=draft).status_code == 401
        client.cookies.set("gpumon_access", viewer_token)
        client.cookies.set("gpumon_csrf", "draft-csrf")
        headers = {"X-CSRF-Token": "draft-csrf"}
        assert client.post("/api/status-page/preview", json=draft, headers=headers).status_code == 403
        client.cookies.set("gpumon_access", admin_token)
        assert client.post("/api/status-page/preview", json=draft).status_code == 403
        response = client.post("/api/status-page/preview", json=draft, headers=headers)
        assert response.status_code == 200
        assert response.json()["title"] == "Unsaved draft"
        assert response.json()["published"] is True
        assert client.get("/api/status-public").json() == {"published": False}
    db.expire_all()
    assert db.get(Setting, "status_page").value == published
