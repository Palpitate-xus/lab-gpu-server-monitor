# GPU Monitor 安全部署指南

[中文](DEPLOYMENT.md) | [English](DEPLOYMENT.en.md)

本指南面向正式环境。完整整改背景和升级注意事项见
[安全上线操作手册](SECURITY_HARDENING.md)。

## 1. 部署边界

```text
用户 ──HTTPS──> Nginx/受控网关 ──127.0.0.1:8300──> GPU Monitor
                                                   ├──TLS/Unix socket──> MySQL
                                                   ├──SSH──> 被监控服务器
                                                   └──IPMI lanplus──> BMC
```

- Compose 只把应用发布到 `127.0.0.1`，8300 不应直接暴露到局域网或公网。
- 非环回 MySQL 必须启用 TLS；3306 不应公开发布。
- 被监控端无需 Agent，但必须使用专用低权限 `gpumon` 账号；默认拒绝 root SSH。
- 正式环境必须通过 HTTPS 使用浏览器，`COOKIE_SECURE=yes`。

## 2. 前置条件

- Docker Engine 与 Docker Compose v2；
- 一个 HTTPS 域名和可信证书；
- 监控中心可出站访问目标 SSH/BMC，且 egress 仅开放必要网段；
- SQLite，或启用 TLS 的 MySQL 8.x；
- 被监控 GPU 服务器上的 `nvidia-smi` 可用。

在被监控机创建最小权限账号，例如：

```bash
sudo useradd --create-home --shell /bin/bash gpumon
sudo install -d -m 700 -o gpumon -g gpumon /home/gpumon/.ssh
```

优先使用 ED25519 key，并在 `authorized_keys` 使用 `restrict`、
`no-port-forwarding`、`no-agent-forwarding`、`no-X11-forwarding`、`no-pty`。
只有确有需要的 `nvme`/`journalctl` 子命令才加入精确 sudo allowlist。

## 3. 创建本地配置

```bash
git clone https://github.com/Palpitate-xus/lab-gpu-server-monitor.git
cd lab-gpu-server-monitor
cp .env.example .env
chmod 600 .env
mkdir -p data/known_hosts secrets
sudo chown -R 10001:10001 data secrets
chmod 700 data data/known_hosts secrets
```

分别运行三次；每次输出只用于一个配置项，禁止复用：

```bash
openssl rand -hex 32
```

新部署的最小 `.env` 示例：

```ini
JWT_SIGNING_KEY=<独立随机值>
CREDENTIAL_ENCRYPTION_KEYS=<另一独立随机值>
ARCHIVE_ENCRYPTION_KEY=<第三个独立的64位十六进制值>

DATABASE_URL=sqlite:///./data/gpu_monitor.db
AUTO_MIGRATE=no

INIT_ADMIN_USERNAME=<首次管理员用户名>
INIT_ADMIN_PASSWORD=<16至72位随机密码>

COOKIE_SECURE=yes
COOKIE_SAMESITE=strict
TRUST_PROXY=no
TRUSTED_PROXY_CIDRS=127.0.0.1/32,::1/128
REQUIRE_ADMIN_MFA=yes
REMOTE_PROCESS_CONTROL_ENABLED=no
ALLOW_ROOT_SSH=no
ARCHIVE_DIR=/app/archives
```

先保持 `TRUST_PROXY=no`。确认应用实际看到的 Nginx 直连对端地址后，把该地址以精确
`/32`（IPv6 用 `/128`）写入 `TRUSTED_PROXY_CIDRS`，再设置 `TRUST_PROXY=yes`。不要为了
省事信任整个 Docker/办公网段。正式 HTTPS 模式在完成此配置前会拒绝启动，防止登录限流把
所有用户误当成同一个代理来源。Uvicorn 不自行解析代理头，客户端地址只由应用按此名单解析。

应用拒绝空密钥、公开占位值、密钥复用、弱 MySQL 账号以及未加密的非环回 MySQL。
不要把 `.env`、`secrets/`、数据库或归档加入 Git。

### MySQL 配置

不要用 `-p 3306:3306` 把 MySQL 发布到全部接口。参考
`deploy/mysql-hardening.sql.example` 创建两个不同账号：

- `gpumon_migrate`：短期 DDL 账号，只在升级窗口使用；
- `gpumon_app`：运行账号，只授予 `SELECT/INSERT/UPDATE/DELETE`。

把 CA（以及可选客户端证书/私钥）放入 `./secrets`，归属设为
`10001:10001`，目录 0700、文件 0400，确保只有容器运行身份可读：

```ini
DATABASE_URL=mysql+pymysql://gpumon_app:<URL编码密码>@db.internal:3306/gpu_monitor?charset=utf8mb4
DATABASE_SSL_CA=/run/secrets/gpu-monitor/mysql-ca.pem
DATABASE_SSL_CERT=/run/secrets/gpu-monitor/mysql-client.pem
DATABASE_SSL_KEY=/run/secrets/gpu-monitor/mysql-client.key
```

密码中的 `@:/?#%` 必须进行 URL 编码。MySQL 仅绑定内部接口，并由防火墙限制来源。

### 可选 Redis 缓存

单 worker 部署保持 `REDIS_URL=` 即可。使用远程共享缓存时必须配置带至少 16 位认证密码的
`rediss://`；系统会强制证书和主机名校验，并拒绝 URL 中覆盖 TLS 校验的参数。私有 CA 可
通过只读 secrets 挂载后配置 `REDIS_SSL_CA`。只有字面量环回地址或 Unix socket 可以不使用
TLS。Redis 仅保存有大小上限的 JSON 缓存，不使用 pickle。

## 4. 显式迁移数据库

Web/调度进程不会自动执行 DDL。先用短期迁移连接运行一次维护任务：

```bash
# SQLite（容器内路径）
MIGRATION_DATABASE_URL='sqlite:////app/data/gpu_monitor.db' \
  docker compose --profile maintenance run --rm gpu-monitor-migrate

# MySQL：不要把迁移密码写入 shell history
read -rsp 'Migration DATABASE_URL: ' MIGRATION_DATABASE_URL && echo
export MIGRATION_DATABASE_URL
docker compose --profile maintenance run --rm gpu-monitor-migrate
unset MIGRATION_DATABASE_URL
```

迁移失败会返回非零状态；不要在失败时启动或重启正式容器。

## 5. 构建、启动与 HTTPS

默认 Compose 使用多阶段构建、冻结的 pnpm lock 和带哈希的 Python lock：

```bash
export GPU_MONITOR_IMAGE="gpu-monitor:$(git rev-parse --short=12 HEAD)"
docker compose config --quiet
docker compose build --pull
docker compose up -d
docker compose ps
docker compose logs --since=10m gpu-monitor
```

Wolfi 基础镜像、Node 基础镜像、Python wheel 和源码编译的 `ipmitool` 均有 digest/hash
校验。Wolfi APK 的实际解析版本记录在 CI 生成的 CycloneDX SBOM 中；每周自动重建会发现
仓库漂移和新增 CVE。生产发布必须把扫描通过的提交 SHA 标签解析为 registry digest 后再
部署，不能仅依赖标签。

安装并修改 `deploy/nginx-gpu-monitor.conf.example` 中的域名和证书路径：

```bash
sudo nginx -t
sudo systemctl reload nginx
curl --fail https://gpu-monitor.example.com/api/health
curl --fail https://gpu-monitor.example.com/api/ready
```

`/api/health` 是存活检查；`/api/ready` 同时检查数据库、调度心跳、SSH 指纹目录和归档
目录的实际写入能力。
浏览器只访问 HTTPS 域名，不访问 `http://<主机>:8300`。

## 6. 首次登录

系统没有默认账号或默认密码。空库首次启动使用 `.env` 中的一次性管理员凭据；登录后：

1. 立即把 TOTP 密钥加入认证器并完成 MFA 验证；
2. 修改一次性密码；
3. 从活动 `.env` 删除 `INIT_ADMIN_USERNAME` 和 `INIT_ADMIN_PASSWORD`，重启后确认仍可登录；
4. 再创建至少一个管理员和日常 Viewer；
5. MCP 只能使用专用 Viewer，不能使用管理员账号。

管理员未完成 MFA 绑定时只能访问绑定流程，所有管理 API 都会返回 403。
Webhook URL 可能包含机器人令牌，保存后会使用凭据密钥加密，管理 API 只返回“已配置”和
脱敏地址，不会回显完整 URL。

## 7. 添加服务器

进入「服务器」→「添加服务器」，填写名称、目标、端口、`gpumon` 用户和认证材料。
首次连接使用 TOFU：指纹会原子写入 `data/known_hosts`；无法持久化时连接直接失败。
服务器重装后必须在带外渠道核对新的 `SHA256:...` 指纹；重置接口会再次要求管理员密码，
先从目标读取新密钥并严格比对指纹，再原子替换旧记录，不会退化为自动 TOFU。

完整实时进程与资产/IPMI 仅管理员可见。历史指标不会保存登录身份、进程用户名或完整 argv。
远程 kill/renice 默认关闭；如确需启用，仍会逐次要求 MFA 会话和管理员密码再认证，并核对
进程启动标识，避免 PID 被复用后操作到另一个进程。

## 8. 升级与回滚

升级前记录精确版本并备份：

```bash
git rev-parse HEAD
docker image inspect "$GPU_MONITOR_IMAGE" --format '{{.Id}}'
umask 077
# 再执行数据库、known_hosts、.env（加密保管）和归档备份
```

随后拉取目标提交、审查 diff、以提交 SHA 构建候选镜像、执行第 4 节迁移，最后才切换容器。
生产 `.env` 的 `GPU_MONITOR_IMAGE` 必须使用已扫描的提交标签或注册表 digest，不要使用
浮动的 `latest` 或未审查工作区直接部署。

回滚时使用记录的提交和镜像摘要。迁移 012/013 只增加安全字段，旧版本通常可忽略；但旧版本
仍依赖 `SECRET_KEY`，所以升级稳定前应把旧 `.env` 作为加密备份保留，不能提交到 Git。

已有部署从单一 `SECRET_KEY` 升级、清理历史进程数据及轮换密钥的完整步骤见
`SECURITY_HARDENING.md`。

## 9. MFA 恢复

优先由另一名已完成 MFA 的管理员在「用户管理」中重置目标管理员 MFA；该操作会同时吊销
其全部会话。单管理员丢失认证器时，在可信宿主机使用 break-glass 脚本：

```bash
docker compose exec gpu-monitor python scripts/reset_admin_mfa.py --username target_admin
docker compose exec gpu-monitor python scripts/reset_admin_mfa.py --username target_admin --apply
```

执行后立即重新登录、重新绑定 MFA，并审查 `user.mfa_breakglass_reset` 审计记录。

## 10. 上线门禁

```bash
python -m pytest -q backend/tests
python -m pytest -q mcp_server/tests
cd frontend && pnpm test && pnpm audit --prod && pnpm build && cd ..
export GPU_MONITOR_IMAGE="gpu-monitor:$(git rev-parse --short=12 HEAD)"
docker compose config --quiet
```

CI 还会执行 Ruff、Bandit、`pip-audit`、Gitleaks、最终镜像 High/Critical CVE 扫描并生成
CycloneDX SBOM；源码编译的 `ipmitool` 会以 commit 和二进制 SHA-256 显式写入 SBOM。
最终镜像、TLS/防火墙、数据库账号、备份恢复和 SSH 指纹演练全部通过后，才能对受信用户
上线。
