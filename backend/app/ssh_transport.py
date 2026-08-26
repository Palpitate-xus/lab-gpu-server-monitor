"""SSH transport layer: connection, host-key TOFU, fault classification,
script execution via stdin (bash -s), output capping.

Fault taxonomy (error_code):
  OK | SSH_DOWN | SSH_AUTH_FAILED | SSH_HOSTKEY_CHANGED | SSH_DNS_FAILED |
  SSH_REFUSED | COLLECT_TIMEOUT | COLLECT_FAILED
"""

from __future__ import annotations

import io
import logging
import os
import re
import socket
from typing import Optional

import paramiko

from .config import get_settings
from .security import decrypt_text

settings = get_settings()
logger = logging.getLogger("gpumon.ssh")

MAX_OUTPUT_BYTES = 2 * 1024 * 1024


# ---------------------------------------------------------------- host keys

class _TofuPolicy(paramiko.client.MissingHostKeyPolicy):
    """Trust on first use: record the key in paramiko host-entries format.

    Entries are written as `[host]:port keytype base64` (or `host ...` for :22)
    so `client.load_host_keys()` matches them on later connects. A changed key
    surfaces as BadHostKeyException from connect(), mapped to
    SSH_HOSTKEY_CHANGED in classify_ssh_error().
    """

    def __init__(self, path: str, host: str, port: int):
        self.path = path
        self.pattern = f"[{host}]:{port}" if port != 22 else host

    def missing_host_key(self, client, hostname, key):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a") as f:
                f.write(f"{self.pattern} {key.get_name()} {key.get_base64()}\n")
        except Exception:
            logger.warning("cannot persist host key for %s", hostname)


def hostkey_path(server_key: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", server_key)
    return os.path.join(settings.DATA_DIR, "known_hosts", f"{safe}.keys")


def _has_recorded_key(server_key: str) -> bool:
    try:
        return os.path.getsize(hostkey_path(server_key)) > 0
    except OSError:
        return False


def forget_hostkey(server_key: str) -> None:
    try:
        os.remove(hostkey_path(server_key))
    except OSError:
        pass


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
    client = paramiko.SSHClient()
    ident = server_key or f"{host}_{port}"
    kh = hostkey_path(ident)
    if _has_recorded_key(ident):
        try:
            client.load_host_keys(kh)
        except Exception:
            pass
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
    if isinstance(e, CredentialDecryptionError):
        return "CRED_DECRYPT_FAILED", "已保存的 SSH 凭据无法解密（SECRET_KEY 已轮换）——请到服务器管理中重新录入该服务器的凭据"
    if isinstance(e, paramiko.AuthenticationException):
        return "SSH_AUTH_FAILED", "SSH 认证失败（检查用户名/密码/密钥）"
    if isinstance(e, paramiko.BadHostKeyException):
        return "SSH_HOSTKEY_CHANGED", "SSH 主机密钥发生变化（可能被中间人攻击或服务器重装，需人工确认后重置）"
    if "HOSTKEY_CHANGED" in msg:
        return "SSH_HOSTKEY_CHANGED", "SSH 主机密钥发生变化（可能被中间人攻击或服务器重装，需人工确认后重置）"
    if isinstance(e, socket.gaierror):
        return "SSH_DNS_FAILED", f"DNS 解析失败: {host}"
    if isinstance(e, ConnectionRefusedError):
        return "SSH_REFUSED", "连接被拒绝（sshd 未运行或端口错误）"
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "COLLECT_TIMEOUT", f"连接超时（{settings.SSH_CONNECT_TIMEOUT}s）"
    if isinstance(e, paramiko.SSHException):
        return "SSH_DOWN", f"SSH 协议错误: {msg[:200]}"
    if isinstance(e, OSError):
        return "SSH_DOWN", f"网络错误: {msg[:200]}"
    return "SSH_DOWN", f"{type(e).__name__}: {msg[:200]}"


# ---------------------------------------------------------------- exec

def run_remote(client: paramiko.SSHClient, command: str, timeout: int = 15) -> tuple[int, str, str]:
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read(MAX_OUTPUT_BYTES).decode("utf-8", errors="replace")
    err = stderr.read(65536).decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def run_script(client: paramiko.SSHClient, script: str, timeout: int = 30) -> tuple[int, str, str]:
    """Execute a shell script via stdin (`bash -s`): nothing lands on disk remotely."""
    _, stdout, stderr = client.exec_command("bash -s", timeout=timeout)
    chan = stdout.channel
    chan.send(script.encode())
    chan.shutdown_write()
    out = stdout.read(MAX_OUTPUT_BYTES).decode("utf-8", errors="replace")
    err = stderr.read(65536).decode("utf-8", errors="replace")
    code = chan.recv_exit_status()
    return code, out, err


def decrypt_creds(server) -> tuple[str, str, str]:
    return (
        decrypt_text(server.password or ""),
        decrypt_text(server.private_key or ""),
        decrypt_text(server.passphrase or ""),
    )
