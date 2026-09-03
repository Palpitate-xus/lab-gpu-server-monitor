from __future__ import annotations

import hashlib
from io import BytesIO
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from mcp import Client

from mcp_server import server


class FakeGpuMonitorClient:
    base_url = "http://127.0.0.1:8300"

    def health(self):
        return {"status": "ok", "app": "GPU Monitor"}

    def get(self, path, params=None):
        if path == "/api/auth/me":
            return {"username": "mcp_viewer", "display_name": "MCP", "role": "viewer"}
        if path == "/api/servers":
            return [
                {
                    "id": 1,
                    "name": "gpu-01",
                    "host": "10.0.0.11",
                    "port": 22,
                    "enabled": True,
                    "server_type": "gpu",
                    "status": "active",
                    "tags": ["lab"],
                },
                {
                    "id": 2,
                    "name": "cpu-01",
                    "host": "10.0.0.12",
                    "port": 22,
                    "enabled": True,
                    "server_type": "cpu",
                    "status": "active",
                    "tags": [],
                },
            ]
        if path == "/api/metrics/cluster-gpus":
            return [
                {
                    "server_id": 1,
                    "server_name": "gpu-01",
                    "hostname": "gpu-node-01",
                    "enabled": True,
                    "status": "active",
                    "tags": ["lab"],
                    "online": True,
                    "error": "",
                    "gpus": [self._gpu()],
                }
            ]
        if path == "/api/cluster/gpu-analysis":
            return {
                "total_gpus": 1,
                "idle_held_count": 0,
                "high_risk_count": 0,
                "gpus": [
                    {
                        "server_id": 1,
                        "server_name": "gpu-01",
                        "uuid": "GPU-test-1",
                        "gpu_index": 0,
                        "risk": 10,
                        "risk_label": "健康",
                        "idle_held": False,
                    }
                ],
            }
        if path == "/api/metrics/server/1/latest":
            return {
                "server_id": 1,
                "collected_at": "2026-09-01T12:00:00Z",
                "status": "ok",
                "error_code": "OK",
                "error": "",
                "hostname": "gpu-node-01",
                "gpu_driver": "580.1",
                "ssh_latency": 0.02,
                "duration": 1.2,
                "gpus": [self._gpu()],
            }
        if path == "/api/servers/1/risk":
            return {
                "server": "gpu-01",
                "gpus": [
                    {
                        "uuid": "GPU-test-1",
                        "risk": 10,
                        "risk_label": "健康",
                        "xid_events": 0,
                        "thermal_throttle_samples": 0,
                        "max_temp": 62,
                    }
                ],
            }
        if path == "/api/metrics/server/1/history":
            return [
                {
                    "time": f"2026-09-01T12:{minute:02d}:00+00:00",
                    "gpu_util": minute,
                    "gpu_mem_used_mb": 2048,
                    "gpu_mem_percent": 8,
                    "gpu_temp": 60,
                    "gpu_power": 120,
                    "gpu_clock": 1500,
                }
                for minute in range(20)
            ]
        if path == "/api/alerts/events":
            return [
                {
                    "id": 7,
                    "server_id": 1,
                    "server_name": "gpu-01",
                    "metric": "GPU_XID",
                    "rule_name": "GPU_XID",
                    "message": "Xid 79",
                    "value": 79,
                    "threshold": 0,
                    "triggered_at": "2026-09-01T12:00:00Z",
                    "recovered_at": None,
                    "acked_at": None,
                    "acked_by": "",
                    "assignee": "",
                },
                {
                    "id": 8,
                    "server_id": 1,
                    "server_name": "gpu-01",
                    "metric": "disk_percent",
                    "rule_name": "disk",
                    "message": "disk full",
                },
            ]
        raise AssertionError(f"unexpected path: {path}, params={params}")

    @staticmethod
    def _gpu():
        return {
            "index": 0,
            "uuid": "GPU-test-1",
            "name": "NVIDIA Test GPU",
            "utilization": 42,
            "util_memory": 8,
            "mem_used_mb": 2048,
            "mem_total_mb": 24576,
            "temperature": 62,
            "power_draw": 120,
            "power_limit": 300,
            "pstate": "P2",
            "ecc_supported": True,
            "ecc_uncorrected_total": 0,
            "pcie_gen_current": 4,
            "pcie_gen_max": 4,
            "pcie_width_current": 16,
            "pcie_width_max": 16,
            "processes": [
                {
                    "pid": 123,
                    "user": "alice",
                    "command": "python train.py",
                    "mem_mb": 2048,
                }
            ],
        }


class _Response:
    def __init__(self, payload):
        import json

        self.raw = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit):
        return self.raw[:limit]


class _ExpiringTokenOpener:
    """Accept only the second issued token to exercise automatic re-login."""

    def __init__(self):
        self.login_count = 0
        self.auth_headers = []

    def open(self, request, timeout):
        path = urlsplit(request.full_url).path
        if path == "/api/auth/login":
            self.login_count += 1
            self.asserted_timeout = timeout
            return _Response(
                {
                    "access_token": f"token-{self.login_count}",
                    "user": {"role": "viewer"},
                }
            )
        if path == "/api/auth/me":
            auth = request.headers.get("Authorization", "")
            self.auth_headers.append(auth)
            if auth == "Bearer token-1":
                raise HTTPError(
                    request.full_url,
                    401,
                    "expired",
                    {},
                    BytesIO(b'{"detail":"expired"}'),
                )
            return _Response({"username": "mcp_viewer", "role": "viewer"})
        raise AssertionError(f"unexpected URL: {request.full_url}")


class ApiClientTests(unittest.TestCase):
    def test_expired_jwt_logs_in_again_once(self):
        client = server.GpuMonitorClient(
            base_url="http://127.0.0.1:8300",
            username="mcp_viewer",
            password="secret",
        )
        opener = _ExpiringTokenOpener()
        client._opener = opener

        result = client.get("/api/auth/me")

        self.assertEqual(result["username"], "mcp_viewer")
        self.assertEqual(opener.login_count, 2)
        self.assertEqual(opener.auth_headers, ["Bearer token-1", "Bearer token-2"])

    def test_remote_plain_http_is_rejected_by_default(self):
        with self.assertRaisesRegex(server.GpuMonitorApiError, "remote plain HTTP"):
            server.GpuMonitorClient(
                base_url="http://10.0.0.20:8300",
                username="mcp_viewer",
                password="secret",
            )

    def test_loopback_prefix_hostname_cannot_bypass_https_requirement(self):
        with self.assertRaisesRegex(server.GpuMonitorApiError, "remote plain HTTP"):
            server.GpuMonitorClient(
                base_url="http://127.attacker.example:8300",
                username="mcp_viewer",
                password="secret",
            )

    def test_poisoned_localhost_resolution_cannot_bypass_https_requirement(self):
        answer = [
            (
                server.socket.AF_INET,
                server.socket.SOCK_STREAM,
                server.socket.IPPROTO_TCP,
                "",
                ("203.0.113.9", 0),
            )
        ]
        with mock.patch.object(server.socket, "getaddrinfo", return_value=answer):
            with self.assertRaisesRegex(server.GpuMonitorApiError, "remote plain HTTP"):
                server.GpuMonitorClient(
                    base_url="http://localhost:8300",
                    username="mcp_viewer",
                    password="secret",
                )

    def test_redirects_are_disabled_to_protect_credentials(self):
        client = server.GpuMonitorClient(
            base_url="http://127.0.0.1:8300",
            username="mcp_viewer",
            password="secret",
        )
        redirect_handlers = [
            handler
            for handler in client._opener.handlers
            if isinstance(handler, server.HTTPRedirectHandler)
        ]
        self.assertEqual(len(redirect_handlers), 1)
        self.assertIsNone(
            redirect_handlers[0].redirect_request(
                None, None, 302, "Found", {}, "https://attacker.example/"
            )
        )

    def test_login_rejects_non_viewer_account(self):
        client = server.GpuMonitorClient(
            base_url="http://127.0.0.1:8300",
            username="admin",
            password="secret",
        )
        client._opener = mock.Mock()
        client._opener.open.return_value = _Response(
            {"access_token": "admin-token", "user": {"role": "admin"}}
        )
        with self.assertRaisesRegex(server.GpuMonitorApiError, "dedicated viewer"):
            client._login()

    def test_strict_errors_do_not_expose_api_details_or_base_url(self):
        client = server.GpuMonitorClient(
            base_url="http://127.0.0.1:8300",
            username="mcp_viewer",
            password="secret",
        )
        opener = mock.Mock()
        opener.open.side_effect = HTTPError(
            "http://127.0.0.1:8300/api/private",
            500,
            "failed",
            {},
            BytesIO(b'{"detail":"database password=do-not-leak"}'),
        )
        client._opener = opener
        with mock.patch.dict(
            "os.environ", {"GPU_MONITOR_MCP_PRIVACY_MODE": "strict"}
        ):
            with self.assertRaises(server.GpuMonitorApiError) as caught:
                client._send("/api/private")
        message = str(caught.exception)
        self.assertIn("HTTP 500", message)
        self.assertNotIn("do-not-leak", message)
        self.assertNotIn("127.0.0.1", message)

        opener.open.side_effect = URLError("connect to internal-db.example failed")
        with mock.patch.dict(
            "os.environ", {"GPU_MONITOR_MCP_PRIVACY_MODE": "strict"}
        ):
            with self.assertRaises(server.GpuMonitorApiError) as caught:
                client._send("/api/private")
        self.assertNotIn("internal-db.example", str(caught.exception))

    def test_hardware_alias_is_keyed_and_stable(self):
        first_key = "first-independent-key-000000000000000000000000"
        second_key = "second-independent-key-00000000000000000000000"
        with mock.patch.dict("os.environ", {"MCP_PRIVACY_HMAC_KEY": first_key}):
            first = server._opaque_hardware_id("GPU-sensitive-uuid")
            again = server._opaque_hardware_id("GPU-sensitive-uuid")
        with mock.patch.dict("os.environ", {"MCP_PRIVACY_HMAC_KEY": second_key}):
            second = server._opaque_hardware_id("GPU-sensitive-uuid")
        self.assertEqual(first, again)
        self.assertNotEqual(first, second)
        self.assertNotEqual(first, hashlib.sha256(b"GPU-sensitive-uuid").hexdigest()[:16])


class McpServerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = mock.patch.dict(
            "os.environ",
            {
                "GPU_MONITOR_MCP_PRIVACY_MODE": "strict",
                "MCP_PRIVACY_HMAC_KEY": "test-only-privacy-key-000000000000000000000000",
            },
        )
        self.env.start()
        server._client_instance = FakeGpuMonitorClient()

    def tearDown(self):
        server._client_instance = None
        self.env.stop()

    async def test_tools_are_registered_as_read_only(self):
        async with Client(server.mcp, raise_exceptions=True) as client:
            result = await client.list_tools()
        tools = {tool.name: tool for tool in result.tools}
        self.assertEqual(
            set(tools),
            {
                "gpu_monitor_connection_status",
                "gpu_monitor_list_servers",
                "gpu_monitor_cluster_summary",
                "gpu_monitor_get_server_gpu_info",
                "gpu_monitor_get_gpu_history",
                "gpu_monitor_get_gpu_processes",
                "gpu_monitor_get_risk_analysis",
                "gpu_monitor_get_gpu_alerts",
            },
        )
        for tool in tools.values():
            self.assertTrue(tool.annotations.read_only_hint)
            self.assertFalse(tool.annotations.destructive_hint)

    async def test_server_info_round_trip(self):
        async with Client(server.mcp, raise_exceptions=True) as client:
            result = await client.call_tool(
                "gpu_monitor_get_server_gpu_info", {"server": "gpu-01"}
            )
        self.assertFalse(result.is_error)
        payload = result.structured_content
        self.assertEqual(payload["server"]["id"], 1)
        self.assertEqual(payload["gpu_count"], 1)
        self.assertNotIn("uuid", payload["gpus"][0])
        self.assertNotIn("hostname", payload["metric"])
        self.assertNotIn("error", payload["metric"])
        self.assertTrue(payload["gpus"][0]["hardware_id_hash"])
        self.assertEqual(payload["gpus"][0]["risk"]["score"], 10)

    async def test_history_is_bounded(self):
        async with Client(server.mcp, raise_exceptions=True) as client:
            result = await client.call_tool(
                "gpu_monitor_get_gpu_history",
                {"server": "1", "hours": 6, "max_points": 10},
            )
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["point_count"], 10)

    async def test_gpu_alert_filter_excludes_non_gpu_events(self):
        async with Client(server.mcp, raise_exceptions=True) as client:
            result = await client.call_tool("gpu_monitor_get_gpu_alerts", {})
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["count"], 1)
        self.assertEqual(result.structured_content["events"][0]["metric"], "GPU_XID")


if __name__ == "__main__":
    unittest.main()
