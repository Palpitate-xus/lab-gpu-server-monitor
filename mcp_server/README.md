# GPU Monitor MCP Server

这是 GPU Monitor 的只读 MCP 接口。它使用专用 Viewer 登录已有 FastAPI 服务，只读取
平台已采集的数据；不会直接连接 MySQL、SSH 或 BMC，也没有刷新、进程操作、告警确认、
配置修改等写工具。系统内 `/help` 页面提供同一份图形化接入说明。

## 工具

| 工具 | 用途 |
|---|---|
| `gpu_monitor_connection_status` | 检查 API 连通性和 Viewer 鉴权 |
| `gpu_monitor_list_servers` | 列出 GPU 服务器及当前汇总状态 |
| `gpu_monitor_cluster_summary` | 集群 GPU、显存、温度、功耗和风险概览 |
| `gpu_monitor_get_server_gpu_info` | 单机 GPU/ECC/PCIe/进程资源/风险明细 |
| `gpu_monitor_get_gpu_history` | 1–168 小时 GPU 趋势 |
| `gpu_monitor_get_gpu_processes` | 历史快照中的 PID 与 GPU 显存占用 |
| `gpu_monitor_get_risk_analysis` | GPU 风险和空占显存分析 |
| `gpu_monitor_get_gpu_alerts` | GPU/XID/ECC/PCIe 告警事件 |

所有工具都声明 MCP `readOnlyHint`，服务只使用 HTTP GET 读取业务数据；唯一 POST 是登录换取
两小时 Viewer Token，过期后最多自动重新登录一次。

## 安装

使用独立虚拟环境并安装带哈希的完整锁文件：

```bash
cd /home/xusheng/workspace/gpu_monitor
python3 -m venv .venv-mcp
.venv-mcp/bin/pip install --require-hashes -r mcp_server/requirements.lock
```

在 GPU Monitor「用户管理」中创建专用 `viewer`（例如 `mcp_viewer`）。服务会拒绝管理员账号，
避免配置失误扩大权限。

## MCP 宿主配置

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
        "GPU_MONITOR_PASSWORD": "替换为 Viewer 随机密码",
        "GPU_MONITOR_MCP_PRIVACY_MODE": "strict",
        "MCP_PRIVACY_HMAC_KEY": "替换为另一个独立随机值（至少32字符）"
      }
    }
  }
}
```

| 变量 | 默认值 | 说明 |
|---|---|---|
| `GPU_MONITOR_URL` | `http://127.0.0.1:8300` | 仅允许根地址，不允许 URL 用户信息、路径、查询或 fragment |
| `GPU_MONITOR_USERNAME` | 无 | 必须是专用 Viewer |
| `GPU_MONITOR_PASSWORD` | 无 | 只放在 MCP 宿主的本地秘密配置中 |
| `GPU_MONITOR_TIMEOUT` | `15` | API 超时秒数，范围 `(0, 120]` |
| `GPU_MONITOR_MCP_PRIVACY_MODE` | `strict` | `strict` 或显式选择 `extended` |
| `MCP_PRIVACY_HMAC_KEY` | 无 | strict 模式必填；独立随机值，不能与登录/JWT/归档密钥复用 |

安全约束不可用环境变量关闭：

- 只有经实际解析仍全部为环回地址的 `localhost`、`127.0.0.0/8`、`::1` 可使用 HTTP；
- 所有远程地址必须使用 HTTPS；
- HTTPS 始终校验证书链和主机名，没有“跳过证书校验”开关；
- URL 中嵌入的账号密码会被拒绝；本机请求不会误走 HTTP 代理；
- API 重定向一律拒绝，登录表单与 Bearer Token 不会转发到其它地址。

## 隐私模式

默认 `strict` 不向模型返回真实 GPU UUID/序列号/PCI 地址、主机名、管理地址、原始连接错误、
标签、账号显示名、进程用户或命令行。需要关联 GPU 时返回由独立部署密钥生成的截断 HMAC 标识；进程仅含 PID
和资源占用。后端 Viewer DTO 还会额外移除主机/BMC 管理信息。

`extended` 仅适合已经批准模型供应商、数据地域、保留策略和人员访问范围的环境。它可返回
更多硬件/运维元数据，但仍拿不到 SSH/BMC 凭据、完整实时进程或任何写权限。

服务器参数使用 ID、精确名称或唯一名称片段；Viewer 无法按隐藏的主机地址检索。

## 测试

```bash
.venv-mcp/bin/python -m pytest -q mcp_server/tests
.venv-mcp/bin/pip-audit -r mcp_server/requirements.lock --disable-pip --no-deps
```

测试使用假的 API 数据，不访问生产数据库或真实服务器。手工运行
`python -m mcp_server.server` 后没有普通终端输出是正常现象：stdio 正在等待 MCP 协议帧。
