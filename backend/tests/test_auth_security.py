from __future__ import annotations

import secrets
import time

import pytest
from fastapi.testclient import TestClient

from backend.app.database import SessionLocal
from backend.app.main import app
from backend.app.models import Server, User
from backend.app.security import (
    _totp_at,
    hash_password,
    increment_token_version,
    new_totp_secret,
    verify_totp,
)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, username: str, password: str):
    return client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
    )


def add_user(username: str, password: str, role: str = "viewer") -> User:
    db = SessionLocal()
    try:
        user = User(
            username=username,
            password_hash=hash_password(password),
            display_name=username,
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user
    finally:
        db.close()


def test_login_cookie_csrf_and_persistent_logout(client: TestClient):
    response = login(client, "security_admin", "security-admin-password-000000000000")
    assert response.status_code == 200
    old_token = response.json()["access_token"]
    cookies = response.headers.get_list("set-cookie")
    assert any("gpumon_access=" in value and "HttpOnly" in value for value in cookies)
    assert any("gpumon_csrf=" in value and "SameSite=strict" in value for value in cookies)

    csrf = client.cookies.get("gpumon_csrf")
    assert csrf

    # A password-only administrator session can enroll MFA, but cannot use
    # administrator endpoints before enrollment is complete.
    denied_before_enrollment = client.put(
        "/api/settings",
        json={"poll_interval": 60},
        headers={"X-CSRF-Token": csrf},
    )
    assert denied_before_enrollment.status_code == 403
    assert "MFA enrollment" in denied_before_enrollment.json()["detail"]

    setup = client.post("/api/auth/mfa/setup", headers={"X-CSRF-Token": csrf})
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    code = _totp_at(secret, int(time.time()) // 30)
    confirmed = client.post(
        "/api/auth/mfa/confirm",
        json={"code": code},
        headers={"X-CSRF-Token": csrf},
    )
    assert confirmed.status_code == 200
    confirmed_token = confirmed.json()["access_token"]
    assert confirmed.json()["user"]["mfa_enrolled"] is True

    denied_without_csrf = client.put("/api/settings", json={"poll_interval": 60})
    assert denied_without_csrf.status_code == 403
    csrf = client.cookies.get("gpumon_csrf")
    allowed = client.put(
        "/api/settings",
        json={"poll_interval": 60},
        headers={"X-CSRF-Token": csrf},
    )
    assert allowed.status_code == 200

    logged_out = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    assert logged_out.status_code == 200
    assert client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {old_token}"}
    ).status_code == 401
    assert client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {confirmed_token}"}
    ).status_code == 401


def test_totp_codes_cannot_be_replayed(monkeypatch):
    fixed_time = 2_000_000_000
    monkeypatch.setattr("backend.app.security.time.time", lambda: fixed_time)
    secret = new_totp_secret()
    counter = fixed_time // 30
    code = _totp_at(secret, counter)

    accepted_counter = verify_totp(secret, code)
    assert accepted_counter == counter
    assert verify_totp(secret, code, last_counter=accepted_counter) is None


def test_password_change_issues_valid_new_token_and_revokes_old(client: TestClient):
    username = "password_test_" + secrets.token_hex(4)
    old_password = "old-password-000000"
    new_password = "new-password-000000"
    add_user(username, old_password)
    auth = login(client, username, old_password)
    assert auth.status_code == 200
    old_token = auth.json()["access_token"]
    csrf = client.cookies.get("gpumon_csrf")
    changed = client.post(
        "/api/users/change-password",
        json={"old_password": old_password, "new_password": new_password},
        headers={"X-CSRF-Token": csrf},
    )
    assert changed.status_code == 200
    new_token = changed.json()["access_token"]
    assert client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {new_token}"}
    ).status_code == 200
    assert client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {old_token}"}
    ).status_code == 401


def test_cookie_csrf_cannot_be_bypassed_with_another_auth_scheme(client: TestClient):
    username = "csrf_test_" + secrets.token_hex(4)
    password = "csrf-password-000000"
    add_user(username, password)
    auth = login(client, username, password)
    assert auth.status_code == 200

    # A non-Bearer header must neither exempt the request from CSRF nor make
    # authentication fall back to the valid cookie.
    blocked = client.post(
        "/api/auth/logout",
        headers={"Authorization": "Basic Zm9vOmJhcg=="},
    )
    assert blocked.status_code == 403
    csrf = client.cookies.get("gpumon_csrf")
    rejected = client.post(
        "/api/auth/logout",
        headers={
            "Authorization": "Basic Zm9vOmJhcg==",
            "X-CSRF-Token": csrf,
        },
    )
    assert rejected.status_code == 401

    # A syntactically valid Bearer request is CSRF-exempt, but an invalid
    # credential still fails normal authentication.
    rejected_bearer = client.post(
        "/api/auth/logout",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert rejected_bearer.status_code == 401


def test_login_rejects_cross_site_browser_origin(client: TestClient):
    username = "origin_test_" + secrets.token_hex(4)
    password = "origin-password-000000"
    add_user(username, password)
    cross_site = client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
        headers={"Origin": "http://attacker.invalid", "Sec-Fetch-Site": "cross-site"},
    )
    assert cross_site.status_code == 403

    same_origin = client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
        headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
    )
    assert same_origin.status_code == 200


def test_concurrent_session_revocations_increment_without_lost_update():
    created = add_user(
        "revoke_test_" + secrets.token_hex(4),
        "revoke-password-000000",
    )
    first = SessionLocal()
    second = SessionLocal()
    check = SessionLocal()
    try:
        first_user = first.get(User, created.id)
        second_user = second.get(User, created.id)
        initial_version = first_user.token_version
        assert second_user.token_version == initial_version

        increment_token_version(first, first_user)
        first.commit()
        increment_token_version(second, second_user)
        second.commit()

        assert check.get(User, created.id).token_version == initial_version + 2
    finally:
        first.close()
        second.close()
        check.close()


def test_deleted_recreated_identity_cannot_adopt_old_token(client: TestClient):
    username = "identity_test_" + secrets.token_hex(4)
    password = "identity-password-000000"
    first = add_user(username, password)
    auth = login(client, username, password)
    old_token = auth.json()["access_token"]
    old_auth_id = first.auth_id

    db = SessionLocal()
    try:
        current = db.get(User, first.id)
        db.delete(current)
        db.commit()
    finally:
        db.close()
    replacement = add_user(username, password, role="admin")
    assert replacement.auth_id != old_auth_id
    assert client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {old_token}"}
    ).status_code == 401


def test_request_body_limit_is_enforced_before_form_parsing(client: TestClient):
    response = client.post(
        "/api/auth/login",
        content=b"x" * (1024 * 1024 + 1),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 413

    def chunks():
        for _ in range(17):
            yield b"x" * (64 * 1024)

    chunked = client.post(
        "/api/auth/login",
        content=chunks(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert chunked.status_code == 413


def test_unenrolled_admin_only_receives_viewer_server_fields(client: TestClient):
    username = "unenrolled_admin_" + secrets.token_hex(4)
    password = "unenrolled-admin-password-000000"
    add_user(username, password, role="admin")
    db = SessionLocal()
    try:
        server = Server(
            name="unenrolled-admin-server-" + secrets.token_hex(3),
            host="10.98.0.10",
            port=2222,
            username="gpumon",
            bmc_host="10.98.0.11",
            bmc_user="bmc-reader",
            enabled=False,
        )
        db.add(server)
        db.commit()
        server_id = server.id
    finally:
        db.close()

    auth = login(client, username, password)
    assert auth.status_code == 200
    token = auth.json()["access_token"]
    rows = client.get(
        "/api/servers", headers={"Authorization": f"Bearer {token}"}
    ).json()
    row = next(item for item in rows if item["id"] == server_id)
    assert row["host"] == ""
    assert row["port"] == 0
    assert row["bmc_host"] == ""


def test_viewer_cannot_read_management_or_full_ipmi_fields(client: TestClient):
    username = "viewer_test_" + secrets.token_hex(4)
    password = "viewer-password-000000"
    add_user(username, password)
    db = SessionLocal()
    try:
        server = Server(
            name="security-test-server-" + secrets.token_hex(3),
            host="10.99.0.10",
            port=2222,
            username="gpumon",
            bmc_host="10.99.0.11",
            bmc_user="bmc-reader",
            enabled=False,
        )
        db.add(server)
        db.commit()
        server_id = server.id
    finally:
        db.close()
    auth = login(client, username, password)
    token = auth.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    rows = client.get("/api/servers", headers=headers).json()
    row = next(item for item in rows if item["id"] == server_id)
    assert row["host"] == ""
    assert row["port"] == 0
    assert row["bmc_host"] == ""
    assert row["bmc_user"] == ""
    assert client.get(f"/api/servers/{server_id}/ipmi/latest", headers=headers).status_code == 403
    assert client.post(
        f"/api/metrics/server/{server_id}/processes", headers=headers
    ).status_code == 403
    assert client.get(
        f"/api/metrics/server/{server_id}/history", headers=headers
    ).status_code == 200
