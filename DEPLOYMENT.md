# 部署指南 / Deployment Guide

[中文](DEPLOYMENT.md) | [English](DEPLOYMENT.en.md)

---

## 架构一览

```text
┌────────────────────────────── 监控中心（你部署 Docker 的机器） ──────────────────────────────┐
│  gpu-monitor 容器 (FastAPI + 调度器 + 前端静态文件)  ──→  MySQL (gpu_monitor 库)             │
└──────────────┬───────────────────────────────────────────────────────────────────────────┘
               │ SSH 出站连接 (22 或自定义端口)
     ┌─────────┼─────────┐
     ▼         ▼         ▼
  GPU 服务器  GPU 服务器  CPU 服务器     ← 被监控端：无需安装任何 Agent
```

被监控服务器**只需要**：开 SSH、有一个可登录账号。所有指标经 SSH 以只读命令采集，
脚本从 stdin 执行、不落盘（详见 README「采集安全」）。

---

## 一、准备

### 1. 监控中心机

| 需求 | 说明 |
|---|---|
| Docker + Docker Compose | v2 (`docker compose`) |
| 8300 端口（可改） | Web UI 与 API |
| 出站 SSH 可达各被监控机 | 22 或自定义端口 |

### 2. 数据库（MySQL）

已有 MySQL 8.x 实例就直接用；没有就起一个：

```bash
docker run -d --name docker-mysql-1 \
  -e MYSQL_ROOT_PASSWORD=<root密码> \
  -e MYSQL_DATABASE=gpu_monitor \
  -e MYSQL_USER=gpumon \
  -e MYSQL_PASSWORD=<gpumon密码> \
  -p 3306:3306 mysql:8.0.39
```

表结构由应用迁移自动创建（`migrations/`，幂等，启动时自动执行），**不需要手工建表**。

> 不想用 MySQL？在 `.env` 里设 `DATABASE_URL=sqlite:///./data/gpu_monitor.db`，
> 数据落在挂载卷 `./data` 里，零外部依赖。

### 3. 被监控 GPU 服务器

- 确保 `nvidia-smi` 可用（驱动正常）
- 建议专用低权账号（示例）：

```bash
# 在被监控机上创建监控账号
sudo useradd -m monitor
sudo passwd monitor            # 或配置 SSH key
```

可选加固（强烈建议）：`authorized_keys` 里限制 key 的能力：

```
restrict,no-port-forwarding,no-agent-forwarding,no-X11-forwarding ssh-ed25519 AAAA... monitor@central
```

全部指标均无需 root；仅 `nvme smart-log` / `ipmitool` / `journalctl` 需要 sudo 时，
按单条命令放开（示例见 README「最小 sudo」）。

---

## 二、部署监控中心

### 1. 克隆仓库

```bash
git clone https://github.com/Palpitate-xus/lab-gpu-server-monitor.git
cd lab-gpu-server-monitor
```

### 2. 配置密钥（必做）

```bash
cp .env.example .env 2>/dev/null || true
# 手动生成密钥写入 .env：
openssl rand -hex 32   # 输出写入 .env 的 SECRET_KEY=
```

`.env`（已被 gitignore，绝不提交）：

```ini
SECRET_KEY=<openssl rand -hex 32 的输出>
DATABASE_URL=mysql+pymysql://gpumon:<gpumon密码>@<MySQL主机>:3306/gpu_monitor?charset=utf8mb4
```

- MySQL 跑在同机 Docker：主机填 `172.17.0.1`（Docker 网桥网关）
- **SECRET_KEY 用来加密 SSH 凭据 + 签发 JWT；丢了/换了，已录入的服务器凭据作废重录**

### 3. 构建前端（本仓库默认流程）

```bash
cd frontend && pnpm install && pnpm build && cd ..
```

> 本仓库的默认 Dockerfile 假定宿主机先构建好 `frontend/dist`（作者的机器拉不到
> Docker Hub 的 node 镜像）。网络通畅时可用一键构建：
>
> ```bash
> docker build -f Dockerfile.multistage -t gpu-monitor:latest .
> ```
>
> 然后在 `docker-compose.yml` 里把 `build: .` 换成 `image: gpu-monitor:latest`。

### 4. 启动

```bash
docker compose up -d --build
```

首次启动自动：建表 → 创建管理员（`INIT_ADMIN_USERNAME/PASSWORD`，默认 `admin/admin123`）→
启动采集调度器。

### 5. 验证

```bash
curl http://127.0.0.1:8300/api/health        # {"status":"ok",...}
```

浏览器打开 `http://<监控中心IP>:8300`，默认 `admin / admin123`——**登录后立即改密**。

---

## 三、添加服务器

1. 登录 → 「服务器」→「添加服务器」
2. 填名称 / IP / SSH 端口 / 认证方式（密码或私钥+口令）
3. **选类型：GPU 服务器 / CPU 服务器**（CPU 服务器不显示 GPU 面板与聚合）
4. 「测试连接」通过后保存

首次连接采用 **TOFU**：指纹自动记录到 `data/known_hosts/`；日后指纹变化会立即
告警并停止采集（防中间人）。确认是重装系统后，在服务器详情页「重置 Host Key」。

数据 30-60 秒内出现在驾驶舱。

---

## 四、升级

```bash
git pull
cd frontend && pnpm install && pnpm build && cd ..
docker compose up -d --build
```

迁移自动执行（幂等），数据不丢。

---

## 五、运维要点

| 事项 | 说明 |
|---|---|
| 数据保留 | 设置页可配保留天数；0 = 永久 |
| 备份 | 备份 MySQL `gpu_monitor` 库（或 SQLite 文件）+ `./data/known_hosts/` |
| 日志 | `docker logs -f gpu-monitor` |
| 改端口 | `docker-compose.yml` 的 `ports: - "8300:8000"` 改左侧 |
| 反向代理 | 可挂 Nginx/Caddy 提供 HTTPS；此时 `.env` 加 `TRUST_PROXY=yes`（限速才认 X-Forwarded-For） |
| 跨域访问 | 默认同源；需跨域时 `.env` 配 `CORS_ORIGINS=https://xxx` 白名单 |
| 密钥轮换 | 换 `SECRET_KEY` 后所有 SSH 凭据需重新录入（页面会提示 `CRED_DECRYPT_FAILED`） |

---

## 六、常见问题

**Q: 添加服务器后一直 SSH 不可达？**
检查网络/端口/防火墙；错误码会区分 认证失败 / DNS / 拒绝 / 超时，按提示处理。

**Q: GPU 卡片显示"未检测到 GPU"？**
被监控机 `nvidia-smi` 能跑才有数据；CPU 服务器请在添加时选「CPU 服务器」类型。

**Q: 忘记 admin 密码？**
`.env` 设 `INIT_ADMIN_USERNAME/PASSWORD` 后删库重建用户，或直接改 MySQL users 表
（密码 bcrypt）。最简单：备份后 `docker compose down`，清空数据库重来
（管理员只在空库时创建）。

**Q: 登录提示"尝试次数过多已锁定"？**
同 IP/用户名 5 次失败锁 10 分钟，等 10 分钟或重启容器（内存锁）。

**Q: 想让监控走非 22 端口？**
添加服务器时「端口」填实际端口（如 23333）即可。
