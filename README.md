# GPU 服务器监控平台

基于 **Vue 3 + Element Plus + ECharts + FastAPI + SSH** 的多服务器监控 Docker 应用，
指标覆盖对标 **btop**，历史数据永久入库（可配保留期）。

## 功能总览

### 监控采集（单次 SSH 连接、一个 POSIX 脚本、1 秒采样窗口）
- **CPU**：型号、核数、总使用率、**每核使用率/频率/温度**（btop 网格）、封装温度、1/5/15 负载
- **内存**：总量/已用/可用/缓存 buff/cache（含 `MemAvailable` 修正）、Swap
- **磁盘**：每分区容量用量 + **每设备 IO 速率（读/写 BPS、IOPS、繁忙度 %）**（/proc/diskstats 差分）
- **网络**：每接口实时上下行速率（/proc/net/dev 差分）
- **GPU**：`nvidia-smi` — 利用率、显存、温度、功耗、风扇、驱动、**核心/显存频率(当前/最大)、pstate、
  编解码会话数、compute mode**、每卡计算进程（PID/用户/显存/命令行）；旧驱动自动降级字段
- **进程**：全量进程表（PID/PPID/用户/CPU/内存/RSS/VSZ/状态/运行时长/完整命令行）
- **系统**：主机名、发行版、内核、运行时长、登录用户（who）

### 平台功能
- **登录/用户管理**：JWT、admin/viewer 角色、改密、禁用、审计日志
- **服务器管理**：密码 或 SSH 私钥(+口令) 认证，凭据 Fernet 加密，测试连接
- **进程操作（admin）**：实时进程表（15s 自动刷新、CPU/内存/时长排序、关键字过滤）、**kill（可选信号）/ renice**
- **告警**：9 种指标规则（CPU/内存/Swap/磁盘/每核负载/GPU 利用率/温度/显存/功耗），
  支持 > >= < <=、持续时长、全部或指定服务器；事件流 + 恢复记录 + 手动确认；**Webhook 通知**（可配模板，兼容企业微信/钉钉/飞书）
- **历史数据**：全部指标永久保存（retention_days=0），趋势图 1/3/6/24h（CPU/内存/GPU 利用率/显存/温度/功耗/负载/网络速率）
- **在线迁移**：SQLite schema 自动升级（migrations/ 目录，幂等）

## 快速开始

```bash
# 前端构建（docker hub 不通时的流程；网络可用可直接用 Dockerfile.multistage）
cd frontend && pnpm install && pnpm build && cd ..
docker compose up -d --build
```

访问 `http://<host>:8300`，默认 `admin / admin123`（**请立即修改**）。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| SECRET_KEY | change-me | JWT 签名 + 凭据加密（**务必修改**；改后已存凭据失效） |
| INIT_ADMIN_USERNAME / PASSWORD | admin/admin123 | 首次启动创建的管理员 |
| POLL_INTERVAL_SECONDS | 60 | 采集间隔（设置页可在线改） |

系统设置页还可配置：数据保留天数（0=永久）、Webhook URL 与消息模板。

## 目录结构

```
├── Dockerfile / Dockerfile.multistage / docker-compose.yml
├── backend/
│   ├── migrations/           # SQL 迁移（幂等，自动执行）
│   └── app/
│       ├── main.py           # FastAPI + SPA 托管 + 迁移
│       ├── ssh_collector.py  # 采集脚本与解析（含单测验证过的解析器）
│       ├── scheduler.py      # 轮询 + 告警评估 + 保留期清理
│       ├── notifier.py       # Webhook 通知
│       ├── migrate.py        # 迁移执行器
│       └── api/              # auth / users / servers / metrics / alerts
└── frontend/src/views/       # Login/Dashboard/Servers/ServerDetail/Users/Alerts/Settings
```

## 安全说明

- SSH 凭据 Fernet 加密存储；进程 kill/renice、服务器增删、用户管理、规则、设置均需 admin
- viewer 角色只读（可看指标、进程、告警）
- 所有敏感操作写入审计日志（可在设置页查看）
