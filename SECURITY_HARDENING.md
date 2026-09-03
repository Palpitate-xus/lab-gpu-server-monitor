# GPU Monitor 安全上线操作手册

本手册对应 `SECURITY_RELEASE_REVIEW.md` 的安全整改。代码默认采用安全失败：缺少密钥、
数据库迁移未完成、SSH 主机密钥目录不可写时，服务会拒绝就绪或拒绝连接。

## 1. 升级前备份与版本记录

记录当前提交和镜像摘要，并备份数据库。不要把 `.env` 或备份提交到 Git。

```bash
git rev-parse HEAD
docker image inspect "$GPU_MONITOR_IMAGE" --format '{{index .RepoDigests 0}}'
umask 077
```

## 2. 拆分密钥

`.env` 权限必须为 0600。三个密钥必须分别生成，不能复用：

```bash
openssl rand -hex 32  # JWT_SIGNING_KEY
openssl rand -hex 32  # 新部署的 CREDENTIAL_ENCRYPTION_KEYS
openssl rand -hex 32  # ARCHIVE_ENCRYPTION_KEY
```

已有部署升级时，为保留现有 SSH/BMC 密文：

1. 先把旧 `.env` 加密备份到仓库之外，验证可读取并限制为 0600；
2. 将旧 `SECRET_KEY` 的值复制到新配置的 `CREDENTIAL_ENCRYPTION_KEYS`；
3. 为 `JWT_SIGNING_KEY` 和 `ARCHIVE_ENCRYPTION_KEY` 生成全新值；
4. 候选版本的活动 `.env` 删除 `SECRET_KEY` 行，但在升级验收和回滚窗口结束前，不销毁第 1 步的旧配置备份；
5. 后续轮换凭据密钥时使用 `新密钥,旧密钥`，完成重加密与恢复验证后再移除旧密钥。

凭据重加密先 dry-run；任何一条密文无法解密都会终止且不会提交：

```bash
docker compose exec gpu-monitor python scripts/rotate_credentials.py
docker compose exec gpu-monitor python scripts/rotate_credentials.py --apply
```

完成数据库备份/恢复抽查、SSH/BMC 连接抽查后，把旧密钥从
`CREDENTIAL_ENCRYPTION_KEYS` 尾部移除并滚动重启。JWT、凭据和归档密钥必须分别轮换，
不得互相复用。该轮换脚本同时覆盖 SSH、BMC、MFA 和已加密的 Webhook URL；升级后的首次
启动会在应用就绪前把遗留的明文 Webhook URL 原地加密，并写入审计记录。

## 3. 修复持久目录权限

镜像内应用 UID/GID 为 10001。执行前确认路径准确：

```bash
sudo chown -R 10001:10001 /home/xusheng/workspace/gpu_monitor/data
sudo chmod 700 /home/xusheng/workspace/gpu_monitor/data
sudo chmod 700 /home/xusheng/workspace/gpu_monitor/data/known_hosts
sudo find /home/xusheng/workspace/gpu_monitor/data/known_hosts -maxdepth 1 -type f -exec chmod 600 {} +
sudo find /home/xusheng/workspace/gpu_monitor/data -maxdepth 1 -type f -exec chmod 600 {} +
sudo chown -R 10001:10001 /home/xusheng/gpu_logs
sudo chmod 700 /home/xusheng/gpu_logs
```

上线前逐台核对已有 SSH 指纹。不要为了消除报错直接删除所有已记录指纹。

## 4. MySQL TLS 与最小权限

GPU Monitor 不应继续复用来源为 `%`、拥有 `ALL PRIVILEGES` 的账号。参考
`deploy/mysql-hardening.sql.example` 创建两个账号：

- `gpumon_migrate`：只在迁移时临时使用，具有本库 DDL 权限；
- `gpumon_app`：Web/调度进程使用，只具有本库 DML 权限。

MySQL 仅监听内部地址，不发布到 `0.0.0.0:3306`；启用 `REQUIRE SSL`，将 CA/客户端
证书放入仓库外的 `secrets/`（该目录已被 Git 忽略）并以只读方式挂载到容器，再配置
`DATABASE_SSL_CA/CERT/KEY`。应用会拒绝连接没有 CA 的非回环 MySQL，不提供跳过数据库
TLS 的配置开关。回环/Unix socket 只适用于同机隔离场景。

迁移凭据不要长期写进 `.env`，可在当前 shell 临时导出：

```bash
read -rsp 'Migration DATABASE_URL: ' MIGRATION_DATABASE_URL && echo
export MIGRATION_DATABASE_URL
docker compose --profile maintenance run --rm gpu-monitor-migrate
unset MIGRATION_DATABASE_URL
```

随后使用 DML 账号启动应用；`AUTO_MIGRATE` 保持 `no`。

可选远程 Redis 必须使用 `rediss://`、至少 16 位认证密码和有效的服务端证书。私有 CA 使用
`REDIS_SSL_CA`；系统拒绝 `ssl_cert_reqs=none` 等 URL 降级参数。单 worker 时建议留空并使用
进程内缓存。

迁移顺序必须是：数据库备份 → 使用临时 DDL 账号运行 maintenance profile → 确认
`012_auth_sessions`、`013_admin_mfa` 已记录在 `schema_migrations` → 切换为 DML 账号 →
启动候选应用。应用发现安全字段缺失时会拒绝启动，不能绕过。

## 5. TLS 入口

Compose 默认只发布 `127.0.0.1:8300`。将 `deploy/nginx-gpu-monitor.conf.example` 安装到
受控 Nginx，替换域名/证书路径并验证：

```bash
sudo nginx -t
sudo systemctl reload nginx
curl --fail https://gpu-monitor.example.com/api/health
curl --fail https://gpu-monitor.example.com/api/ready
```

防火墙只开放 TLS 入口，3306 和 8300 不允许来自外部网段。浏览器部署保持
`COOKIE_SECURE=yes`、`COOKIE_SAMESITE=strict`。正式启动前必须确认应用实际看到的 Nginx
直连对端地址，以精确 `/32`（IPv6 为 `/128`）配置 `TRUSTED_PROXY_CIDRS`，并设置
`TRUST_PROXY=yes`；否则应用会拒绝启动，避免所有客户端被错误合并到一个代理限流桶。

## 6. 清理历史敏感进程数据

新版采集不再保存进程用户名和完整 argv。先 dry-run，再执行一次清理：

```bash
docker compose exec gpu-monitor python scripts/scrub_sensitive_history.py
docker compose exec gpu-monitor python scripts/scrub_sensitive_history.py --apply
```

该操作只删除历史登录身份/来源地址及进程身份/命令参数，不修改 CPU、GPU、显存、功耗等指标。

## 7. MFA 上线与恢复

`REQUIRE_ADMIN_MFA=yes` 保持开启。每位管理员首次登录后必须绑定 TOTP，未完成前不能调用
管理 API。至少保留两名独立管理员，并保存一次性恢复流程，不保存 TOTP 明文。

优先由另一名已绑定 MFA 的管理员在「用户管理」中重置。单管理员丢失认证器时，在可信
宿主机先 dry-run，再执行 break-glass：

```bash
docker compose exec gpu-monitor python scripts/reset_admin_mfa.py --username target_admin
docker compose exec gpu-monitor python scripts/reset_admin_mfa.py --username target_admin --apply
```

该操作吊销目标管理员全部会话。随后立即重新绑定 MFA，并审查
`user.mfa_breakglass_reset` 审计记录。

## 8. 构建与验收

```bash
cd frontend
corepack enable
pnpm install --frozen-lockfile
pnpm test
pnpm audit --prod
pnpm build
cd ..

export GPU_MONITOR_IMAGE="gpu-monitor:security-$(git rev-parse --short=12 HEAD)"
docker compose config --quiet
git rev-parse --short=12 HEAD
docker build --pull -f Dockerfile.multistage \
  -t "$GPU_MONITOR_IMAGE" .
# 对上述提交标签完成扫描并记录 registry digest 后，才切换容器。
docker compose ps
docker compose logs --since=10m gpu-monitor
```

还需执行后端/MCP hash lock 安装、`pip-audit`、Ruff、Bandit 和 Gitleaks。必须对最终镜像
执行 Trivy/Grype High/Critical 扫描；未修复漏洞同样不能静默忽略。仓库 CI 同时执行这些
门禁并生成 CycloneDX SBOM。扫描和验收记录应绑定提交 SHA 与镜像摘要。

镜像供应链采用分层锁定：Wolfi 基础镜像固定多架构 index digest；Python 依赖固定版本和
wheel 哈希；`ipmitool` 固定上游 commit 与源码归档 SHA-256，并在构建时启用 PIE、RELRO、
NOW、FORTIFY 后编译。因为 Wolfi APK 仓库为滚动仓库，APK 解析结果以最终 SBOM 和镜像
digest 为准，不在 Dockerfile 中钉死可能已从仓库移除的小版本。CI 每周重新构建和扫描，
任何 High/Critical 或 secret 命中都会阻断；生产环境只使用已验收的 registry digest。
Trivy 无法自动识别源码编译的 `ipmitool`，CI 会把其版本、commit 和二进制 SHA-256 显式
补入 CycloneDX SBOM。

## 9. 运行策略

- 被监控主机使用专用 `gpumon` 账号和精确 sudo allowlist；默认拒绝 root SSH。
- 远程 kill/renice 默认关闭；确需启用时设置 `REMOTE_PROCESS_CONTROL_ENABLED=yes`，
  每次操作仍要求管理员重新输入密码。
- 完整实时进程、IPMI 和资产信息只对管理员开放。
- MCP 使用专用 Viewer，保持 `GPU_MONITOR_MCP_PRIVACY_MODE=strict`，远程地址必须 HTTPS。
- 将容器 `security_audit` 日志转发到外部只追加日志系统并设置保留/告警策略。
