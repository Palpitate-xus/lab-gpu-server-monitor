"""Webhook notifier for alert events (POST JSON; works with 企业微信/钉钉/飞书 via 转换).

Routing:
  - webhook_channels table: one row per target, each with its own template and
    a minimum severity filter (info | warning | critical)
  - legacy single-target settings (alert_webhook_url/template) are still honored
    as a fallback so existing deployments keep working
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import logging
import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urlparse

from .database import SessionLocal
from .models import AuditLog, Setting, WebhookChannel
from .security import decrypt_text, encrypt_text

logger = logging.getLogger("gpumon.alerts")

SETTING_WEBHOOK_URL = "alert_webhook_url"
SETTING_WEBHOOK_TEMPLATE = "alert_webhook_template"

# default template: plain JSON payload
DEFAULT_TEMPLATE = (
    '{"text": "[{{level}}] {{server_name}}: {{metric}}={{value}} {{op}} {{threshold}} '
    '({{rule_name}}) at {{time}}"}'
)

_SEV_RANK = {"info": 0, "warning": 1, "critical": 2}
WEBHOOK_ENCRYPTED_PREFIX = "fernet:"


def protect_webhook_url(url: str) -> str:
    value = (url or "").strip()
    return WEBHOOK_ENCRYPTED_PREFIX + encrypt_text(value) if value else ""


def reveal_webhook_url(stored: str) -> str:
    value = stored or ""
    if not value:
        return ""
    if value.startswith(WEBHOOK_ENCRYPTED_PREFIX):
        return decrypt_text(value.removeprefix(WEBHOOK_ENCRYPTED_PREFIX))
    # Compatibility for an existing installation until the startup migration
    # encrypts the row. New writes always use protect_webhook_url().
    return value


def redact_webhook_url(stored: str) -> str:
    value = reveal_webhook_url(stored)
    if not value:
        return ""
    try:
        parsed = urlparse(value)
        host = parsed.hostname or "configured"
        port = f":{parsed.port}" if parsed.port and parsed.port != 443 else ""
        return f"https://{host}{port}/…"
    except (TypeError, ValueError):
        return "configured (hidden)"


def secure_stored_webhook_urls() -> int:
    """Encrypt legacy plaintext URL rows and verify existing ciphertext."""
    db = SessionLocal()
    changed = 0
    try:
        targets = list(db.query(WebhookChannel).all())
        legacy = db.get(Setting, SETTING_WEBHOOK_URL)
        if legacy is not None:
            targets.append(legacy)
        for target in targets:
            stored = target.url if isinstance(target, WebhookChannel) else target.value
            if not stored:
                continue
            if stored.startswith(WEBHOOK_ENCRYPTED_PREFIX):
                reveal_webhook_url(stored)  # fail startup if the active keyring cannot decrypt
                continue
            protected = protect_webhook_url(stored)
            if isinstance(target, WebhookChannel):
                target.url = protected
            else:
                target.value = protected
            changed += 1
        if changed:
            db.add(
                AuditLog(
                    username="system:migration",
                    action="webhook.encrypt_urls",
                    detail=f"encrypted {changed} legacy webhook URL(s)",
                )
            )
            db.commit()
            logger.info("encrypted %d legacy webhook URL(s)", changed)
        else:
            db.rollback()
        return changed
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_webhook_config() -> tuple[str, str]:
    db = SessionLocal()
    try:
        url_row = db.get(Setting, SETTING_WEBHOOK_URL)
        tpl_row = db.get(Setting, SETTING_WEBHOOK_TEMPLATE)
        return (
            reveal_webhook_url((url_row.value if url_row else "") or ""),
            (tpl_row.value if tpl_row else "") or DEFAULT_TEMPLATE,
        )
    finally:
        db.close()


def _render(template: str, ctx: dict) -> str:
    """Placeholder substitution; values are JSON-string-escaped so user data
    can never break out of the payload structure."""
    out = template
    for k, v in ctx.items():
        # json.dumps then strip the outer quotes -> safe inline escaping
        safe = json.dumps(str(v), ensure_ascii=False)[1:-1]
        out = out.replace("{{" + k + "}}", safe)
    return out


def _resolve_webhook_target(url: str) -> tuple[object | None, str | None, str]:
    """Resolve once and return a public IP to which the TLS socket is pinned."""
    if not url:
        return None, None, "no webhook url configured"
    if len(url) > 2048:
        return None, None, "webhook url is too long"
    try:
        p = urlparse(url)
    except Exception:
        return None, None, "invalid url"
    if p.scheme != "https":
        return None, None, "webhook must use https://"
    if p.username or p.password or p.fragment:
        return None, None, "credentials and fragments are not allowed in webhook urls"
    host = p.hostname or ""
    if not host:
        return None, None, "invalid url"
    try:
        port = p.port or 443
    except ValueError:
        return None, None, "invalid webhook port"
    # Fail closed: only globally routable addresses are valid webhook targets.
    # This also excludes CGNAT/shared space and deprecated IPv6 site-local
    # ranges which are not covered consistently by the individual predicates.
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except Exception:
        return None, None, f"cannot resolve host {host}"
    public_ips: list[str] = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or getattr(ip, "is_site_local", False):
            return None, None, f"webhook host resolves to non-public address ({ip})"
        value = str(ip)
        if value not in public_ips:
            public_ips.append(value)
    if not public_ips:
        return None, None, "webhook host has no public address"
    return p, public_ips[0], ""


def _validate_webhook_url(url: str) -> tuple[bool, str]:
    parsed, pinned_ip, reason = _resolve_webhook_target(url)
    return bool(parsed and pinned_ip), reason


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, port: int, pinned_ip: str, timeout: float):
        super().__init__(
            hostname,
            port=port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        sock = socket.create_connection(
            (self._pinned_ip, self.port),
            self.timeout,
            self.source_address,
        )
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def send_webhook(url: str, template: str, ctx: dict) -> tuple[bool, str]:
    parsed, pinned_ip, reason = _resolve_webhook_target(url)
    if parsed is None or pinned_ip is None:
        return False, reason
    body = _render(template, ctx)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    host_header = parsed.hostname or ""
    if parsed.port and parsed.port != 443:
        host_header = f"{host_header}:{parsed.port}"
    conn = _PinnedHTTPSConnection(
        parsed.hostname or "",
        parsed.port or 443,
        pinned_ip,
        timeout=10,
    )
    try:
        conn.request(
            "POST",
            path,
            body=body.encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body.encode("utf-8"))),
                "Host": host_header,
                "User-Agent": "gpu-monitor-webhook/1",
            },
        )
        response = conn.getresponse()
        response.read(64 * 1024)
        # Redirects are never followed; treat every 3xx as a failed delivery.
        return 200 <= response.status < 300, f"HTTP {response.status}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        conn.close()


def _channels() -> list[tuple[str, str, str]]:
    """(url, template, min_severity) for all enabled targets."""
    out: list[tuple[str, str, str]] = []
    db = SessionLocal()
    try:
        for ch in db.query(WebhookChannel).filter(WebhookChannel.enabled.is_(True)).all():
            if ch.url:
                out.append(
                    (
                        reveal_webhook_url(ch.url),
                        ch.template or DEFAULT_TEMPLATE,
                        ch.min_severity or "info",
                    )
                )
    finally:
        db.close()
    if not out:
        url, tpl = get_webhook_config()
        if url:
            out.append((url, tpl, "info"))
    return out


def _dispatch(ctx: dict, severity: str = "info") -> tuple[bool, str]:
    targets = _channels()
    if not targets:
        return False, "webhook not configured"
    rank = _SEV_RANK.get(severity, 0)
    results = []
    for url, tpl, min_sev in targets:
        if _SEV_RANK.get(min_sev, 0) > rank:
            continue  # below this channel's threshold
        ok, msg = send_webhook(url, tpl, ctx)
        results.append((ok, msg))
    if not results:
        return False, "all channels below severity threshold"
    ok = any(r[0] for r in results)
    return ok, "; ".join(r[1] for r in results)


def notify_alert(server_name: str, metric: str, value: float, op: str, threshold: float,
                 rule_name: str, severity: str = "warning") -> tuple[bool, str]:
    ctx = {
        "level": "ALERT",
        "server_name": server_name,
        "metric": metric,
        "value": round(value, 1),
        "op": op,
        "threshold": threshold,
        "rule_name": rule_name,
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    return _dispatch(ctx, severity)


def notify_recovery(server_name: str, metric: str, rule_name: str,
                    severity: str = "info") -> tuple[bool, str]:
    ctx = {
        "level": "RECOVERY",
        "server_name": server_name,
        "metric": metric,
        "value": "",
        "op": "",
        "threshold": "",
        "rule_name": rule_name,
        "time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    return _dispatch(ctx, severity)
