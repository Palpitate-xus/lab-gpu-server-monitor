from __future__ import annotations

import os

import paramiko
import pytest
from starlette.requests import Request

from backend.app import main as app_main
from backend.app import (
    cache as app_cache,
    ipmi_collector,
    notifier,
    rate_limit,
    scheduler,
    ssh_collector,
    ssh_transport,
)
from backend.app.archive_crypto import (
    archive_storage_ready,
    decrypt_file,
    encrypt_file,
    ensure_archive_storage,
)
from backend.app.database import SessionLocal
from backend.app.models import Setting, WebhookChannel
from backend.app.privacy import minimize_metric
from backend.app.security import enforce_login_origin, resolve_client_ip


class _FakeSshClient:
    def __init__(self):
        self.keys = paramiko.HostKeys()

    def get_host_keys(self):
        return self.keys


def test_tofu_persists_with_strict_modes_and_rejects_change(tmp_path, monkeypatch):
    monkeypatch.setattr(ssh_transport.settings, "DATA_DIR", str(tmp_path))
    key = paramiko.RSAKey.generate(1024)
    path = ssh_transport.hostkey_path("server_1")
    policy = ssh_transport._TofuPolicy(path, "gpu.example", 22)
    policy.missing_host_key(_FakeSshClient(), "gpu.example", key)

    assert os.stat(os.path.dirname(path)).st_mode & 0o777 == 0o700
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert os.stat(os.path.join(os.path.dirname(path), ".hostkey.lock")).st_mode & 0o777 == 0o600
    policy.missing_host_key(_FakeSshClient(), "gpu.example", key)
    with pytest.raises(paramiko.BadHostKeyException):
        policy.missing_host_key(
            _FakeSshClient(), "gpu.example", paramiko.RSAKey.generate(1024)
        )


def test_tofu_fails_closed_when_atomic_publish_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(ssh_transport.settings, "DATA_DIR", str(tmp_path))
    policy = ssh_transport._TofuPolicy(
        ssh_transport.hostkey_path("server_2"), "gpu.example", 22
    )
    monkeypatch.setattr(os, "link", lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError()))
    with pytest.raises(paramiko.SSHException, match="refusing SSH connection"):
        policy.missing_host_key(
            _FakeSshClient(), "gpu.example", paramiko.RSAKey.generate(1024)
        )


def test_hostkey_reset_pins_only_the_out_of_band_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr(ssh_transport.settings, "DATA_DIR", str(tmp_path))
    trusted = paramiko.RSAKey.generate(1024)
    changed = paramiko.RSAKey.generate(1024)
    monkeypatch.setattr(ssh_transport, "_fetch_remote_host_key", lambda *_args: trusted)

    actual = ssh_transport.replace_hostkey_with_expected_fingerprint(
        "gpu.example", 22, "server_7", trusted.fingerprint
    )
    path = ssh_transport.hostkey_path("server_7")
    before = open(path, "rb").read()
    assert actual == trusted.fingerprint

    monkeypatch.setattr(ssh_transport, "_fetch_remote_host_key", lambda *_args: changed)
    with pytest.raises(ssh_transport.HostKeyFingerprintMismatch):
        ssh_transport.replace_hostkey_with_expected_fingerprint(
            "gpu.example", 22, "server_7", trusted.fingerprint
        )
    assert open(path, "rb").read() == before


def test_collected_processes_drop_user_and_argv():
    sample = "PID PPID USER CPU MEM RSS VSZ STAT ELAPSED COMMAND\n1 0 alice 1 2 3 4 S 5 python train.py --token secret"
    stored = ssh_collector._parse_ps(sample)
    live = ssh_collector._parse_ps(sample, include_sensitive=True)
    assert stored[0]["command"] == "python"
    assert stored[0]["user"] == ""
    assert live[0]["command"] == "python train.py --token secret"
    assert live[0]["user"] == "alice"


def test_historical_metric_responses_drop_login_and_process_identity():
    minimized = minimize_metric(
        {
            "users": [{"user": "alice", "from": "198.51.100.7"}],
            "processes": [{"pid": 7, "user": "alice", "command": "python --token secret"}],
            "gpus": [
                {
                    "index": 0,
                    "processes": [
                        {"pid": 7, "user": "alice", "command": "python --token secret"}
                    ],
                }
            ],
        }
    )

    assert minimized["users"] == []
    assert minimized["processes"] == [{"pid": 7}]
    assert minimized["gpus"][0]["processes"] == [{"pid": 7}]


def test_archive_encryption_detects_tampering(tmp_path):
    source = tmp_path / "source.tar.gz"
    encrypted = tmp_path / "archive.enc"
    restored = tmp_path / "restored.tar.gz"
    source.write_bytes(os.urandom(4096))
    key = "ab" * 32
    encrypt_file(str(source), str(encrypted), key)
    decrypt_file(str(encrypted), str(restored), key)
    assert restored.read_bytes() == source.read_bytes()

    damaged = bytearray(encrypted.read_bytes())
    damaged[-1] ^= 1
    encrypted.write_bytes(damaged)
    second = tmp_path / "tampered-output"
    with pytest.raises(Exception):
        decrypt_file(str(encrypted), str(second), key)
    assert not second.exists()

    with pytest.raises(ValueError, match="exactly 64 hexadecimal"):
        encrypt_file(str(source), str(tmp_path / "bad-key"), "ab " * 21 + "a")


def test_archive_storage_is_private_and_actually_writable(tmp_path):
    archive_dir = tmp_path / "archives"
    ensure_archive_storage(str(archive_dir))
    assert os.stat(archive_dir).st_mode & 0o777 == 0o700
    assert archive_storage_ready(str(archive_dir)) is True

    not_a_directory = tmp_path / "file"
    not_a_directory.write_text("not a directory")
    assert archive_storage_ready(str(not_a_directory)) is False


def test_root_ssh_is_rejected_before_network_access(monkeypatch):
    monkeypatch.setattr(ssh_transport.settings, "ALLOW_ROOT_SSH", "no")
    with pytest.raises(ssh_transport.RootSshDisabledError):
        ssh_transport.connect_host("192.0.2.10", 22, "root", password="unused")


def test_legacy_ssh_algorithms_are_explicitly_disabled():
    disabled = ssh_transport.DISABLED_SSH_ALGORITHMS
    assert "ssh-rsa" in disabled["keys"]
    assert "ssh-rsa" in disabled["pubkeys"]
    assert "3des-cbc" in disabled["ciphers"]
    assert "aes256-cbc" in disabled["ciphers"]
    assert "hmac-sha1" in disabled["macs"]
    assert "hmac-md5" in disabled["macs"]


def test_ipmi_uses_modern_cipher_suite_and_minimal_environment(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

    monkeypatch.setattr(ipmi_collector.subprocess, "run", fake_run)
    result = ipmi_collector._run(
        "192.0.2.10", "operator", "secret", ["mc", "info"]
    )

    assert result == (0, "ok", "")
    command = captured["command"]
    assert command[command.index("-C") + 1] == "17"
    assert "secret" not in command
    assert captured["kwargs"]["env"] == {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "IPMITOOL_PASSWORD": "secret",
        "LC_ALL": "C",
    }


def test_webhook_resolution_rejects_private_and_returns_pinned_public_ip(monkeypatch):
    monkeypatch.setattr(
        notifier.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(notifier.socket.AF_INET, 1, 6, "", ("10.0.0.8", 443))],
    )
    assert notifier._validate_webhook_url("https://hooks.example/x")[0] is False
    monkeypatch.setattr(
        notifier.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(notifier.socket.AF_INET, 1, 6, "", ("93.184.216.34", 443))],
    )
    parsed, pinned, reason = notifier._resolve_webhook_target("https://hooks.example/x")
    assert parsed.hostname == "hooks.example"
    assert pinned == "93.184.216.34"
    assert reason == ""


@pytest.mark.parametrize("address", ["100.64.0.1", "fec0::1"])
def test_webhook_resolution_rejects_non_global_special_ranges(monkeypatch, address):
    family = notifier.socket.AF_INET6 if ":" in address else notifier.socket.AF_INET
    sockaddr = (address, 443, 0, 0) if family == notifier.socket.AF_INET6 else (address, 443)
    monkeypatch.setattr(
        notifier.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(family, 1, 6, "", sockaddr)],
    )
    ok, reason = notifier._validate_webhook_url("https://hooks.example/x")
    assert ok is False
    assert "non-public" in reason


def test_webhook_resolution_rejects_invalid_port_without_raising():
    ok, reason = notifier._validate_webhook_url("https://hooks.example:99999/x")
    assert ok is False
    assert reason == "invalid webhook port"


def test_webhook_urls_are_encrypted_at_rest_and_redacted_from_responses():
    plaintext = "https://hooks.example.invalid/services/private-token"
    db = SessionLocal()
    try:
        db.query(WebhookChannel).delete()
        legacy = db.get(Setting, notifier.SETTING_WEBHOOK_URL)
        if legacy is None:
            legacy = Setting(key=notifier.SETTING_WEBHOOK_URL, value=plaintext)
            db.add(legacy)
        else:
            legacy.value = plaintext
        db.add(
            WebhookChannel(
                name="security-test",
                url=plaintext,
                template="",
                min_severity="info",
                enabled=True,
            )
        )
        db.commit()
    finally:
        db.close()

    assert notifier.secure_stored_webhook_urls() == 2

    db = SessionLocal()
    try:
        stored_setting = db.get(Setting, notifier.SETTING_WEBHOOK_URL).value
        stored_channel = db.query(WebhookChannel).one().url
        assert stored_setting.startswith(notifier.WEBHOOK_ENCRYPTED_PREFIX)
        assert stored_channel.startswith(notifier.WEBHOOK_ENCRYPTED_PREFIX)
        assert plaintext not in stored_setting
        assert plaintext not in stored_channel
        assert notifier.reveal_webhook_url(stored_setting) == plaintext
        redacted = notifier.redact_webhook_url(stored_channel)
        assert redacted == "https://hooks.example.invalid/…"
        assert "private-token" not in redacted
    finally:
        db.query(WebhookChannel).delete()
        db.query(Setting).filter(Setting.key == notifier.SETTING_WEBHOOK_URL).delete()
        db.commit()
        db.close()


def test_login_limiter_has_bounded_storage(monkeypatch):
    monkeypatch.setattr(rate_limit, "MAX_BUCKETS", 8)
    limiter = rate_limit.LoginRateLimiter()
    for index in range(100):
        limiter.record_failure(f"192.0.2.{index}", f"user-{index}")
    assert limiter.status()["tracked_bucket_count"] <= 16


def test_process_local_cache_has_a_hard_entry_limit(monkeypatch):
    monkeypatch.setattr(app_cache, "MAX_MEMORY_CACHE_ENTRIES", 8)
    backend = app_cache.InMemoryBackend()
    for index in range(100):
        backend.set(f"parameter-variant-{index}", {"value": index}, ttl=60)
    assert len(backend._data) == 8
    assert backend.get("parameter-variant-99") == {"value": 99}


def test_runtime_rejects_legacy_only_signing_secret(monkeypatch):
    monkeypatch.setattr(app_main.settings, "JWT_SIGNING_KEY", "")
    monkeypatch.setattr(app_main.settings, "SECRET_KEY", "legacy-secret-" + "x" * 48)
    with pytest.raises(RuntimeError, match="legacy SECRET_KEY fallback is not accepted"):
        app_main._validate_runtime_security()


def test_https_runtime_requires_exact_trusted_proxy_identity(monkeypatch):
    monkeypatch.setattr(app_main.settings, "ALLOW_INSECURE_HTTP", "no")
    monkeypatch.setattr(app_main.settings, "COOKIE_SECURE", "yes")
    monkeypatch.setattr(app_main.settings, "TRUST_PROXY", "no")
    with pytest.raises(RuntimeError, match="HTTPS deployments require TRUST_PROXY=yes"):
        app_main._validate_runtime_security()


def test_runtime_requires_tls_for_remote_mysql(monkeypatch):
    monkeypatch.setattr(
        app_main.settings,
        "DATABASE_URL",
        "mysql+pymysql://gpumon:long-random-runtime-password@db.internal/gpu_monitor",
    )
    monkeypatch.setattr(app_main.settings, "DATABASE_SSL_CA", "")
    monkeypatch.setattr(app_main.settings, "DATABASE_SSL_CERT", "")
    monkeypatch.setattr(app_main.settings, "DATABASE_SSL_KEY", "")
    with pytest.raises(RuntimeError, match="non-loopback MySQL requires DATABASE_SSL_CA"):
        app_main._validate_runtime_security()


def test_runtime_requires_authenticated_tls_for_remote_redis(monkeypatch):
    monkeypatch.setattr(
        app_main.settings,
        "REDIS_URL",
        "redis://:a-long-cache-password@10.0.0.8:6379/0",
    )
    assert "non-loopback Redis requires rediss://" in app_main.redis_security_errors()

    monkeypatch.setattr(
        app_main.settings,
        "REDIS_URL",
        "rediss://:short@cache.internal:6379/0?ssl_cert_reqs=none",
    )
    errors = app_main.redis_security_errors()
    assert any("TLS query options" in error for error in errors)
    assert any("at least 16 characters" in error for error in errors)


def test_runtime_rejects_mysql_tls_downgrade_query(monkeypatch):
    monkeypatch.setattr(
        app_main.settings,
        "DATABASE_URL",
        "mysql+pymysql://gpumon:long-random-runtime-password@db.internal/gpu_monitor"
        "?ssl_disabled=true",
    )
    monkeypatch.setattr(app_main.settings, "DATABASE_SSL_CA", "/run/secrets/ca.pem")
    with pytest.raises(RuntimeError, match="must not contain TLS query options"):
        app_main._validate_runtime_security()


def test_scheduler_status_detects_stale_heartbeat(monkeypatch):
    class _AliveThread:
        @staticmethod
        def is_alive():
            return True

    now = scheduler.time.monotonic()
    monkeypatch.setitem(scheduler._state, "thread", _AliveThread())
    monkeypatch.setitem(scheduler._state, "running", True)
    monkeypatch.setitem(scheduler._state, "interval", 60)
    monkeypatch.setitem(scheduler._state, "heartbeat_monotonic", now)
    assert scheduler.scheduler_status()["healthy"] is True

    monkeypatch.setitem(scheduler._state, "heartbeat_monotonic", now - 301)
    assert scheduler.scheduler_status()["healthy"] is False


def test_client_ip_only_honors_forwarding_from_trusted_peer(monkeypatch):
    from backend.app import security

    monkeypatch.setattr(security.settings, "TRUST_PROXY", "yes")
    monkeypatch.setattr(
        security.settings,
        "TRUSTED_PROXY_CIDRS",
        "127.0.0.1/32,10.0.0.8/32",
    )
    headers = [(b"x-forwarded-for", b"198.51.100.10, 10.0.0.8")]
    trusted_request = Request(
        {"type": "http", "method": "GET", "path": "/", "headers": headers,
         "client": ("127.0.0.1", 1234), "scheme": "http", "server": ("test", 80)}
    )
    assert resolve_client_ip(trusted_request) == "198.51.100.10"

    untrusted_request = Request(
        {"type": "http", "method": "GET", "path": "/", "headers": headers,
         "client": ("203.0.113.8", 1234), "scheme": "http", "server": ("test", 80)}
    )
    assert resolve_client_ip(untrusted_request) == "203.0.113.8"


def test_runtime_rejects_broad_trusted_proxy_network(monkeypatch):
    monkeypatch.setattr(app_main.settings, "TRUST_PROXY", "yes")
    monkeypatch.setattr(app_main.settings, "TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    with pytest.raises(RuntimeError, match="exact /32 or /128"):
        app_main._validate_runtime_security()


def test_runtime_rejects_unsafe_credentialed_cors_origin(monkeypatch):
    monkeypatch.setattr(app_main.settings, "CORS_ORIGINS", "null,http://dev.example")
    monkeypatch.setattr(app_main.settings, "ALLOW_INSECURE_HTTP", "no")
    with pytest.raises(RuntimeError) as caught:
        app_main._validate_runtime_security()
    message = str(caught.value)
    assert "exact web origins" in message
    assert "plain-HTTP CORS origins" in message


def test_runtime_rejects_ambiguous_security_boolean(monkeypatch):
    monkeypatch.setattr(app_main.settings, "REMOTE_PROCESS_CONTROL_ENABLED", "enabled")
    with pytest.raises(RuntimeError, match="explicit yes/no boolean"):
        app_main._validate_runtime_security()


def test_https_origin_is_compared_to_external_host_not_private_proxy_hop(monkeypatch):
    from backend.app import security

    monkeypatch.setattr(security.settings, "ALLOW_INSECURE_HTTP", "no")
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/login",
            "headers": [
                (b"host", b"gpu-monitor.example.com"),
                (b"origin", b"https://gpu-monitor.example.com"),
                (b"sec-fetch-site", b"same-origin"),
            ],
            "client": ("127.0.0.1", 1234),
            "scheme": "http",
            "server": ("127.0.0.1", 8000),
        }
    )
    enforce_login_origin(request)


def test_legacy_bcrypt_rejects_ambiguous_long_utf8_password():
    from passlib.context import CryptContext
    from backend.app.security import hash_password, verify_password

    first = "密" * 24 + "甲"
    same_72_byte_prefix = "密" * 24 + "乙"
    legacy_hash = CryptContext(schemes=["bcrypt"]).hash(first)
    assert len(first.encode("utf-8")) > 72
    assert verify_password(first, legacy_hash) is False
    assert verify_password(same_72_byte_prefix, legacy_hash) is False

    modern_hash = hash_password(first)
    assert modern_hash.startswith("$bcrypt-sha256$")
    assert verify_password(first, modern_hash) is True
    assert verify_password(same_72_byte_prefix, modern_hash) is False
