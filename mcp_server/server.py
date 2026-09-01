"""Read-only MCP server backed by the GPU Monitor REST API.

The MCP process never connects to monitored machines or the SQL database. It
logs in to the existing FastAPI application with a least-privilege viewer
account and exposes a small, read-only GPU-focused tool surface over stdio.
"""

from __future__ import annotations

import json
import os
import ssl
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

from mcp.server import MCPServer
from mcp.types import ToolAnnotations


MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class GpuMonitorApiError(RuntimeError):
    """A safe-to-report error returned by, or while calling, GPU Monitor."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_loopback(hostname: str | None) -> bool:
    host = (hostname or "").strip("[]").lower()
    return host == "localhost" or host == "::1" or host.startswith("127.")


def _error_detail(raw: bytes) -> str:
    if not raw:
        return "request failed"
    text = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(text)
        detail = (
            payload.get("detail", payload) if isinstance(payload, dict) else payload
        )
        if isinstance(detail, str):
            return detail[:500]
        return json.dumps(detail, ensure_ascii=False, default=str)[:500]
    except (ValueError, TypeError):
        return text[:500]


@dataclass
class GpuMonitorClient:
    """Small synchronous client with lazy login and one automatic re-login."""

    base_url: str
    username: str
    password: str = field(repr=False)
    timeout: float = 15.0
    verify_tls: bool = True
    allow_insecure_http: bool = False
    _token: str = field(default="", init=False, repr=False)
    _token_lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )
    _opener: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise GpuMonitorApiError(
                "GPU_MONITOR_URL must be an absolute http:// or https:// URL"
            )
        if parsed.username or parsed.password:
            raise GpuMonitorApiError(
                "Do not embed credentials in GPU_MONITOR_URL; use the username/password variables"
            )
        if (
            parsed.scheme == "http"
            and not _is_loopback(parsed.hostname)
            and not self.allow_insecure_http
        ):
            raise GpuMonitorApiError(
                "Refusing to send credentials over remote plain HTTP. Use HTTPS or set "
                "GPU_MONITOR_ALLOW_INSECURE_HTTP=yes for a trusted private network."
            )
        if not self.username:
            raise GpuMonitorApiError("GPU_MONITOR_USERNAME is required")
        if not self.password:
            raise GpuMonitorApiError("GPU_MONITOR_PASSWORD is required")
        if self.timeout <= 0 or self.timeout > 120:
            raise GpuMonitorApiError("GPU_MONITOR_TIMEOUT must be in (0, 120] seconds")

        handlers: list[Any] = []
        # Local monitor traffic should not accidentally leave through an HTTP proxy.
        if _is_loopback(parsed.hostname):
            handlers.append(ProxyHandler({}))
        if parsed.scheme == "https" and not self.verify_tls:
            handlers.append(HTTPSHandler(context=ssl._create_unverified_context()))
        self._opener = build_opener(*handlers)

    @classmethod
    def from_env(cls) -> "GpuMonitorClient":
        try:
            timeout = float(os.getenv("GPU_MONITOR_TIMEOUT", "15"))
        except ValueError as exc:
            raise GpuMonitorApiError("GPU_MONITOR_TIMEOUT must be a number") from exc
        return cls(
            base_url=os.getenv("GPU_MONITOR_URL", "http://127.0.0.1:8300"),
            username=os.getenv("GPU_MONITOR_USERNAME", "").strip(),
            password=os.getenv("GPU_MONITOR_PASSWORD", ""),
            timeout=timeout,
            verify_tls=_env_bool("GPU_MONITOR_VERIFY_TLS", True),
            allow_insecure_http=_env_bool("GPU_MONITOR_ALLOW_INSECURE_HTTP", False),
        )

    def _send(
        self,
        path: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
        content_type: str = "application/json",
        token: str = "",
        params: dict[str, Any] | None = None,
    ) -> Any:
        if not path.startswith("/"):
            raise GpuMonitorApiError("API path must start with /")
        url = self.base_url + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None and v != ""}
            if clean:
                url += "?" + urlencode(clean)
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = content_type
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raw = exc.read(64 * 1024)
            raise GpuMonitorApiError(
                f"GPU Monitor API returned HTTP {exc.code}: {_error_detail(raw)}",
                status=exc.code,
            ) from None
        except URLError as exc:
            reason = str(getattr(exc, "reason", exc))[:300]
            raise GpuMonitorApiError(
                f"Cannot reach GPU Monitor at {self.base_url}: {reason}"
            ) from None
        except TimeoutError:
            raise GpuMonitorApiError(
                f"GPU Monitor request timed out after {self.timeout:g}s"
            ) from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise GpuMonitorApiError(
                "GPU Monitor response exceeded the 16 MiB safety limit"
            )
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            raise GpuMonitorApiError(
                "GPU Monitor returned a non-JSON response"
            ) from None

    def _login(self) -> str:
        form = urlencode(
            {"username": self.username, "password": self.password}
        ).encode()
        payload = self._send(
            "/api/auth/login",
            method="POST",
            data=form,
            content_type="application/x-www-form-urlencoded",
        )
        token = payload.get("access_token", "") if isinstance(payload, dict) else ""
        if not token:
            raise GpuMonitorApiError(
                "GPU Monitor login succeeded without an access token"
            )
        self._token = token
        return token

    def _access_token(self) -> str:
        with self._token_lock:
            return self._token or self._login()

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Authenticated GET, retrying once when the two-hour JWT expires."""
        if not path.startswith("/api/"):
            raise GpuMonitorApiError("Only GPU Monitor /api/ endpoints are allowed")
        for attempt in range(2):
            token = self._access_token()
            try:
                return self._send(path, token=token, params=params)
            except GpuMonitorApiError as exc:
                if exc.status != 401 or attempt:
                    raise
                with self._token_lock:
                    if self._token == token:
                        self._token = ""
        raise GpuMonitorApiError("GPU Monitor authentication failed")

    def health(self) -> Any:
        return self._send("/api/health")


_client_instance: GpuMonitorClient | None = None
_client_guard = threading.Lock()


def _get_client() -> GpuMonitorClient:
    global _client_instance
    if _client_instance is None:
        with _client_guard:
            if _client_instance is None:
                _client_instance = GpuMonitorClient.from_env()
    return _client_instance


def _as_list(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise GpuMonitorApiError(f"GPU Monitor returned an invalid {label} payload")
    return [item for item in value if isinstance(item, dict)]


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _rounded(value: Any, digits: int = 1) -> float:
    return round(_number(value), digits)


def _memory_percent(used: Any, total: Any) -> float:
    total_n = _number(total)
    return round(_number(used) / total_n * 100, 1) if total_n else 0.0


def _data_age_seconds(collected_at: Any) -> int | None:
    if not isinstance(collected_at, str) or not collected_at:
        return None
    try:
        collected = datetime.fromisoformat(collected_at.replace("Z", "+00:00"))
        if collected.tzinfo is None:
            collected = collected.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - collected).total_seconds()))
    except ValueError:
        return None


def _gpu_snapshot(
    gpu: dict[str, Any], include_processes: bool = True
) -> dict[str, Any]:
    """Return useful GPU fields while bounding process data sent to the model."""
    out = {
        "index": gpu.get("index", 0),
        "uuid": gpu.get("uuid", ""),
        "name": gpu.get("name", ""),
        "serial": gpu.get("serial", ""),
        "pci_bus_id": gpu.get("pci_bus_id", ""),
        "utilization_pct": _rounded(gpu.get("utilization")),
        "memory_utilization_pct": _rounded(gpu.get("util_memory")),
        "memory_used_mb": _rounded(gpu.get("mem_used_mb")),
        "memory_total_mb": _rounded(gpu.get("mem_total_mb")),
        "memory_used_pct": _memory_percent(
            gpu.get("mem_used_mb"), gpu.get("mem_total_mb")
        ),
        "temperature_c": _rounded(gpu.get("temperature")),
        "memory_temperature_c": _rounded(gpu.get("mem_temperature")),
        "power_draw_w": _rounded(gpu.get("power_draw")),
        "power_limit_w": _rounded(gpu.get("power_limit")),
        "fan_speed_pct": _rounded(gpu.get("fan_speed")),
        "pstate": gpu.get("pstate", ""),
        "compute_mode": gpu.get("compute_mode", ""),
        "clock_graphics_mhz": _rounded(gpu.get("clock_graphics")),
        "clock_memory_mhz": _rounded(gpu.get("clock_memory")),
        "throttle_reasons": list(gpu.get("throttle_reasons") or []),
        "ecc_supported": bool(gpu.get("ecc_supported", False)),
        "ecc_corrected_volatile": int(_number(gpu.get("ecc_corrected_volatile"))),
        "ecc_uncorrected_volatile": int(_number(gpu.get("ecc_uncorrected_volatile"))),
        "ecc_corrected_total": int(_number(gpu.get("ecc_corrected_total"))),
        "ecc_uncorrected_total": int(_number(gpu.get("ecc_uncorrected_total"))),
        "retired_pages_pending": int(_number(gpu.get("retired_pending"))),
        "remapped_rows_pending": int(_number(gpu.get("remapped_pending"))),
        "remapped_rows_failure": int(_number(gpu.get("remapped_failure"))),
        "pcie_generation": {
            "current": int(_number(gpu.get("pcie_gen_current"))),
            "maximum": int(_number(gpu.get("pcie_gen_max"))),
        },
        "pcie_width": {
            "current": int(_number(gpu.get("pcie_width_current"))),
            "maximum": int(_number(gpu.get("pcie_width_max"))),
        },
    }
    processes = [p for p in (gpu.get("processes") or []) if isinstance(p, dict)]
    out["process_count"] = len(processes)
    if include_processes:
        out["processes"] = [
            {
                "pid": p.get("pid"),
                "user": p.get("user", ""),
                "command": str(p.get("command") or "")[:120],
                "gpu_memory_mb": _rounded(p.get("mem_mb")),
            }
            for p in processes[:50]
        ]
        out["processes_truncated"] = len(processes) > 50
    return out


def _server_public(server: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": server.get("id"),
        "name": server.get("name", ""),
        "host": server.get("host", ""),
        "port": server.get("port", 22),
        "enabled": bool(server.get("enabled", False)),
        "server_type": server.get("server_type", "gpu"),
        "lifecycle_status": server.get("status") or "active",
        "status_reason": server.get("status_reason") or "",
        "status_until": server.get("status_until"),
        "tags": list(server.get("tags") or []),
    }


def _resolve_server(api: GpuMonitorClient, reference: str) -> dict[str, Any]:
    ref = str(reference or "").strip()
    if not ref:
        raise GpuMonitorApiError(
            "server must be an ID, exact name, hostname, or host address"
        )
    servers = _as_list(api.get("/api/servers"), "server list")
    gpu_servers = [s for s in servers if s.get("server_type", "gpu") != "cpu"]

    matches: list[dict[str, Any]] = []
    if ref.isdigit():
        matches = [s for s in gpu_servers if s.get("id") == int(ref)]
    if not matches:
        folded = ref.casefold()
        matches = [
            s
            for s in gpu_servers
            if folded
            in {
                str(s.get("name", "")).casefold(),
                str(s.get("host", "")).casefold(),
            }
        ]
    if not matches:
        folded = ref.casefold()
        matches = [
            s for s in gpu_servers if folded in str(s.get("name", "")).casefold()
        ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        choices = ", ".join(f"{s.get('id')}:{s.get('name')}" for s in matches[:10])
        raise GpuMonitorApiError(
            f"server reference is ambiguous; choose one of: {choices}"
        )
    available = ", ".join(f"{s.get('id')}:{s.get('name')}" for s in gpu_servers[:20])
    raise GpuMonitorApiError(
        f"GPU server not found: {ref}. Available GPU servers: {available or 'none'}"
    )


def _summarize_matrix(
    rows: list[dict[str, Any]], include_disabled: bool
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if not include_disabled and not row.get("enabled", False):
            continue
        gpus = [g for g in (row.get("gpus") or []) if isinstance(g, dict)]
        utils = [_number(g.get("utilization")) for g in gpus]
        temperatures = [_number(g.get("temperature")) for g in gpus]
        mem_used = sum(_number(g.get("mem_used_mb")) for g in gpus)
        mem_total = sum(_number(g.get("mem_total_mb")) for g in gpus)
        out.append(
            {
                "server_id": row.get("server_id"),
                "server_name": row.get("server_name", ""),
                "hostname": row.get("hostname", ""),
                "enabled": bool(row.get("enabled", False)),
                "online": bool(row.get("online", False)),
                "lifecycle_status": row.get("status") or "active",
                "tags": list(row.get("tags") or []),
                "error": row.get("error", ""),
                "gpu_count": len(gpus),
                "average_utilization_pct": round(sum(utils) / len(utils), 1)
                if utils
                else 0.0,
                "memory_used_mb": round(mem_used, 1),
                "memory_total_mb": round(mem_total, 1),
                "memory_used_pct": _memory_percent(mem_used, mem_total),
                "maximum_temperature_c": round(max(temperatures), 1)
                if temperatures
                else 0.0,
                "power_draw_w": round(
                    sum(_number(g.get("power_draw")) for g in gpus), 1
                ),
            }
        )
    return out


READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)

mcp = MCPServer("gpu_monitor_mcp")


@mcp.tool(annotations=READ_ONLY)
def gpu_monitor_connection_status() -> dict[str, Any]:
    """Check GPU Monitor reachability and verify the configured viewer login."""
    api = _get_client()
    health = api.health()
    me = api.get("/api/auth/me")
    return {
        "base_url": api.base_url,
        "health": health,
        "authenticated_user": {
            "username": me.get("username", "") if isinstance(me, dict) else "",
            "display_name": me.get("display_name", "") if isinstance(me, dict) else "",
            "role": me.get("role", "") if isinstance(me, dict) else "",
        },
        "read_only_tools": True,
    }


@mcp.tool(annotations=READ_ONLY)
def gpu_monitor_list_servers(include_disabled: bool = False) -> dict[str, Any]:
    """List GPU servers with their latest aggregate GPU status.

    Args:
        include_disabled: Include servers disabled in GPU Monitor.
    """
    rows = _as_list(_get_client().get("/api/metrics/cluster-gpus"), "GPU matrix")
    servers = _summarize_matrix(rows, include_disabled)
    return {"count": len(servers), "servers": servers}


@mcp.tool(annotations=READ_ONLY)
def gpu_monitor_cluster_summary() -> dict[str, Any]:
    """Return current cluster-wide GPU utilization, memory, temperature, power and risk."""
    api = _get_client()
    matrix = _as_list(api.get("/api/metrics/cluster-gpus"), "GPU matrix")
    enabled_rows = [row for row in matrix if row.get("enabled", False)]
    gpus = [
        gpu
        for row in enabled_rows
        if row.get("online", False)
        for gpu in (row.get("gpus") or [])
        if isinstance(gpu, dict)
    ]
    utils = [_number(g.get("utilization")) for g in gpus]
    temperatures = [_number(g.get("temperature")) for g in gpus]
    mem_used = sum(_number(g.get("mem_used_mb")) for g in gpus)
    mem_total = sum(_number(g.get("mem_total_mb")) for g in gpus)
    analysis = api.get("/api/cluster/gpu-analysis")
    analysis = analysis if isinstance(analysis, dict) else {}
    risky = [g for g in (analysis.get("gpus") or []) if isinstance(g, dict)]
    risky.sort(key=lambda item: _number(item.get("risk")), reverse=True)
    return {
        "servers": {
            "total": len(matrix),
            "enabled": len(enabled_rows),
            "online": sum(1 for row in enabled_rows if row.get("online", False)),
            "offline": sum(1 for row in enabled_rows if not row.get("online", False)),
        },
        "gpus": {
            "total_reporting": len(gpus),
            "busy": sum(1 for g in gpus if _number(g.get("utilization")) >= 5),
            "idle": sum(1 for g in gpus if _number(g.get("utilization")) < 5),
            "idle_with_memory_held": sum(
                1
                for g in gpus
                if _number(g.get("utilization")) < 5
                and _memory_percent(g.get("mem_used_mb"), g.get("mem_total_mb")) >= 30
            ),
            "average_utilization_pct": round(sum(utils) / len(utils), 1)
            if utils
            else 0.0,
            "memory_used_mb": round(mem_used, 1),
            "memory_total_mb": round(mem_total, 1),
            "memory_used_pct": _memory_percent(mem_used, mem_total),
            "maximum_temperature_c": round(max(temperatures), 1)
            if temperatures
            else 0.0,
            "power_draw_w": round(sum(_number(g.get("power_draw")) for g in gpus), 1),
        },
        "risk": {
            "idle_held_count": int(_number(analysis.get("idle_held_count"))),
            "high_risk_count": int(_number(analysis.get("high_risk_count"))),
            "highest_risk_gpus": risky[:10],
        },
    }


@mcp.tool(annotations=READ_ONLY)
def gpu_monitor_get_server_gpu_info(server: str) -> dict[str, Any]:
    """Get a detailed latest GPU snapshot for one server.

    Args:
        server: Server ID, exact name, hostname, host address, or an unambiguous name fragment.
    """
    api = _get_client()
    resolved = _resolve_server(api, server)
    server_id = int(resolved["id"])
    latest = api.get(f"/api/metrics/server/{server_id}/latest")
    if not isinstance(latest, dict):
        raise GpuMonitorApiError("GPU Monitor returned an invalid latest metric")
    risk_payload = api.get(f"/api/servers/{server_id}/risk")
    risks = risk_payload.get("gpus", []) if isinstance(risk_payload, dict) else []
    risk_by_uuid = {
        str(item.get("uuid")): item
        for item in risks
        if isinstance(item, dict) and item.get("uuid")
    }
    snapshots = []
    for raw_gpu in latest.get("gpus") or []:
        if not isinstance(raw_gpu, dict):
            continue
        gpu = _gpu_snapshot(raw_gpu)
        risk = risk_by_uuid.get(str(raw_gpu.get("uuid")), {})
        gpu["risk"] = {
            "score": int(_number(risk.get("risk"))),
            "label": risk.get("risk_label", "unknown"),
            "xid_events_24h": int(_number(risk.get("xid_events"))),
            "thermal_throttle_samples_24h": int(
                _number(risk.get("thermal_throttle_samples"))
            ),
            "maximum_temperature_24h_c": _rounded(risk.get("max_temp")),
        }
        snapshots.append(gpu)
    return {
        "server": _server_public(resolved),
        "metric": {
            "collected_at": latest.get("collected_at"),
            "age_seconds": _data_age_seconds(latest.get("collected_at")),
            "status": latest.get("status", "unknown"),
            "error_code": latest.get("error_code", ""),
            "error": latest.get("error", ""),
            "hostname": latest.get("hostname", ""),
            "gpu_driver": latest.get("gpu_driver", ""),
            "ssh_latency_seconds": _rounded(latest.get("ssh_latency"), 3),
            "collection_duration_seconds": _rounded(latest.get("duration"), 2),
        },
        "gpu_count": len(snapshots),
        "gpus": snapshots,
    }


@mcp.tool(annotations=READ_ONLY)
def gpu_monitor_get_gpu_history(
    server: str, hours: int = 6, max_points: int = 120
) -> dict[str, Any]:
    """Get downsampled aggregate GPU history for one server.

    Args:
        server: Server ID, name, hostname, host address, or unique name fragment.
        hours: History window from 1 to 168 hours.
        max_points: Maximum returned points from 10 to 720.
    """
    if isinstance(hours, bool) or not 1 <= hours <= 168:
        raise GpuMonitorApiError("hours must be between 1 and 168")
    if isinstance(max_points, bool) or not 10 <= max_points <= 720:
        raise GpuMonitorApiError("max_points must be between 10 and 720")
    api = _get_client()
    resolved = _resolve_server(api, server)
    rows = _as_list(
        api.get(
            f"/api/metrics/server/{int(resolved['id'])}/history",
            {"hours": hours},
        ),
        "GPU history",
    )
    if len(rows) > max_points:
        scale = (len(rows) - 1) / (max_points - 1)
        indices = sorted({round(i * scale) for i in range(max_points)})
        rows = [rows[index] for index in indices]
    points = [
        {
            "time": row.get("time"),
            "utilization_pct": _rounded(row.get("gpu_util")),
            "memory_used_mb": _rounded(row.get("gpu_mem_used_mb")),
            "memory_used_pct": _rounded(row.get("gpu_mem_percent")),
            "maximum_temperature_c": _rounded(row.get("gpu_temp")),
            "power_draw_w": _rounded(row.get("gpu_power")),
            "average_graphics_clock_mhz": _rounded(row.get("gpu_clock")),
        }
        for row in rows
    ]
    utils = [_number(point["utilization_pct"]) for point in points]
    temps = [_number(point["maximum_temperature_c"]) for point in points]
    powers = [_number(point["power_draw_w"]) for point in points]
    return {
        "server": _server_public(resolved),
        "window_hours": hours,
        "point_count": len(points),
        "summary": {
            "average_utilization_pct": round(sum(utils) / len(utils), 1)
            if utils
            else 0.0,
            "maximum_temperature_c": round(max(temps), 1) if temps else 0.0,
            "average_power_draw_w": round(sum(powers) / len(powers), 1)
            if powers
            else 0.0,
        },
        "points": points,
    }


@mcp.tool(annotations=READ_ONLY)
def gpu_monitor_get_gpu_processes(server: str) -> dict[str, Any]:
    """List current compute processes and GPU memory use on one GPU server."""
    api = _get_client()
    resolved = _resolve_server(api, server)
    latest = api.get(f"/api/metrics/server/{int(resolved['id'])}/latest")
    if not isinstance(latest, dict):
        raise GpuMonitorApiError("GPU Monitor returned an invalid latest metric")
    gpu_rows = []
    total = 0
    for raw_gpu in latest.get("gpus") or []:
        if not isinstance(raw_gpu, dict):
            continue
        processes = [p for p in (raw_gpu.get("processes") or []) if isinstance(p, dict)]
        total += len(processes)
        gpu_rows.append(
            {
                "gpu_index": raw_gpu.get("index"),
                "gpu_uuid": raw_gpu.get("uuid", ""),
                "gpu_name": raw_gpu.get("name", ""),
                "process_count": len(processes),
                "processes": [
                    {
                        "pid": p.get("pid"),
                        "user": p.get("user", ""),
                        "command": str(p.get("command") or "")[:120],
                        "gpu_memory_mb": _rounded(p.get("mem_mb")),
                    }
                    for p in processes[:100]
                ],
                "processes_truncated": len(processes) > 100,
            }
        )
    return {
        "server": _server_public(resolved),
        "collected_at": latest.get("collected_at"),
        "age_seconds": _data_age_seconds(latest.get("collected_at")),
        "total_processes": total,
        "gpus": gpu_rows,
    }


@mcp.tool(annotations=READ_ONLY)
def gpu_monitor_get_risk_analysis(
    minimum_risk: int = 0, idle_only: bool = False, limit: int = 100
) -> dict[str, Any]:
    """Get cluster GPU risk scores and persistent idle-memory-holding detection.

    Args:
        minimum_risk: Include GPUs with a risk score at or above 0-100.
        idle_only: Return only GPUs holding memory while idle.
        limit: Maximum GPUs returned from 1 to 200.
    """
    if isinstance(minimum_risk, bool) or not 0 <= minimum_risk <= 100:
        raise GpuMonitorApiError("minimum_risk must be between 0 and 100")
    if isinstance(limit, bool) or not 1 <= limit <= 200:
        raise GpuMonitorApiError("limit must be between 1 and 200")
    payload = _get_client().get("/api/cluster/gpu-analysis")
    if not isinstance(payload, dict):
        raise GpuMonitorApiError("GPU Monitor returned an invalid risk analysis")
    gpus = [
        item
        for item in (payload.get("gpus") or [])
        if isinstance(item, dict)
        and _number(item.get("risk")) >= minimum_risk
        and (not idle_only or bool(item.get("idle_held", False)))
    ]
    return {
        "cluster_total_gpus": int(_number(payload.get("total_gpus"))),
        "cluster_idle_held_count": int(_number(payload.get("idle_held_count"))),
        "cluster_high_risk_count": int(_number(payload.get("high_risk_count"))),
        "filters": {
            "minimum_risk": minimum_risk,
            "idle_only": idle_only,
            "limit": limit,
        },
        "matched_count": len(gpus),
        "returned_count": min(len(gpus), limit),
        "gpus": gpus[:limit],
    }


@mcp.tool(annotations=READ_ONLY)
def gpu_monitor_get_gpu_alerts(
    server: str = "", open_only: bool = True, limit: int = 50
) -> dict[str, Any]:
    """Get GPU-related alert events, optionally restricted to one server.

    Args:
        server: Optional server ID/name/hostname/host; empty means the whole cluster.
        open_only: Return only unrecovered alerts when true.
        limit: Maximum source events inspected, from 1 to 200.
    """
    if isinstance(limit, bool) or not 1 <= limit <= 200:
        raise GpuMonitorApiError("limit must be between 1 and 200")
    api = _get_client()
    params: dict[str, Any] = {
        "open_only": str(bool(open_only)).lower(),
        "limit": limit,
    }
    resolved = None
    if str(server or "").strip():
        resolved = _resolve_server(api, server)
        params["server_id"] = int(resolved["id"])
    rows = _as_list(api.get("/api/alerts/events", params), "alert event list")
    gpu_terms = ("GPU", "XID", "ECC", "PCIE", "NVIDIA", "NVML")
    events = []
    for row in rows:
        haystack = " ".join(
            str(row.get(key) or "") for key in ("metric", "rule_name", "message")
        ).upper()
        if any(term in haystack for term in gpu_terms):
            events.append(
                {
                    "id": row.get("id"),
                    "server_id": row.get("server_id"),
                    "server_name": row.get("server_name", ""),
                    "metric": row.get("metric", ""),
                    "rule_name": row.get("rule_name", ""),
                    "message": row.get("message", ""),
                    "value": row.get("value"),
                    "threshold": row.get("threshold"),
                    "triggered_at": row.get("triggered_at"),
                    "recovered_at": row.get("recovered_at"),
                    "acked_at": row.get("acked_at"),
                    "acked_by": row.get("acked_by", ""),
                    "assignee": row.get("assignee", ""),
                }
            )
    return {
        "server": _server_public(resolved) if resolved else None,
        "open_only": bool(open_only),
        "count": len(events),
        "events": events,
    }


def main() -> None:
    """Run the local stdio transport; stdout is reserved for MCP framing."""
    mcp.run()


if __name__ == "__main__":
    main()
