# GPU Monitor MCP Server

这是 GPU Monitor 的只读 MCP 接口。它不重复执行 SSH 或 `nvidia-smi`，而是使用专用
viewer 账号登录现有 FastAPI 服务，并读取平台已经采集、缓存和分析好的 GPU 数据。

登录 GPU Monitor 后也可直接访问系统内的 `/help` 页面查看图形化接入指南。

默认使用本地 `stdio` 传输，不新增网络监听端口。服务器不会返回 SSH 用户名、密码、
私钥、BMC 用户名或 BMC 密码，也没有刷新采集、进程操作、告警确认等写工具。

## 工具

| 工具 | 用途 |
|---|---|
| `gpu_monitor_connection_status` | 检查 API 连通性和 viewer 登录 |
| `gpu_monitor_list_servers` | 列出 GPU 服务器及当前汇总状态 |
| `gpu_monitor_cluster_summary` | 集群 GPU、显存、温度、功耗和风险概览 |
| `gpu_monitor_get_server_gpu_info` | 单台服务器的 GPU/ECC/PCIe/进程/风险明细 |
| `gpu_monitor_get_gpu_history` | 1-168 小时 GPU 趋势 |
| `gpu_monitor_get_gpu_processes` | 当前 GPU 计算进程及显存占用 |
| `gpu_monitor_get_risk_analysis` | GPU 风险和空占显存分析 |
| `gpu_monitor_get_gpu_alerts` | GPU/XID/ECC/PCIe 告警事件 |

所有工具都声明了 MCP `readOnlyHint`，且不会修改平台状态。

## 安装

MCP SDK v2 要求 Pydantic 2.12+，而 Web 后端目前固定在 Pydantic 2.10.x，因此 MCP
使用独立虚拟环境，避免改变正在运行的服务依赖：

```bash
cd /home/xusheng/workspace/gpu_monitor
python3 -m venv .venv-mcp
.venv-mcp/bin/pip install -r mcp_server/requirements.txt
```

在 GPU Monitor 中创建一个 `viewer` 用户，例如 `mcp_viewer`。不要给 MCP 使用管理员
账号。随后由 MCP 宿主向进程传入：

```text
GPU_MONITOR_URL=http://127.0.0.1:8300
GPU_MONITOR_USERNAME=mcp_viewer
GPU_MONITOR_PASSWORD=<viewer 用户密码>
```

可选变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `GPU_MONITOR_TIMEOUT` | `15` | API 超时秒数，最大 120 |
| `GPU_MONITOR_VERIFY_TLS` | `yes` | HTTPS 证书校验；不建议关闭 |
| `GPU_MONITOR_ALLOW_INSECURE_HTTP` | `no` | 是否允许向非本机 HTTP 地址发送登录凭据 |

## MCP 宿主配置

不同宿主的配置文件位置不同，但启动参数相同。通用配置示例：

```json
{
  "mcpServers": {
    "gpu-monitor": {
      "command": "/home/xusheng/workspace/gpu_monitor/.venv-mcp/bin/python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/home/xusheng/workspace/gpu_monitor",
      "env": {
        "GPU_MONITOR_URL": "http://127.0.0.1:8300",
        "GPU_MONITOR_USERNAME": "mcp_viewer",
        "GPU_MONITOR_PASSWORD": "替换为 viewer 密码"
      }
    }
  }
}
```

手工执行 `python -m mcp_server.server` 后没有普通终端输出是正常现象：stdio
服务器正在等待 MCP 宿主通过标准输入发送协议消息，标准输出仅用于 MCP 帧。

非本机部署建议使用 HTTPS。出于凭据安全考虑，非本机明文 HTTP 默认会被拒绝。

## 测试

测试使用假 GPU Monitor API 数据，不访问生产数据库或真实被监控服务器：

```bash
.venv-mcp/bin/python -m unittest discover -s mcp_server/tests -v
```
