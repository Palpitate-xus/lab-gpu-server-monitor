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
| **fast** | 每轮（默认 30-60s） | CPU（含 iowait/每核）、内存（HugePages）、磁盘空间+inode、每设备 IO、NIC 速率/错误/丢包/链路状态、GPU 全量（利用率/显存/温度/显存温度/功耗/频率/pstate/**降频原因/ECC/PCIe 链路/retired pages**/计算进程）、进程表、登录用户、TCP/fd |
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
- **SECRET_KEY 只存 `.env`（已 gitignore）**，compose 通过 `env_file` 注入；
  **轮换密钥会使已存 SSH 凭据不可解密**（错误码 `CRED_DECRYPT_FAILED`），
  需在服务器管理页重新录入——这是设计特性，防止旧密文被旧密钥解开
- **SSH 凭据**：Fernet 加密存储（AES-128-CBC+HMAC，密钥由 SECRET_KEY 派生）；
  建议专用 `monitor` 用户 + ED25519 key +
  `authorized_keys` 限制（`no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty`）
- **登录密码**：bcrypt cost=12

### 认证与访问
- **登录速率限制**：同用户名 5 次 / 同 IP 10 次失败锁 10 分钟（429 + 剩余时间），
  登录页按钮显示锁定倒计时；成功登录清零；失败尝试写审计日志
- **JWT 有效期 2 小时 + 吊销机制**（jti）：改密 / 禁用 / 删除用户即作废其全部存量 token
- **API 文档默认关闭**（`/docs` `/redoc` `/openapi.json`），需要时设 `DOCS_ENABLED=yes`
- **安全响应头**：CSP / X-Frame-Options DENY / nosniff / Referrer-Policy / Permissions-Policy / HSTS
- **Webhook SSRF 防护**：仅 https、解析后拒私网/环回/链路本地地址、拒绝重定向，保存时即校验
- **容器非 root 运行**（appuser, uid 10001）+ HEALTHCHECK
- 401 自动登出前端
- **CORS 默认关闭**（同源部署，SPA 与 API 同源）；跨域部署需显式配置
  `CORS_ORIGINS` 白名单；反代场景设 `TRUST_PROXY=yes` 才信任 X-Forwarded-For
- 进程 kill/renice、服务器增删、用户管理、规则、设置均需 admin；viewer 只读；
  敏感操作全部审计日志

### 采集安全
- **Host Key 校验**：TOFU（首次信任并记录），密钥变化立即中止并告警（防 MITM）；
  管理员确认服务器重装后可一键重置
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
- **进程操作（admin）**：实时进程表（15s 刷新、排序、过滤）、kill/renice
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
# 前端构建（docker hub 不通时的流程；网络可用可直接用 Dockerfile.multistage）
cd frontend && pnpm install && pnpm build && cd ..
docker compose up -d --build
```

访问 `http://<host>:8300`，默认 `admin / admin123`（**请立即修改**；登录页仅开发模式显示默认口令）。

**注意**：`SECRET_KEY` 未配置或仍为默认值时**应用拒绝启动**（防止可伪造管理员令牌与
凭据解密）；生成示例：`python3 -c 'import secrets;print(secrets.token_urlsafe(48))'`。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| SECRET_KEY | change-me | JWT 签名 + 凭据加密（**务必修改**；改后已存凭据失效） |
| INIT_ADMIN_USERNAME / PASSWORD | admin/admin123 | 首次启动创建的管理员 |
| DOCS_ENABLED | no | 设 yes 开放 /docs /redoc /openapi.json（默认关闭防探测） |
| POLL_INTERVAL_SECONDS | 60 | 采集间隔（设置页可在线改） |

系统设置页还可配置：数据保留天数（0=永久）、Webhook URL 与消息模板。

## 目录结构

```
├── Dockerfile / Dockerfile.multistage / docker-compose.yml
├── backend/
│   ├── migrations/               # SQL 迁移（幂等，自动执行）
│   └── app/
│       ├── main.py               # FastAPI + SPA 托管 + 迁移
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
