"""SSH transport layer: connection, host-key TOFU, fault classification,
script execution via stdin (bash -s), output capping.

Fault taxonomy (error_code):
  OK | SSH_DOWN | SSH_AUTH_FAILED | SSH_HOSTKEY_CHANGED | SSH_DNS_FAILED |
  SSH_REFUSED | COLLECT_TIMEOUT | COLLECT_FAILED
"""

from __future__ import annotations

import fcntl
import base64
import hmac
import io
import logging
import os
import re
import socket
import tempfile
import threading
import time
from contextlib import contextmanager
from typing import Optional

import paramiko

from .config import get_settings
from .security import decrypt_text

settings = get_settings()
logger = logging.getLogger("gpumon.ssh")

MAX_OUTPUT_BYTES = 2 * 1024 * 1024
_HOSTKEY_LOCK = threading.RLock()
DISABLED_SSH_ALGORITHMS = {
    "keys": ("ssh-rsa",),
    "pubkeys": ("ssh-rsa",),
    "ciphers": ("3des-cbc", "aes128-cbc", "aes192-cbc", "aes256-cbc"),
    "macs": ("hmac-md5", "hmac-md5-96", "hmac-sha1", "hmac-sha1-96"),
}


class RootSshDisabledError(RuntimeError):
    pass


class HostKeyFingerprintMismatch(RuntimeError):
    pass


# ---------------------------------------------------------------- host keys

class _TofuPolicy(paramiko.client.MissingHostKeyPolicy):
    """Trust on first use: record the key in paramiko host-entries format.

    Entries are written as `[host]:port keytype base64` (or `host ...` for :22)
    so `client.load_host_keys()` matches them on later connects. A changed key
    surfaces as BadHostKeyException from connect(), mapped to
    SSH_HOSTKEY_CHANGED in classify_ssh_error().
    """

    def __init__(self, path: str, host: str, port: int):
        if not host or any(
            character.isspace() or ord(character) < 33 or ord(character) == 127
            for character in host
        ):
            raise ValueError("SSH host contains whitespace or control characters")
        self.path = path
        self.pattern = f"[{host}]:{port}" if port != 22 else host

    def missing_host_key(self, client, hostname, key):
        try:
            with _HOSTKEY_LOCK:
                with _hostkey_process_lock() as directory:
                    _ensure_hostkey_storage_locked(directory)
                    if os.path.exists(self.path):
                        _verify_recorded_key(self.path, self.pattern, hostname, key)
                    else:
                        fd, temporary = tempfile.mkstemp(prefix=".hostkey-", dir=directory)
                        try:
                            os.fchmod(fd, 0o600)
                            payload = f"{self.pattern} {key.get_name()} {key.get_base64()}\n".encode()
                            view = memoryview(payload)
                            while view:
                                written = os.write(fd, view)
                                if written <= 0:
                                    raise OSError("short write while persisting SSH host key")
                                view = view[written:]
                            os.fsync(fd)
                            os.close(fd)
                            fd = -1
                            _verify_recorded_key(temporary, self.pattern, hostname, key)
                            # link() is an atomic no-overwrite publish. A concurrent
                            # writer must be verified rather than silently replaced.
                            try:
                                os.link(temporary, self.path)
                            except FileExistsError:
                                _verify_recorded_key(self.path, self.pattern, hostname, key)
                            os.chmod(self.path, 0o600)
                            dir_fd = os.open(directory, os.O_RDONLY)
                            try:
                                os.fsync(dir_fd)
                            finally:
                                os.close(dir_fd)
                        finally:
                            if fd >= 0:
                                os.close(fd)
                            try:
                                os.unlink(temporary)
                            except FileNotFoundError:
                                pass
                    client.get_host_keys().add(self.pattern, key.get_name(), key)
        except paramiko.BadHostKeyException:
            raise
        except Exception as exc:
            logger.error("cannot safely persist host key for %s: %s", hostname, type(exc).__name__)
            raise paramiko.SSHException(
                f"refusing SSH connection: cannot persist host key for {hostname}"
            ) from exc


def _hostkey_dir() -> str:
    return os.path.join(settings.DATA_DIR, "known_hosts")


@contextmanager
def _hostkey_process_lock():
    directory = _hostkey_dir()
    os.makedirs(directory, mode=0o700, exist_ok=True)
    if os.path.islink(directory) or not os.path.isdir(directory):
        raise RuntimeError(f"host-key path is not a real directory: {directory}")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(os.path.join(directory, ".hostkey.lock"), flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield directory
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _ensure_hostkey_storage_locked(directory: str) -> None:
    os.chmod(directory, 0o700)
    for entry in os.scandir(directory):
        if entry.name.startswith(".hostkey-"):
            try:
                os.unlink(entry.path)
            except OSError:
                pass
            continue
        if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
            raise RuntimeError(f"unsafe entry in host-key directory: {entry.name}")
        os.chmod(entry.path, 0o600)
    # Verify actual create/flush/remove capability, not only os.access(),
    # which is unreliable for root and some network filesystems.
    fd, probe = tempfile.mkstemp(prefix=".write-test-", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, b"probe")
        os.fsync(fd)
    finally:
        os.close(fd)
        os.unlink(probe)


def ensure_hostkey_storage() -> None:
    with _HOSTKEY_LOCK:
        with _hostkey_process_lock() as directory:
            _ensure_hostkey_storage_locked(directory)


def hostkey_storage_ready() -> bool:
    try:
        with _HOSTKEY_LOCK:
            ensure_hostkey_storage()
        return True
    except Exception:
        return False


def _verify_recorded_key(path: str, pattern: str, hostname: str, key: paramiko.PKey) -> None:
    keys = paramiko.HostKeys(path)
    matched = keys.lookup(pattern)
    expected = matched.get(key.get_name()) if matched else None
    if expected is None or expected.asbytes() != key.asbytes():
        if expected is None:
            expected = next(iter(matched.values()), key) if matched else key
        raise paramiko.BadHostKeyException(hostname, key, expected)


def hostkey_path(server_key: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", server_key)
    return os.path.join(_hostkey_dir(), f"{safe}.keys")


def _has_recorded_key(server_key: str) -> bool:
    try:
        return os.path.getsize(hostkey_path(server_key)) > 0
    except OSError:
        return False


def forget_hostkey(server_key: str) -> bool:
    with _HOSTKEY_LOCK:
        with _hostkey_process_lock() as directory:
            _ensure_hostkey_storage_locked(directory)
            try:
                os.remove(hostkey_path(server_key))
                directory_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                return True
            except FileNotFoundError:
                return False


def _validate_expected_fingerprint(value: str) -> str:
    fingerprint = value.strip().rstrip("=")
    if not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", fingerprint):
        raise ValueError("expected fingerprint must use OpenSSH SHA256:... format")
    encoded = fingerprint.removeprefix("SHA256:")
    try:
        decoded = base64.b64decode(encoded + "=", validate=True)
    except ValueError as exc:
        raise ValueError("expected fingerprint is not valid base64") from exc
    if len(decoded) != 32:
        raise ValueError("expected fingerprint must contain a SHA-256 digest")
    return fingerprint


def _fetch_remote_host_key(host: str, port: int) -> paramiko.PKey:
    sock = socket.create_connection((host, port), timeout=settings.SSH_CONNECT_TIMEOUT)
    transport = None
    try:
        transport = paramiko.Transport(
            sock,
            disabled_algorithms=DISABLED_SSH_ALGORITHMS,
        )
        transport.start_client(timeout=settings.SSH_CONNECT_TIMEOUT)
        return transport.get_remote_server_key()
    finally:
        if transport is not None:
            transport.close()
        else:
            sock.close()


def replace_hostkey_with_expected_fingerprint(
    host: str,
    port: int,
    server_key: str,
    expected_fingerprint: str,
) -> str:
    """Fetch a host key without credentials and atomically pin it iff verified."""
    expected = _validate_expected_fingerprint(expected_fingerprint)
    path = hostkey_path(server_key)
    policy = _TofuPolicy(path, host, port)
    key = _fetch_remote_host_key(host, port)
    actual = key.fingerprint.rstrip("=")
    if not hmac.compare_digest(actual, expected):
        raise HostKeyFingerprintMismatch(
            f"host key fingerprint mismatch (received {actual})"
        )

    with _HOSTKEY_LOCK:
        with _hostkey_process_lock() as directory:
            _ensure_hostkey_storage_locked(directory)
            fd, temporary = tempfile.mkstemp(prefix=".hostkey-", dir=directory)
            try:
                os.fchmod(fd, 0o600)
                payload = f"{policy.pattern} {key.get_name()} {key.get_base64()}\n".encode()
                view = memoryview(payload)
                while view:
                    written = os.write(fd, view)
                    if written <= 0:
                        raise OSError("short write while pinning SSH host key")
                    view = view[written:]
                os.fsync(fd)
                os.close(fd)
                fd = -1
                _verify_recorded_key(temporary, policy.pattern, host, key)
                os.replace(temporary, path)
                os.chmod(path, 0o600)
                directory_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                if fd >= 0:
                    os.close(fd)
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
    return actual


# ---------------------------------------------------------------- connect

def load_pkey(private_key: str, passphrase: str) -> paramiko.PKey:
    password = passphrase or None
    last_err: Optional[Exception] = None
    for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        buf = io.StringIO(private_key)
        try:
            return cls.from_private_key(buf, password=password)
        except Exception as e:
            last_err = e
    raise ValueError(f"Cannot load private key: {last_err}")


def connect_host(
    host: str,
    port: int,
    username: str,
    password: str = "",
    private_key: str = "",
    passphrase: str = "",
    server_key: str = "",
) -> paramiko.SSHClient:
    """Connect with TOFU host-key verification keyed by server identity."""
    if username.strip().lower() == "root" and not settings.allow_root_ssh:
        raise RootSshDisabledError(
            "root SSH is disabled; use a dedicated least-privilege gpumon account"
        )
    client = paramiko.SSHClient()
    ident = server_key or f"{host}_{port}"
    kh = hostkey_path(ident)
    if _has_recorded_key(ident):
        client.load_host_keys(kh)
        # recorded keys loaded; a *changed* key raises BadHostKeyException;
        # anything still unmatched is rejected outright
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(_TofuPolicy(kh, host, port))
    kwargs = {
        "hostname": host,
        "port": port,
        "username": username,
        "timeout": settings.SSH_CONNECT_TIMEOUT,
        "banner_timeout": settings.SSH_CONNECT_TIMEOUT,
        "auth_timeout": settings.SSH_CONNECT_TIMEOUT,
        "allow_agent": False,
        "look_for_keys": False,
        "disabled_algorithms": DISABLED_SSH_ALGORITHMS,
    }
    if private_key:
        kwargs["pkey"] = load_pkey(private_key, passphrase)
    else:
        kwargs["password"] = password
    client.connect(**kwargs)
    return client


def connect_server(server) -> paramiko.SSHClient:
    """Connect using a Server ORM object's encrypted credentials."""
    return connect_host(
        host=server.host,
        port=server.port or 22,
        username=server.username,
        password=decrypt_text(server.password or ""),
        private_key=decrypt_text(server.private_key or ""),
        passphrase=decrypt_text(server.passphrase or ""),
        server_key=f"server_{server.id}",
    )


def classify_ssh_error(e: Exception, host: str) -> tuple[str, str]:
    from .security import CredentialDecryptionError
    msg = str(e)
    logger.warning(
        "SSH operation failed for %r (%s): %s",
        host,
        type(e).__name__,
        msg[:300].replace("\r", " ").replace("\n", " "),
    )
    if isinstance(e, CredentialDecryptionError):
        return "CRED_DECRYPT_FAILED", "已保存的 SSH 凭据无法解密（凭据加密密钥不匹配）——请恢复旧密钥或重新录入凭据"
    if isinstance(e, RootSshDisabledError):
        return "SSH_ROOT_DISABLED", "已禁止 root SSH，请改用专用低权限 gpumon 账号"
    if isinstance(e, paramiko.AuthenticationException):
        return "SSH_AUTH_FAILED", "SSH 认证失败（检查用户名/密码/密钥）"
    if isinstance(e, paramiko.BadHostKeyException):
        return "SSH_HOSTKEY_CHANGED", "SSH 主机密钥发生变化（可能被中间人攻击或服务器重装，需人工确认后重置）"
    if "HOSTKEY_CHANGED" in msg:
        return "SSH_HOSTKEY_CHANGED", "SSH 主机密钥发生变化（可能被中间人攻击或服务器重装，需人工确认后重置）"
    if isinstance(e, socket.gaierror):
        return "SSH_DNS_FAILED", "DNS 解析失败"
    if isinstance(e, ConnectionRefusedError):
        return "SSH_REFUSED", "连接被拒绝（sshd 未运行或端口错误）"
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "COLLECT_TIMEOUT", f"连接超时（{settings.SSH_CONNECT_TIMEOUT}s）"
    if isinstance(e, paramiko.SSHException):
        return "SSH_DOWN", "SSH 协议错误"
    if isinstance(e, OSError):
        return "SSH_DOWN", "网络连接失败"
    return "SSH_DOWN", "SSH 连接失败"


# ---------------------------------------------------------------- exec

def _recv_exit_status(chan, timeout: int) -> int:
    """Bounded wait for the remote exit status; recv_exit_status() alone can
    block forever when the channel timeout is not honored."""
    deadline = time.time() + timeout
    while not chan.exit_status_ready():
        if chan.closed or time.time() > deadline:
            return -1
        time.sleep(0.1)
    return chan.recv_exit_status()


def run_remote(client: paramiko.SSHClient, command: str, timeout: int = 15) -> tuple[int, str, str]:
    # Callers pass only fixed collector commands or values built from validated
    # integers/Literal signal names; no raw request string reaches this sink.
    _, stdout, stderr = client.exec_command(command, timeout=timeout)  # nosec B601
    out = stdout.read(MAX_OUTPUT_BYTES).decode("utf-8", errors="replace")
    err = stderr.read(65536).decode("utf-8", errors="replace")
    code = _recv_exit_status(stdout.channel, timeout)
    return code, out, err


def run_script(client: paramiko.SSHClient, script: str, timeout: int = 30) -> tuple[int, str, str]:
    """Execute a shell script via stdin (`bash -s`): nothing lands on disk remotely."""
    _, stdout, stderr = client.exec_command("bash -s", timeout=timeout)  # nosec B601
    chan = stdout.channel
    chan.send(script.encode())
    chan.shutdown_write()
    out = stdout.read(MAX_OUTPUT_BYTES).decode("utf-8", errors="replace")
    err = stderr.read(65536).decode("utf-8", errors="replace")
    code = _recv_exit_status(chan, timeout)
    return code, out, err


def decrypt_creds(server) -> tuple[str, str, str]:
    return (
        decrypt_text(server.password or ""),
        decrypt_text(server.private_key or ""),
        decrypt_text(server.passphrase or ""),
    )
