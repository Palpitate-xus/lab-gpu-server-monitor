# GPU 服务器监控平台

[中文](README.md) | [English](README.en.md)

基于 **Vue 3 + Element Plus + ECharts + FastAPI + SSH** 的多服务器监控 Docker 应用，
**Agentless 架构**（服务器端零常驻 Agent、零监听端口），指标覆盖对标 **btop** 并扩展
GPU 数据中心级健康监控（XID / ECC / PCIe / NVMe / RAID / 内核事件 / 风险预测）。

```text
                ┌────────────────┐
                │ Central Server │  FastAPI + Scheduler + MySQL
                └───────┬────────┘
                        │ SSH（key/password, TOFU hostkey）
         ┌──────────────┼──────────────┐
         ▼              ▼              ▼
     GPU Server 1   GPU Server 2   GPU Server N
     只读命令白名单 · LC_ALL=C · 输出限流 · 无落地文件
         │
    ==SECTION== 分隔协议（stdout）
         ▼
   Parse → MySQL → Dashboard/Alerts/Detectors
```

## 采集分层

| 层 | 频率 | 内容 |
|---|---|---|
| **fast** | 每轮（默认 30-60s） | CPU（含 iowait/每核）、内存（HugePages）、磁盘空间+inode、每设备 IO、NIC 速率/错误/丢包/链路状态、GPU 全量（利用率/显存/温度/显存温度/功耗/频率/pstate/**降频原因/ECC/PCIe 链路/retired pages**/计算进程资源）、脱敏进程资源、TCP/fd；不持久化登录用户、进程用户名或完整命令行 |
| **kernel** | 每轮 | `journalctl -k` 增量 → **Xid / OOM / MCE / EDAC / PCIe AER / IO / NVMe / NFS / NIC reset** 事件（boot_id+hash 去重入库） |
| **slow** | 每 5 分钟 | **NVMe SMART**（温度/备用空间/寿命/介质错误/意外断电）、mdraid 状态、NFS 挂载、systemd failed、关键服务（sshd/docker/kubelet/slurmd/nvidia-persistenced）、**MIG**、NVLink、IPMI/BMC 传感器 |
| **inventory** | 每 24 小时 | machine-id、DMI/BIOS/序列号、lscpu、**NUMA 拓扑（节点 CPU/内存）**、`nvidia-smi topo -m`、PCI 设备 NUMA 归属、磁盘/网卡清单（serial/MAC 稳定 ID）、InfiniBand、NTP 时间同步状态 |

## 内置健康检测器（13 个，非用户规则）

`GPU_IDLE_VRAM_HELD`（空占/僵尸进程：显存>30% 且利用率≈0 持续 30 分钟）、
`GPU_MISSING`（GPU UUID 基线对比——掉卡检测）、`GPU_ECC_UNCORRECTED`、`GPU_XID`、
`GPU_THERMAL_THROTTLE`、`NVME_HEALTH`、`RAID_DEGRADED`、`HOSTKEY_CHANGED`、
`SSH_FAULT`（区分 AUTH/DNS/REFUSED/TIMEOUT/HOSTKEY 而非统一 Offline）、
`NFS_STALE`、`SERVICE_FAILED`、`OOM_KILL`、`STORAGE_BOTTLENECK`
（关联诊断：GPU 利用率骤降 + iowait 升高 + 磁盘繁忙 → 疑似存储瓶颈）。

**GPU 风险评分**（0-100，24h 窗口）：Xid 事件 ×20、不可纠正 ECC ×5、热降频、
高温、PCIe 链路降级加权；≥60 高危 / ≥30 关注。GPU 以 **UUID 为唯一标识**，
基线自动记录新增/消失。

## 安全架构

### 密钥与凭据
- JWT、SSH/BMC/MFA 密文、归档分别使用 `JWT_SIGNING_KEY`、
  `CREDENTIAL_ENCRYPTION_KEYS`、`ARCHIVE_ENCRYPTION_KEY`，启动时拒绝空值、公开占位值和密钥复用。
- `CREDENTIAL_ENCRYPTION_KEYS` 是有序 keyring：首个密钥加密、其余密钥仅解密；使用
  `scripts/rotate_credentials.py` 可在不中断旧密文读取的情况下完成轮换。
- **SSH/BMC/MFA 凭据**使用 Fernet 认证加密保存；建议专用 `gpumon` 用户 + ED25519 key +
  `authorized_keys` 限制（`no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty`）
- 登录密码使用 bcrypt，新增/修改密码至少 15 位；首次管理员密码至少 16 位且没有默认值。
- 指标归档使用独立 AES-256-GCM 密钥加密，目录/文件权限固定为 0700/0600。

### 认证与访问
- 管理员默认强制绑定并验证 TOTP MFA；未完成绑定时，所有管理员权限接口都拒绝访问。
- 浏览器令牌只放在 `Secure + HttpOnly + SameSite` Cookie；写请求使用双提交 CSRF 校验，
  不再把 JWT 保存到 localStorage。
- JWT 同时绑定不可复用的 `auth_id` 与持久化 `token_version`；登出、改密、改角色、禁用、
  删除用户后，旧令牌跨进程重启仍立即失效。
- 登录限制为每 IP/账号组合 5 次、每 IP 20 次失败后延迟 10 分钟；状态存储有硬容量上限，
  不使用可被远程攻击者全局锁死的“按用户名”锁。
- API 文档端点固定关闭；所有 API 禁止缓存，并启用 CSP、HSTS、frame/object 隔离等安全头。
- Webhook 仅允许 HTTPS 公网目标，DNS 校验后的地址会固定到实际 TLS 连接，证书仍按原域名验证，
  且不跟随重定向。
- 容器 UID 10001 非 root、只读根文件系统、删除全部 capabilities，并限制 CPU/内存/PID/日志。
- **CORS 默认关闭**（同源部署，SPA 与 API 同源）；跨域部署需显式配置
  `CORS_ORIGINS` 白名单；只有来自 `TRUSTED_PROXY_CIDRS` 的代理头才会被信任。
- Viewer 看不到主机/BMC 管理地址、凭据状态、完整 IPMI/资产或进程身份；完整实时进程仅管理员可见。
- 远程 kill/renice 默认关闭；显式启用后仍要求管理员 MFA 和当前密码再次认证。

### 采集安全
- **Host Key 校验**：TOFU 首次指纹以原子、不可覆盖方式写入 0600 文件；持久化失败会中止连接，
  指纹变化立即拒绝并告警。管理员核对服务器重装后的新指纹，才能重置信任。
- 默认拒绝 root SSH，采集统一使用专用低权限 `gpumon` 账户。
- **命令白名单**：采集命令全部内置固定模板，前端/用户**不可能**注入 shell
- **服务器端零残留**：脚本经 stdin（`bash -s`）执行，不落盘、无后台进程
- **输出限流**：单采集器 2MB 上限，`LC_ALL=C` 固定 locale
- **最小 sudo**：全部指标无需 root；仅 `nvme smart-log`/`ipmitool`/`journalctl`
  建议按需放开（sudoers 白名单单条命令）

## 平台功能

- **登录/用户管理**：JWT、admin/viewer 角色、改密（改密后自动续发当前会话令牌）、禁用、审计日志
- **服务器管理**：密码 或 SSH 私钥(+口令) 认证，测试连接；
  GPU / CPU 服务器类型——CPU 服务器跳过所有 GPU 面板与聚合
- **服务器生命周期**：`运行中 / 维护中 / 已排空 / 返修中` 状态机——维护中的机器
  静默全部检测器与规则告警、排除出集群健康统计；可设到期时间自动恢复；
  每次状态变更与手工记录写入**故障台账**（详情页「台账」标签）
- **标签分组**：服务器多标签（机柜/集群/团队/型号），列表与报表按标签筛选
- **进程操作（admin）**：实时进程表（15s 刷新、排序、过滤）；kill/renice 默认关闭，
  启用后逐次要求 MFA 会话与密码再认证
- **告警**：用户规则（9 指标）+ 内置检测器事件流；**确认（ack）与恢复分离**——
  确认只是认领静默，条件消除后自动恢复；支持手动关闭（resolve）、认领（assign）；
  点事件（Xid/OOM/MCE）1 小时 TTL 自动关闭；**检测器事件同样推送通知**
- **多通道通知**：多个 Webhook 目标，各自模板与最低严重度过滤（info/warning/critical）
- **驾驶舱**：集群健康条（点击下钻）、GPU 矩阵热图（可按 服务器/利用率/显存/温度 排序）、集群趋势、实时告警跑马灯
- **服务器详情**：健康模型树（连通性/CPU/内存/文件系统/网络/GPU/内核事件）、
  btop 核心网格、GPU 卡片（ECC/PCIe/降频/风险标签）、内核事件流、
  NVMe/RAID/NFS、服务/MIG/IPMI、资产/NUMA 拓扑、**台账、采集健康**标签页
- **GPU 分析**：集群级空占检测（僵尸显存）与故障风险排行
- **利用率报表**：按服务器/标签的卡时、平均利用率、空占卡时与占比、功耗，
  基于小时级降采样聚合表，支持 CSV 导出
- **公开状态页**（Uptime Kuma 风格，`/status` 免登录）：整体健康横幅、
  每台服务器可用率条形图（7-90 天）+ SSH 延迟 + **每张 GPU 的环形利用率仪表**；
  管理员可配置发布开关、标题、展示机器、时间窗、主题（跟随访客/强制深浅色）
- **采集健康**：每服务器 24h 采集成功率、SSH 延迟、错误码分布
- **历史数据**：可配保留天数（0=永久），小时级预聚合支撑长周期趋势与报表；
  原始数据长窗口查询自动降采样
- **检测阈值可配置**：空占显存/时长、健康树 CPU/内存/磁盘阈值在设置页调整
- **深色/浅色主题**：跟随系统自动切换 + 手动三态
- **在线迁移**：MySQL/SQLite 双方言幂等迁移（migrations/，按方言自动选择）

## MCP 接入

仓库包含一个只读 MCP Server，可让 Codex、Claude Desktop、Cursor 等 MCP 宿主查询
集群 GPU 状态、单机 GPU/ECC/PCIe 明细、历史趋势、计算进程、风险评分和告警。
它复用现有 REST API 与 viewer 权限，不直接接触 SSH/数据库凭据，也不提供任何写操作。

安装、账号和宿主配置见 **[GPU Monitor MCP Server](mcp_server/README.md)**。

## 快速开始

详细步骤见 **[部署指南 / Deployment Guide](DEPLOYMENT.md)**（[English](DEPLOYMENT.en.md)）。

```bash
cp .env.example .env
chmod 600 .env
# 为三个密钥分别执行一次，并填写 .env；不要复用输出
openssl rand -hex 32
# 填写首次管理员、归档和数据库配置后，先执行 DEPLOYMENT.md 中的独立迁移步骤
export GPU_MONITOR_IMAGE="gpu-monitor:$(git rev-parse --short=12 HEAD)"
docker compose up -d --build
```

Compose 只监听 `127.0.0.1:8300`。浏览器必须通过受控 HTTPS 反向代理访问；系统没有默认
管理员账号或密码。首次管理员登录后会被强制引导绑定 TOTP MFA，完成前不能执行管理操作。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| JWT_SIGNING_KEY | 无 | JWT 专用随机密钥，至少 32 字符 |
| CREDENTIAL_ENCRYPTION_KEYS | 无 | 凭据 keyring，格式为 `当前密钥,旧密钥` |
| ARCHIVE_ENCRYPTION_KEY | 无 | 归档 AES-256-GCM 密钥，必须是 64 位十六进制 |
| INIT_ADMIN_USERNAME / PASSWORD | 无 | 仅空库首次启动使用；密码 16–72 位 |
| DATABASE_URL / DATABASE_SSL_CA | SQLite / 无 | 非环回 MySQL 强制配置 CA 与最小权限运行账号 |
| REDIS_URL / REDIS_SSL_CA | 无 | 可选缓存；非环回 Redis 强制 `rediss://`、认证和证书校验 |
| REQUIRE_ADMIN_MFA | yes | 管理员权限默认要求 TOTP MFA |
| REMOTE_PROCESS_CONTROL_ENABLED | no | 是否启用远程进程操作；即使启用仍需再认证 |
| POLL_INTERVAL_SECONDS | 60 | 采集间隔（设置页可在线改） |

系统设置页还可配置：数据保留天数（0=永久）、Webhook URL 与消息模板。Webhook URL 会加密
保存且不会通过管理 API 回显完整令牌。

## 目录结构

```
├── Dockerfile / Dockerfile.multistage / docker-compose.yml
├── backend/
│   ├── migrations/               # SQL 迁移（由短期 DDL 账号显式执行）
│   └── app/
│       ├── main.py               # FastAPI + SPA 托管 + 安全启动检查
│       ├── remote_scripts.py     # fast/slow/inventory/kernel 四套远程脚本
│       ├── ssh_transport.py      # SSH 传输：TOFU hostkey、故障分类、stdin 执行
│       ├── ssh_collector.py      # fast 层解析
│       ├── collectors_extra.py   # slow/inventory/kernel 解析
│       ├── health.py             # 13 内置检测器 + GPU 风险评分 + 健康树
│       ├── scheduler.py          # 分层调度（fast 每轮/slow 5min/inv 24h）
│       ├── notifier.py           # Webhook 通知
│       ├── migrate.py            # 迁移执行器（MySQL/SQLite 双方言）
│       └── api/                  # auth/users/servers/metrics/alerts/cockpit/enterprise
└── frontend/src/views/           # Login/Dashboard/Servers/ServerDetail/Users/Alerts/Settings/Cockpit
```
