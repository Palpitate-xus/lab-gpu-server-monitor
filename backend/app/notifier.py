"""Webhook notifier for alert events (POST JSON; works with企业微信/钉钉/飞书 via 转换)."""

from __future__ import annotations

import logging
import urllib.request
from datetime import datetime, timezone

from .database import SessionLocal
from .models import Setting

logger = logging.getLogger("gpumon.alerts")

SETTING_WEBHOOK_URL = "alert_webhook_url"
SETTING_WEBHOOK_TEMPLATE = "alert_webhook_template"

# default template: plain JSON payload
DEFAULT_TEMPLATE = (
    '{"text": "[{{level}}] {{server_name}}: {{metric}}={{value}} {{op}} {{threshold}} '
    '({{rule_name}}) at {{time}}"}'
)


def get_webhook_config() -> tuple[str, str]:
    db = SessionLocal()
    try:
        url_row = db.get(Setting, SETTING_WEBHOOK_URL)
        tpl_row = db.get(Setting, SETTING_WEBHOOK_TEMPLATE)
        return (
            (url_row.value if url_row else "") or "",
            (tpl_row.value if tpl_row else "") or DEFAULT_TEMPLATE,
        )
    finally:
        db.close()


def _render(template: str, ctx: dict) -> str:
    out = template
    for k, v in ctx.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out


def send_webhook(url: str, template: str, ctx: dict) -> tuple[bool, str]:
    if not url:
        return False, "no webhook url configured"
    body = _render(template, ctx)
    req = urllib.request.Request(
        url,
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status < 300, f"HTTP {resp.status}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def notify_alert(server_name: str, metric: str, value: float, op: str, threshold: float, rule_name: str) -> tuple[bool, str]:
    url, template = get_webhook_config()
    if not url:
        return False, "webhook not configured"
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
    return send_webhook(url, template, ctx)


def notify_recovery(server_name: str, metric: str, rule_name: str) -> tuple[bool, str]:
    url, template = get_webhook_config()
    if not url:
        return False, "webhook not configured"
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
    return send_webhook(url, template, ctx)
