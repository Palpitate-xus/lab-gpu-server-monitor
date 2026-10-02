from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.app import scheduler
from backend.app.api import metrics


def configured_server(auth_type):
    # Legacy databases can contain both write-only credentials. Selection must
    # honor the configured authentication type on every SSH execution path.
    return SimpleNamespace(id=1, name="legacy", host="192.0.2.1", port=22,
                           username="gpumon", auth_type=auth_type,
                           password="stored-password", private_key="stored-key",
                           passphrase="stored-passphrase")


def assert_active_credentials(kwargs, auth_type):
    assert kwargs["password_enc"] == ("stored-password" if auth_type == "password" else "")
    assert kwargs["private_key_enc"] == ("stored-key" if auth_type == "key" else "")
    assert kwargs["passphrase_enc"] == ("stored-passphrase" if auth_type == "key" else "")


@pytest.mark.parametrize("auth_type", ["password", "key"])
@pytest.mark.parametrize("worker,collector", [
    ("_poll_one", "collect"), ("_slow_one", "collect_slow"), ("_inventory_one", "collect_inventory"),
])
def test_all_scheduled_collectors_only_receive_active_credentials(monkeypatch, auth_type, worker, collector):
    calls = []
    def collect(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("isolated test stops before any network or database write")
    monkeypatch.setattr(scheduler, "_server_begin", lambda *_args: True)
    monkeypatch.setattr(scheduler, "_server_end", lambda *_args: None)
    monkeypatch.setattr(scheduler, collector, collect)
    getattr(scheduler, worker)(configured_server(auth_type))
    assert len(calls) == 1
    assert_active_credentials(calls[0], auth_type)


@pytest.mark.parametrize("auth_type", ["password", "key"])
def test_live_process_reads_only_receive_active_credentials(monkeypatch, auth_type):
    calls = []
    server = configured_server(auth_type)
    metrics._procs_cache.clear()
    monkeypatch.setattr(metrics, "live_processes", lambda **kwargs: (calls.append(kwargs) or (False, "mock stopped")))
    with pytest.raises(HTTPException) as error:
        metrics.server_processes(server.id, "cpu", object(), SimpleNamespace(get=lambda *_args: server))
    assert error.value.status_code == 502
    assert_active_credentials(calls[0], auth_type)


@pytest.mark.parametrize("auth_type", ["password", "key"])
def test_process_actions_only_receive_active_credentials(monkeypatch, auth_type):
    from backend.app import config, security
    from backend.app.schemas import ProcessAction
    calls = []
    server = configured_server(auth_type)
    db = SimpleNamespace(get=lambda *_args: server, add=lambda *_args: None,
                         commit=lambda: None, rollback=lambda: None)
    admin = SimpleNamespace(id=1, username="admin", password_hash="unused")
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(remote_process_control_enabled=True))
    monkeypatch.setattr(metrics, "check_step_up_limit", lambda *_args: ("test", "test"))
    monkeypatch.setattr(metrics, "record_step_up_success", lambda *_args: None)
    monkeypatch.setattr(security, "verify_password", lambda *_args: True)
    monkeypatch.setattr(metrics, "remote_command", lambda **kwargs: (calls.append(kwargs) or (True, "mock only")))
    metrics.process_action(server.id, ProcessAction(action="renice", pid=123, start_ticks=12345,
                                                   nice=10, reauth_password="test-only"), object(), db, admin)
    assert_active_credentials(calls[0], auth_type)
