# GPU Monitor 上线与网络安全审查

> 整改复核日期：2026-09-03（UTC）
> 原始审查基线：`0754242`
> 整改起点：`ecd753d`（仅包含原始审查报告）
> 整改代码提交：`eda861c0974b`
> 候选镜像：`gpu-monitor:security-eda861c0974b`（`sha256:1e612ba70f1b32bc67d62ebba436421f5fe5f570e96ba449ae20d48b24f3d645`）

## 整改复核结论

原始审查发现的 **S-01～S-22 共 22 项安全问题，在仓库可控制的代码、配置、构建和文档
范围内均已整改**。候选版本没有修改 GPU 指标计算、采集口径、报表算法等业务逻辑；只处理
认证授权、敏感数据边界、输入约束、传输安全、供应链、容器隔离、审计和上线失败策略。

这不等于对“未知漏洞”作绝对保证，也不代表当前运行实例已经安全。2026-09-03 的只读检查
确认旧容器仍在运行，仍使用旧镜像和旧部署配置；本次没有重启、替换或写入现网。候选版本
只有完成下方部署门禁后才可上线。

| 复核项 | 当前结果 |
|---|---|
| 已识别的 22 项安全问题 | **仓库侧全部完成整改** |
| GPU 指标与报表业务逻辑 | **未改动**；原报告 B 类非安全口径问题仍保留，未借安全整改改算法 |
| 自动化测试与静态检查 | **通过**；详细结果见下表 |
| 最终候选镜像漏洞/secret 扫描 | **通过**；全严重级别已知漏洞 0，secret 0 |
| 当前运行实例 | **未切换，仍不满足上线要求** |
| 公网/不可信网络上线 | **暂不批准**；须完成 TLS、防火墙、DB、迁移、轮换、清理与演练门禁 |

## 安全问题整改状态表

状态中的“代码完成、部署待验收”表示应用已具备强制机制，但证书、数据库账号、真实主机和
现网数据等外部状态不能通过修改仓库代替。

| ID | 整改状态 | 主要落点与复核证据 |
|---|---|---|
| S-01 | **代码完成、部署待验收** | SSH TOFU 改为文件锁、原子写入、0700/0600 和持久化失败关闭连接；readiness 检查真实写入。上线前仍须逐台核对现有指纹并修正数据卷属主。 |
| S-02 | **代码完成、部署待验收** | Compose 默认仅绑定 `127.0.0.1:8300`，提供 TLS-only Nginx 示例、HSTS 和可信代理精确地址校验；真实证书与防火墙尚须部署。 |
| S-03 | **已修复** | FastAPI/Starlette/python-multipart 等升级并生成 hash lock；后端 `pip-audit` 为 0。 |
| S-04 | **已修复** | 删除可工作默认账号、密码和密钥；缺失、占位、复用或强度不足时 fail-fast；初始管理员使用显式一次性凭据。 |
| S-05 | **代码完成、部署待验收** | 远程 MySQL 强制 CA/TLS，迁移与运行账号拆分，提供最小权限模板；现网 MySQL 账号、TLS 和 3306 防火墙须按手册执行。 |
| S-06 | **已修复** | 会话使用持久化 `auth_id`/token version/JTI，登出、改密、改角色、禁用和删除均可跨重启撤销，阻止同名账号复用旧 Token。 |
| S-07 | **已修复** | 登录输入长度/格式、请求体大小、Origin/CSRF、容量受限限流和管理员再认证限流均已覆盖测试。 |
| S-08 | **代码完成、数据清理待执行** | Viewer/MCP 不再获得进程身份和完整 argv，新历史数据不再保存这些字段；提供只删敏感字段的 dry-run/apply 清理脚本。 |
| S-09 | **代码完成、主机侧待验收** | 默认拒绝 root SSH，远程进程控制默认关闭；管理员要求 MFA，危险操作要求短时密码再认证并防 PID 复用；真实主机仍须迁移低权限账号/sudo allowlist。 |
| S-10 | **已修复** | API 资源限制、缓存/限流边界、只读 rootfs、非 root、cap-drop、no-new-privileges、CPU/内存/PID 与日志轮转已配置。 |
| S-11 | **已修复** | 迁移失败阻止启动，迁移改为独立 maintenance profile；liveness/readiness 分离并检查 DB、schema、scheduler 与关键目录。 |
| S-12 | **已修复** | Viewer DTO 移除 BMC 用户、管理地址及资产/IPMI敏感字段；完整视图仅管理员可用。 |
| S-13 | **已修复** | MCP 使用结构化 URL/IP 校验，远程只允许 HTTPS，严格隐私模式默认开启，并覆盖恶意 hostname 测试。 |
| S-14 | **已修复** | Webhook 连接固定到已校验公网 IP，同时保留原 hostname 的 TLS SNI/证书验证，禁止重定向并限制响应。 |
| S-15 | **代码完成、恢复演练待执行** | 归档使用 AES-GCM、0600、去凭据元数据和完整计数后删除；恢复限制大小/数量、默认禁用服务器并要求显式确认。 |
| S-16 | **已修复** | 严格 `.dockerignore`；Node/基础镜像 digest、Python wheel hash、ipmitool commit+源码 SHA-256；CI 生成含源码组件的 CycloneDX SBOM。 |
| S-17 | **已修复** | CSV 统一 RFC 4180 转义并防公式注入，包含引号、逗号、换行和危险前缀测试。 |
| S-18 | **已修复** | SSH 禁用弱算法，JWT 改用 PyJWT 并移除无用 ecdsa；依赖审计为 0。 |
| S-19 | **代码完成、密钥轮换待执行** | JWT、凭据和归档密钥拆分；凭据 keyring 支持渐进轮换，提供全量 dry-run/apply 脚本且包含 MFA/Webhook。 |
| S-20 | **代码完成、外部审计存储待接入** | 新增后端/MCP/前端测试、Ruff、Bandit、pip/pnpm audit、Gitleaks、Trivy、SBOM、Dependabot 和 `SECURITY.md`；生产审计仍须转发只追加存储。 |
| S-21 | **已修复** | JWT 不再写 localStorage，改用 Secure/HttpOnly/SameSite cookie，并配套 CSRF 与 Origin 校验。 |
| S-22 | **已修复** | 关闭 Uvicorn server header，敏感 API 统一 `no-store`，禁用的 docs/redoc/openapi 返回真实 404。 |

## 整改验证记录

| 检查 | 整改候选结果 |
|---|---|
| 后端测试 | `39 passed`；仅 1 条已知第三方弃用警告 |
| MCP 测试 | `12 passed` |
| 前端测试 / 构建 | `3 passed`；生产构建通过，仅保留非阻断 chunk-size 提示 |
| Ruff / Bandit | 通过；Bandit 仅保留带说明的 TOTP 标准 SHA-1 `nosec` |
| Python / Node 依赖审计 | 后端 0、MCP 0、`pnpm audit --prod` 0 |
| Secret 扫描 | 已验证命中 0 |
| Compose / workflow / diff | Compose、GitHub Actions YAML、主 Dockerfile `--check`、`git diff --check` 均通过；多阶段 Dockerfile 已修正全局 `ARG` 作用域，本机后续拉取固定 Node digest 时因 Docker Hub 超时中止，仍须由联网 CI 完成全量构建 |
| 候选镜像运行 | 非 root UID 10001、只读 rootfs、cap-drop、no-new-privileges 和资源限制下 readiness 通过；`/docs` 404，安全响应头生效 |
| 候选镜像扫描 | Trivy `0.74.0`：Wolfi 30 个系统包与 Python 共 2 个目标，UNKNOWN/LOW/MEDIUM/HIGH/CRITICAL 均为 0，secret 0 |
| 候选镜像 SBOM | CycloneDX 共 68 个组件；已显式补入源码构建的 `ipmitool` 组件 |
| `ipmitool` 供应链 | 固定 `1.8.19` + commit `be11d948f89b10be094e28d8a0a5e8fb532c7b60` + 源码 SHA-256；二进制 SHA-256 为 `5f384a57d9f028bed17749285f8a794b74a3ad4c341588fb58af281cd69988b6`；精确 commit 的 OSV 查询无已知漏洞 |
| 历史敏感数据清理 | 全量 dry-run 在现网数据规模下超时后已终止，**没有写入**；须在维护窗口重新评估并执行 |

较早的 Debian slim 候选镜像因扫描发现 16 个当时无上游修复版本的 High/Critical OS
漏洞而被否决；最终候选改为固定 digest 的 Wolfi 基础镜像。源码编译的 `ipmitool` 不会被
Trivy 自动识别，因此 CI 会把其 commit 与二进制 SHA-256 显式加入 SBOM，并独立核验上游
公告。

## 上线前仍必须完成的外部操作

| Gate | 必须完成 | 验收证据 |
|---|---|---|
| G-01 网络入口 | 安装真实 TLS 证书与 Nginx 配置；防火墙只开放受信 TLS 入口，禁止外部访问 8300/3306 | 外部端口扫描、TLS 配置报告、HSTS/代理地址验证 |
| G-02 数据库 | 备份；启用 MySQL TLS；创建受限迁移账号与 DML 运行账号；执行 012/013 迁移 | `Ssl_cipher` 非空、grant 清单、`schema_migrations`、迁移日志 |
| G-03 密钥与身份 | 生成三类独立密钥，迁移/轮换遗留密文；移除一次性管理员凭据；所有管理员绑定 MFA | 轮换 dry-run/apply 记录、恢复验证、管理员/MFA 清单 |
| G-04 历史与备份 | 维护窗口执行历史敏感字段 scrub；验证加密归档和隔离恢复 | 清理前后计数、归档权限、恢复演练记录 |
| G-05 SSH/BMC | 修正卷权限，逐台核对 SSH 指纹；迁移 root/高权账号为专用最小权限账号 | 指纹清单、账号/sudo/BMC 权限清单、采集验收 |
| G-06 运维闭环 | 审计日志接入外部只追加存储；部署按提交 SHA + registry digest；预生产观察并准备回滚 | SBOM/扫描件、镜像 digest、审计告警、24～72 小时观察及回滚记录 |

在 G-01～G-06 完成前，不应以“代码已整改”为由直接替换生产。现有旧实例本身仍是风险项，
应在维护窗口按 `SECURITY_HARDENING.md` 和 `DEPLOYMENT.md` 完成切换。

---

## 原始基线审查（2026-09-02，保留审计轨迹）

以下“一”到“九”为整改前基线记录，状态和结论不代表整改候选版本的当前状态。

> 审查日期：2026-09-02（UTC）
> 代码基线：`0754242`（`feat(mcp): add read-only GPU monitoring server`）
> 审查对象：FastAPI 后端、Vue 前端、SSH/IPMI 采集、MySQL、归档恢复、MCP Server、Docker Compose 与当前运行实例
> 审查方式：静态代码审查、依赖漏洞审计、隔离 SQLite 接口复现、生产实例只读检查、非破坏性 HTTP 探测
> 说明：未修改业务代码，未登录真实 SSH/BMC，未触发采集、进程操作、Webhook 或生产数据写入。

## 一、结论

**当前版本不建议直接上线到公网或不可信办公网。** 在严格防火墙/VPN 隔离的实验室网络中可以继续试运行，但仍应先修复 SSH 主机密钥持久化问题；该问题已在当前实例持续发生，会让部分首次连接的 SSH 主机密钥校验退化为 fail-open。

| 结论项 | 结果 |
|---|---|
| 公网/不可信网络上线 | **不通过** |
| 严格隔离内网试运行 | **有条件通过**：先修 S-01，并限制 8300/3306 来源 |
| 认证授权基本边界 | 基本正确，但会话撤销与身份绑定不合格 |
| 敏感凭据管理 | 当前 `.env` 较安全；部署默认值、密钥生命周期和备份边界不合格 |
| 依赖安全 | 后端不通过；前端和 MCP 当前审计通过 |
| 数据正确性 | 不通过；在线状态、利用率、能耗等核心口径存在确定错误 |
| 可运维性 | 不通过；迁移失败继续启动、健康检查过浅、缺少 CI/回归测试 |

优先级定义：

| 优先级 | 含义 |
|---|---|
| P0 | 上线阻断；暴露到不可信网络前必须修复 |
| P1 | 高风险；正式生产前应修复 |
| P2 | 中风险；应进入首轮生产整改 |
| P3 | 低风险/工程质量；可排期处理 |

本次共列出 **22 项安全/上线问题**（P0 5、P1 6、P2 9、P3 2）和 **21 项确定或高度可信的功能问题**（P1 8、P2 10、P3 3）。同一根因同时影响安全和功能时，两张表会互相引用。

## 二、网络安全与上线问题

| ID | 优先级 | 状态 | 位置/证据 | 问题与影响 | 修复与验收建议 |
|---|---|---|---|---|---|
| S-01 | **P0** | **运行态确认** | `backend/app/ssh_transport.py:32-70,87-125`；当前容器 UID 10001，`/app/data/known_hosts` 为 root:root 0755、文件 0644；12 小时日志出现 **8483** 条 `cannot persist host key`；9 台服务器仅有 4 个 `server_*.keys` | `_TofuPolicy` 写入失败只记警告，当前连接仍继续；未固定密钥的目标会在每次连接时重新“首次信任”。密码认证可能被 SSH 中间人窃取。`forget_hostkey()` 又吞掉删除错误，界面可能提示重置成功但实际未重置。 | 启动前保证 bind/named volume 属于运行 UID，目录 0700、文件 0600；使用原子写入和文件锁；持久化失败必须关闭连接并报错；重置失败必须返回 5xx。增加容器 smoke test：创建、读取、拒绝变更、删除主机密钥均成功。 |
| S-02 | **P0** | **运行态确认** | `docker-compose.yml:7-9`；`0.0.0.0:8300` 与 `[::]:8300` 监听；当前 Nginx 配置没有代理 8300；直接访问为明文 HTTP | 登录密码、JWT、服务器清单、进程命令行及监控数据均可明文传输。应用虽有 CSP 等安全头，但无法替代 TLS。 | Compose 默认改为 `127.0.0.1:8300:8000`；由受控 Nginx/网关终止 TLS，HTTP 强制跳转 HTTPS；外层只允许 VPN/管理网段；确认 HSTS、真实客户端 IP和 WebSocket/超时配置。 |
| S-03 | **P0** | **依赖审计+可达路径确认** | `backend/requirements.txt`；`pip-audit` 报 **17 条/4 个包**。`python-multipart==0.0.20` 的二次复杂度表单解析可由 `/api/auth/login` 触达；`starlette==0.41.3` 的 Range 二次复杂度可由 `/`、`/assets/*` 的 `FileResponse/StaticFiles` 触达；良性 Range 探测返回 206 | 未认证攻击者可用构造表单或 Range 请求消耗单 worker CPU，造成服务不可用。17 条中包含条件不适用项，但上述高危 DoS 与本系统直接相关。 | 不要只强行覆盖传递依赖；整体升级并回归。2026-09-02 的可解析候选为 `FastAPI 0.141.1 + Starlette 1.6.0 + python-multipart 0.0.32`。升级后重新执行 `pip-audit`、登录/静态文件/Range/表单回归，并在反向代理限制请求头和 body 大小。 |
| S-04 | **P0** | **配置确认** | `docker-compose.yml:13-18`、`backend/app/config.py:4,31,39-41`、`.env.example:5` | 首次部署仍硬编码 `admin/admin123`；配置类还有公开数据库默认口令。示例 `SECRET_KEY=change-me-run-openssl-rand-hex-32` 长度足够且不等于代码唯一拒绝值，会通过启动检查。当前实例 3 个活动管理员均已不是 `admin123`，当前真实密钥也不是占位符，但新部署仍危险。 | 删除所有可工作的默认密码；`INIT_ADMIN_PASSWORD`/数据库密码/密钥缺失时 fail-fast；示例值留空；拒绝完整占位符集合；首次管理员使用一次性随机密码并强制改密。增加启动配置测试。 |
| S-05 | **P0** | **运行态确认** | 当前 MySQL 监听 `0.0.0.0:3306`/`[::]:3306`；会话 `Ssl_cipher` 为空；账号为 `gpumon@%`，拥有 `gpu_monitor.*` 的 ALL PRIVILEGES | 数据库流量未加密且账户来源不受限。只要密码泄露或网络可嗅探，攻击者可读写全部监控数据和密文凭据，并破坏表结构。 | 优先把 MySQL 仅绑定回环或私有 Docker 网络并用防火墙拒绝外部 3306；账户限制到固定容器网段/主机；启用 TLS；迁移账号与运行账号分离，运行账号仅给必要 DML；复核备份账号权限。 |
| S-06 | **P1** | **隔离复现** | `backend/app/security.py:37-55,89-110`、`token_revocation.py:1-52`、`api/users.py:67-110`、前端 `Layout.vue:107-114` | JWT 撤销只在内存，重启后密码修改/删除产生的旧令牌会重新有效，且没有服务端 logout。鉴权按 `sub=username` 查用户，不验证 JWT 的 `uid` 与数据库用户 ID；隔离测试模拟重启及同名账号重建后，旧 Viewer Token 可访问管理员接口。 | 用户表增加持久化 `token_version`/`session_epoch`，JWT 同时绑定不可复用的用户 ID 与版本；鉴权按 ID 查询并核对用户名/版本；实现 logout/JTI 撤销；修改密码、角色、禁用、删除时事务内递增版本。多实例时使用数据库/Redis 持久化。 |
| S-07 | **P1** | **代码确认** | `api/auth.py:40-81`、`rate_limit.py:28-79` | 主登录路由使用 `OAuth2PasswordRequestForm`，没有用户名/密码长度约束或全局请求体上限；限流字典没有总容量上限。攻击者可用大量超长、唯一用户名消耗内存；任意来源对已知用户名失败 5 次还能持续锁死管理员，形成账户 DoS。限流重启/多 worker 后也不一致。 | 登录后立即做与 `LoginRequest` 相同的长度/字符规范校验；网关和 ASGI 层限制 body/header/连接数；限流使用有容量和 TTL 的 Redis；以 IP+账号组合、渐进退避和告警替代可被外部永久维持的全局硬锁。 |
| S-08 | **P1** | **代码+运行数据确认** | `ssh_collector.py:588-613,754`、`schemas.py:174-177`、`api/metrics.py:107-129,247-276`；当前每台服务器最新快照合计存有 **4025** 条完整进程命令行 | Viewer 可读取完整 `ps args`；命令行常包含令牌、对象存储密钥、数据库 DSN 或训练参数。当前简单关键字扫描未命中明显秘密，但不能证明没有敏感数据，且历史快照持续保存这些字段。 | 默认只保存/返回 PID、用户、可执行文件名与资源值；完整 argv 改为管理员按需实时读取，不进入历史库；增加脱敏规则和保存开关；为 Viewer/MCP 单独定义字段级响应模型。 |
| S-09 | **P1** | **架构风险** | `schemas.py:47-63` 默认 SSH 用户为 root；`api/metrics.py:279-319` 支持远程 kill/renice；当前 9 台中 1 台使用 root SSH，5 台配置 BMC | Web 应用同时是 SSH/BMC 凭据库和远程操作入口，管理员 Token 被盗后的横向影响很大；当前无 MFA、无二次确认令牌、无细粒度操作角色。 | 采集统一使用专用低权限账号和精确 sudo allowlist；禁止 root 密码登录；BMC 使用只读账户；远程进程操作拆为独立角色并要求 MFA/短时再认证/双人审批；限制容器到目标网段的 egress。 |
| S-10 | **P1** | **配置/代码确认** | 除登录外无 API 级限流；公开状态页存在重查询；容器 `pids_limit`/memory/CPU 均无限制，rootfs 可写，Docker `json-file` 无轮转 | 单个 Viewer 或未认证状态页请求可以放大数据库、SSH 与 CPU 消耗；日志/线程/内存耗尽会影响同机其它实验服务。与 S-03 的可利用解析 DoS 叠加后风险更高。 | 网关分端点限流；限制请求体、Range 数、并发和超时；公开状态页使用 single-flight/预计算；Compose 设置 CPU、内存、PID、日志轮转、`no-new-privileges`、`cap_drop: [ALL]`，根文件系统尽量只读。参考 [OWASP API4:2023](https://owasp.org/API-Security/editions/2023/en/0xa4-unrestricted-resource-consumption/)。 |
| S-11 | **P1** | **代码确认** | `main.py:34-43,283-285`、Docker `HEALTHCHECK` | 数据库迁移异常被记录后继续启动；`/api/health` 永远只返回静态 `ok`，不检查 DB、schema、调度线程、归档目录或主机密钥目录。容器可显示 healthy，但核心功能已失效或 schema 半迁移。 | 迁移失败必须阻止启动；增加 `/livez` 与 `/readyz`，readiness 检查 DB、schema 版本、调度线程时间、新鲜度及关键目录可写性；健康检查使用 readiness。 |
| S-12 | **P2** | **代码/隔离复现** | `schemas.py:87-109`、`api/servers.py:39-41`、`api/ipmi.py:32-48` | Viewer 响应包含 `bmc_user`，并能读取完整 IPMI LAN/FRU/SEL、主机 IP/资产信息。SSH 用户名被刻意隐藏，BMC 用户名却未隐藏，字段策略不一致。 | 明确数据分类；Viewer 默认移除 BMC 用户名和管理面资产字段；必要信息只给 `operator/admin`；为公开页、Viewer、MCP、Admin 建立不同 DTO。 |
| S-13 | **P2** | **已复现** | `mcp_server/server.py:43-45,91-99` | MCP 用字符串 `hostname.startswith("127.")` 判断回环；`http://127.attacker.example:8300` 被错误当作本机，允许明文发送 Viewer 密码。 | 用 `ipaddress.ip_address()` 判断字面 IP；`localhost` 单独白名单并解析后确认全部地址回环；拒绝 URL 中的 query/fragment/userinfo；新增恶意主机名单元测试。 |
| S-14 | **P2** | **代码确认** | `notifier.py:58-112` | Webhook 已要求 HTTPS、公网 IP并禁止跳转，这是正向设计；但校验时 DNS 解析一次，真正 `urlopen` 又解析一次，仍有 DNS rebinding/TOCTOU SSRF 窗口。 | 连接到校验后的固定 IP，同时用原 hostname 做 TLS SNI/证书校验；或经具备 egress allowlist 的代理发送；每次重试都重新安全校验。 |
| S-15 | **P2** | **代码确认** | `scheduler.py:367-437`、`scripts/restore_archive.py:36-99` | 每日归档把 `Server` 全部列写入 tar，包括 SSH/BMC 密文、用户名和地址；默认新文件通常为 0644。恢复脚本会重建缺失服务器并保留原 `enabled`/凭据，可能把已退役目标重新启用。归档成功判断 `written > 0` 也可能在并发边界下删除未完整归档的旧行。 | 服务器快照只保留恢复外键所需的无密钥元数据；备份目录 0700、文件 0600并做独立加密/完整性签名；仅 `written == n` 才删除；恢复默认禁用服务器、剥离凭据并要求显式确认；在隔离库定期演练。 |
| S-16 | **P2** | **配置确认** | 根目录缺 `.dockerignore`，当前构建上下文约 **331 MB**；包含 `.env`、`data/`、`.git/`、`frontend/node_modules/` 等；`Dockerfile` 复制宿主预构建 `dist`，多阶段版本使用 `pnpm install --no-frozen-lockfile` | 远程 BuildKit/CI 会接收不应进入构建上下文的密钥和数据；构建不可复现，宿主残留或被篡改的 dist 可直接进入镜像。 | 新增严格 `.dockerignore`；CI 内用锁文件和 `--frozen-lockfile` 构建前端；基础镜像固定 digest；Python 生成完整 hash lock；生成 SBOM并签名镜像。 |
| S-17 | **P2** | **代码确认** | `frontend/src/views/Reports.vue:105-121` | CSV 直接拼接服务器名和标签，没有完整转义，也没有防 `= + - @` 公式前缀。管理员打开导出文件时可能触发 Excel/LibreOffice 公式注入；引号/换行还会破坏 CSV。 | 所有单元格统一 RFC 4180 转义；以危险字符开头的文本前置单引号或制表保护；增加公式、引号、逗号、换行用例。 |
| S-18 | **P2** | **依赖审计** | `paramiko==3.5.0` 命中 SHA-1 公告；`python-jose[cryptography]` 带入无修复版 `ecdsa`，应用实际只使用 HS256 | Paramiko 默认算法仍可能接受弱 SHA-1；`ecdsa` 当前路径未被应用使用，但增加无意义攻击面和审计噪声。 | Paramiko 显式禁用 `ssh-rsa`/弱算法并跟进上游修复提交；将 JWT 库改为维护活跃、只需对称算法的实现，或去掉不需要的 extra；升级后复跑 SSH 兼容测试。见 [Paramiko GHSA](https://github.com/advisories/ghsa-r374-rxx8-8654)。 |
| S-19 | **P2** | **设计确认** | `security.py:37-85` | 同一个 `SECRET_KEY` 同时签 JWT、派生 Fernet 凭据密钥；轮换 JWT 密钥会让所有 SSH/BMC 密文无法解密，因而团队容易长期不轮换。 | 分离 `JWT_SIGNING_KEY` 和版本化的 `CREDENTIAL_ENCRYPTION_KEYS`；支持旧 key 解密、新 key 加密及后台轮换；优先接入 KMS/Secret Manager。 |
| S-20 | **P2** | **仓库确认** | 无 CI、Dependabot/Renovate、SECURITY.md、SBOM或正式后端测试套件；Ruff 当前 30 项 | 依赖漏洞与回归只能靠人工发现，无法形成上线门禁；审计日志也不是防篡改存储，设置、状态页等部分高权限操作未完整审计。 | 建立 CI：后端测试、MCP 测试、前端构建、Ruff、Bandit、`pip-audit`、`pnpm audit`、镜像扫描、secret scan；补 SECURITY.md；审计日志覆盖所有写操作并转发到只追加外部存储。 |
| S-21 | **P3** | **代码确认** | `frontend/src/composables.js:59-105` | JWT 保存在 localStorage，任何未来 XSS/恶意扩展都可读；当前未发现 `v-html/innerHTML/eval`，且 CSP 较严格，因此现实风险有所降低。 | 长期改为 Secure+HttpOnly+SameSite Cookie并配套 CSRF；若继续 Bearer/localStorage，保持短时令牌、实现刷新令牌轮换并避免加载第三方脚本。 |
| S-22 | **P3** | **运行态确认** | API 响应显示 `server: uvicorn`；敏感 API/登录响应未统一 `Cache-Control: no-store`；`/docs` 在禁用时被 SPA catch-all 返回 200 HTML | 信息泄露和缓存风险较低，但会干扰扫描器与运维判断。 | 关闭 server header；敏感 API 加 `no-store`；对 `/docs`、`/redoc`、`/openapi.json` 显式返回 404，而不是 SPA 200。 |

## 三、功能与数据正确性问题

| ID | 优先级 | 状态 | 位置/证据 | 问题与影响 | 修复与验收建议 |
|---|---|---|---|---|---|
| B-01 | **P1** | **隔离复现** | `main.py:186-232,261-275` | `_set_setting()` 每个键单独 commit。提交 `poll_interval=61 + 非法 webhook` 返回 400，但再次读取已变为 61；阈值接口同类。 | 先验证完整 payload，再单事务 flush/commit；任何异常 rollback。测试“全成或全败”。 |
| B-02 | **P1** | **隔离复现** | `security.py:42-49`、`token_revocation.py:35-52`、`api/users.py:103-110` | 撤销时间是浮点秒，新 JWT 的 `iat` 是整数秒；改密返回 200 后，响应里的新 Token 立即访问 `/auth/me` 得 401。 | 与 S-06 一并使用持久化 token version；至少统一时间精度并保证新版本 Token 在提交后有效。 |
| B-03 | **P1** | **隔离复现** | `api/status_page.py:163-225` | 一条 **7 天前**的成功记录仍被公开状态页标记为 `online=true`，整体也可显示全部正常。 | 以 `max(2×poll_interval, 上限)` 判断新鲜度；过期显示 `stale/unknown`，公开 `data_age_seconds`。 |
| B-04 | **P1** | **隔离复现** | `api/metrics.py:61-104` | 禁用服务器仍参与 online/error、CPU、内存、磁盘、GPU 汇总；隔离测试禁用后 `servers_online` 仍为 1。 | 资源 KPI 只聚合启用且新鲜的数据；明确定义 total/enabled/disabled 口径。 |
| B-05 | **P1** | **代码确认** | `api/enterprise.py:241-291`、`scheduler.py:821-888` | `gpu_hours=ok_samples/60` 假设固定 60 秒且没乘 GPU 数；`idle_ratio_pct=idle_min/(ok*60)` 量纲错误，8 卡服务器可显示 800% 等失真值。 | 小时表记录采样秒数、GPU 卡分钟/卡时；占比使用空占卡分钟/总卡分钟。覆盖 1/8 卡与 10/30/60/120 秒间隔测试。 |
| B-06 | **P1** | **代码确认** | `api/cockpit.py:159-329` | 每日能耗使用“均值 W × 24h”，即使当天只过几小时或历史缺样也外推全天；coverage 把小时点按 1440 分钟计算；`peak_w` 是单台服务器峰值而不是同一时刻集群总峰值。 | 按相邻采样/小时积分 `W×Δt`；当天标明“截至当前”而非全天；覆盖率按期望粒度计算；集群峰值按对齐时间桶求和后取 max。 |
| B-07 | **P1** | **代码确认** | `api/cockpit.py:127-156` | 当前功率先过滤所有历史 `status=ok` 再取 max；服务器已离线、停用或采集停止时，最后成功功率会无限计入。 | 先取启用服务器绝对最新记录，再校验状态和新鲜度；过期不计入并返回 stale 数。 |
| B-08 | **P2** | **隔离复现** | `api/servers.py:129-153`、`models.py:302-321` | 删除服务器返回 200 后，`ipmi_snapshots` 仍残留 1 行；其它缺少 FK 的表也依赖易漏的手工列表。 | 为全部从表建立正式 FK/`ON DELETE` 策略，迁移前清孤儿；删除接口不再维护模型清单。 |
| B-09 | **P1** | **代码确认** | `scheduler.py:720-769` | slow/inventory 是否执行由整表全局最大时间决定；只要一台刚成功，新增或失败服务器也被延期，inventory 最坏再等一天。 | 按 `(server_id, kind)` 保存最近成功/失败时间，逐服务器调度并做上限退避。 |
| B-10 | **P2** | **代码确认** | `metrics.py:23-53`、`enterprise.py:326-340,429-443`、`cockpit.py:345-355` | 多处用 `max(collected_at)` 回表；同一时间两行会都命中，字典随机覆盖。数据库无 `(server_id,collected_at)` 唯一约束。 | 使用 `max(id)` 作为最终 tie-breaker，或引入采集批次/序号及唯一约束。 |
| B-11 | **P2** | **代码确认** | `api/cockpit.py:64-123` | GPU 功率按服务器去重，但网络/磁盘仍把同服务器同分钟重复采样直接求和，手动采集或间隔小于 60 秒会制造假峰值。 | 所有 rate 指标先按 `(minute,server_id)` 求均值/设备和，再做集群求和。 |
| B-12 | **P2** | **代码确认** | `frontend/src/views/Servers.vue:235-265,326-339` | 编辑框故意将已存用户名/密码留空，但底部“测试连接”仍把空值发往临时测试接口，常规编辑场景测试失败；列表上的“测试”才使用已存凭据。 | 编辑态未输入新凭据时调用 `/servers/{id}/test`；输入新凭据时才调用临时接口，并明确提示测试哪组参数。 |
| B-13 | **P2** | **代码确认** | `frontend/src/views/Servers.vue:279-303` | “测试 IPMI”先 PUT 保存整个编辑表单，再测试；用户未点保存的其它改动已落库。 | 新增仅接收临时 BMC 参数的测试接口，或明确改名“保存并测试”并二次确认。 |
| B-14 | **P2** | **代码确认** | `Dashboard.vue:145-160`、`Cockpit.vue:487-510` | `Promise.allSettled()` 不会进入 catch；Dashboard 无论子请求是否失败都清空错误，Cockpit 只 `console.warn` 并用 0/空数组覆盖，用户会把故障当真实零值。 | 保留最后成功数据；关键请求失败显示全局 banner，次要请求显示面板级错误及时间；检查每个 settled 结果。 |
| B-15 | **P2** | **代码确认** | `api/metrics.py:242-276` | 实时进程缓存只以 `server_id` 为 key，不包含 `sort`；10 秒内先请求 CPU 排序，再请求内存排序会得到旧排序。Viewer 还能用该 GET 触发真实 SSH。 | key 改为 `(server_id,sort)`；增加每用户/服务器速率限制；考虑只由后台采集并缓存。 |
| B-16 | **P2** | **代码确认** | `scheduler.py:821-909` | 每次只聚合“上一个完整小时”。服务停机数小时后恢复不会回补缺失小时，长期报表永久断档。 | 记录最后聚合水位，循环回补至上一完整小时；保证幂等并限制单次回补量。 |
| B-17 | **P2** | **代码确认** | `status_page.py:131-225` | 公共页每台服务器约 3 次查询，并把每日 count 展开成 `[status] * n`；缓存没有 single-flight。多服务器/365 天和缓存刚过期并发时会成为 DB 热点。 | 2～3 条集合查询完成全部聚合；直接保存 ok/total 计数；增加 single-flight 和网关缓存/限流。 |
| B-18 | **P2** | **代码确认** | `Layout.vue:93-104`、`Cockpit.vue:490-496` | 侧栏未恢复告警最多取 100 条、驾驶舱最多取 20 条后直接用数组长度当总数，超限后 KPI 固定在 100/20。 | 后端分页返回 `{items,total}` 或独立 count 接口；徽标与列表查询分离。 |
| B-19 | **P3** | **代码确认** | `schemas.py:284-288`、`api/metrics.py:291-295` | signal 只过滤为字母数字，没有允许集合；会产生不可预测的远端 kill 错误和审计内容。当前没有发现 shell 元字符注入路径。 | 使用 `Literal["TERM","KILL","HUP","INT"]` 并映射为固定信号编号。 |
| B-20 | **P3** | **代码确认** | `frontend/src/composables.js:68-71` | 模块加载时直接 `JSON.parse(localStorage.user)`；值被扩展、旧版本或人工损坏后，SPA 在挂载前崩溃。 | try/catch 解析并清理非法会话；增加损坏 localStorage 启动测试。 |
| B-21 | **P3** | **构建/代码确认** | `main.js:3-23`、多张表固定 `max-height`、GPU 卡片全量渲染 | 前端生产构建成功，但主 JS 约 1.26 MB、公共块约 520 KB并触发 Vite 告警；大量 GPU 时页面/DOM 可无限增长，部分移动端布局与可访问性不足。 | Element Plus/图标按需加载，拆 vendor chunk；GPU 矩阵虚拟化/分页；统一 `100dvh + min-height:0 + 面板内滚动`；补键盘与移动端回归。 |

## 四、已确认的正向安全措施

| 项目 | 结果 |
|---|---|
| API 授权边界 | 已逐路由检查：除登录、健康检查、已发布状态页和 SPA 外，业务 API 均要求登录；管理写操作大多要求 Admin。未发现直接未认证写接口。 |
| SQL 注入 | 业务查询使用 SQLAlchemy ORM/参数绑定；Bandit 对 `import_sqlite.py` 的动态表名告警来自内部固定表名调用，未发现外部输入到 SQL 的可利用链。 |
| 前端 XSS 基线 | 未发现 `v-html`、`innerHTML`、`document.write`、`eval/new Function`；Vue 插值默认转义。CSP、`nosniff`、`DENY`、Referrer/Permissions Policy 均已生效。 |
| Webhook 基线 | 已强制 HTTPS、拒绝私网/回环/保留地址并禁止跳转；仅剩 S-14 的 DNS TOCTOU。 |
| SSH 命令注入 | 采集脚本是代码内常量；进程 PID/nice 为整数，signal 会过滤非字母数字。Bandit 的 Paramiko 告警经人工检查未发现当前参数可拼入 shell 元字符，但仍应采用 B-19 白名单。 |
| 凭据存储 | SSH/BMC 密码和私钥使用 Fernet 密文保存；API 不返回密文本身。当前 `.env` 为 0600，真实 `SECRET_KEY` 长度 64且不是占位符，MySQL 密码也不同于源码默认值。 |
| 当前管理员 | 只读核验 3 个活动管理员，均未使用公开默认密码 `admin123`。未执行生产登录尝试。 |
| 容器身份 | 当前 Web 容器以非 root `appuser` 运行且非 privileged；问题在于 bind mount 权限和其它硬化项，而不是进程直接以 root 运行。 |
| MCP 写边界 | 8 个工具实际只调用登录和 GET API，设置了 `readOnlyHint`；默认校验 TLS、远程明文 HTTP 默认拒绝、响应上限 16 MiB、无 stdout 凭据日志。 |
| Secret 扫描 | 当前 Git 跟踪文件未发现真实私钥/Token；命中项为公开默认值、文档占位符、测试假值和 UI placeholder。历史对象路径未发现曾提交 `.env`/PEM/私钥文件。 |
| 前端/MCP 依赖 | `pnpm audit --prod` 与 MCP 独立 requirements 的 `pip-audit` 均为 0 个已知漏洞。 |

## 五、MCP 专项数据边界

“只读”只代表不会修改 GPU Monitor，不代表返回数据适合发送给外部模型。当前 MCP 可能把以下内容交给 MCP 宿主，再由宿主发送给云端模型：

| 数据 | 当前行为 | 建议默认策略 |
|---|---|---|
| 服务器 IP/端口、名称、标签、状态原因 | `_server_public()` 直接返回 | 默认只返回匿名 ID/别名；地址需显式 opt-in |
| GPU UUID、序列号、PCI 地址 | 详细 GPU 工具直接返回 | 默认哈希/截断；硬件定位模式才开放 |
| 进程用户名、命令行 | 最多 100/120 字符返回 | 默认去掉 command/user，仅返回 PID 与资源；管理员显式开启 |
| 告警消息、确认人、分派人 | 直接返回 | 脱敏人员标识和自由文本 |
| Viewer 密码 | 写在宿主本地 MCP 配置的环境变量中 | 配置文件 0600；优先短期服务 Token/系统 keyring，不使用真人账号 |

上线 MCP 前应明确：模型供应商、数据保留策略、训练/日志使用条款、跨境要求及内部数据分类。建议新增 `GPU_MONITOR_MCP_PRIVACY_MODE=strict` 并默认启用字段脱敏。

## 六、验证记录

| 检查 | 结果 | 说明 |
|---|---|---|
| `python3 -m compileall -q backend/app backend/scripts mcp_server` | 通过 | Python 语法可编译 |
| `docker compose config --quiet` | 通过 | Compose 可解析，但不代表配置安全 |
| `pnpm build` | 通过，有体积警告 | 2295 modules；主块/公共块超过 500 KB |
| MCP 单元测试 | 通过 | 6/6；含 TLS/HTTP限制、JWT 重登、只读注解、输出边界 |
| 隔离 FastAPI + SQLite 接口测试 | **复现 6 项问题** | 设置部分提交、旧数据在线、禁用仍在线、Viewer 获得 BMC 用户名、删除残留 IPMI、改密新 Token 401 |
| 隔离 JWT 身份重用测试 | **复现** | 模拟重启清空内存撤销后，旧同名 Token 可解析为重建后的管理员账号 |
| `pip-audit -r backend/requirements.txt` | **失败：17 条/4 包** | 直接可达的重点为表单与 Range DoS；并非 17 条全部适用于本系统 |
| `pip-audit -r mcp_server/requirements.txt` | 通过 | 0 个已知漏洞 |
| `pnpm audit --prod` | 通过 | 0 个已知漏洞 |
| Bandit | 无 High；4 个 Medium | 动态 SQL/Paramiko/TLS opt-out 已人工复核；主要是需约束的设计告警 |
| Ruff | 失败：30 项 | 22 项可自动修复，主要是未使用导入、导入位置与歧义变量 |
| detect-secrets | 有命中，均已人工分类 | 公开默认值/示例/测试/placeholder；未发现真实已跟踪凭据 |
| 当前容器 | Docker 显示 healthy | 但健康检查过浅；日志 12 小时 8483 条 SSH host-key 持久化告警 |
| 当前 MySQL | 只读连接成功 | MySQL 8.0.39；无 TLS；`gpumon@%` 对单库 ALL；3306 监听所有接口 |
| 当前秘密与默认口令 | 部分通过 | `.env` 0600、强密钥、DB 密码非源码默认、活动管理员非 `admin123` |
| OS/镜像 CVE | **未完成** | 环境无 Trivy/Grype/Docker Scout；apt 模拟显示 0 个普通升级不等同于 CVE 扫描 |
| 正式后端测试/前端测试/CI | **缺失** | 仓库只有 MCP 测试；本报告的隔离测试尚未沉淀为版本化测试 |

## 七、建议整改顺序与上线门槛

| 阶段 | 必做内容 | 验收标准 |
|---|---|---|
| 立即隔离 | 8300/3306 只允许本机、VPN或指定管理网；未修前不要开放 MCP 给云端模型；保留当前强密码/密钥 | 从非允许网段无法连接 8300/3306；边界扫描只看到 TLS 入口 |
| Gate 1：安全阻断 | S-01～S-07：主机密钥 fail-closed、TLS、依赖升级、移除默认凭据、DB 隔离、持久会话版本、登录输入/限流 | `pip-audit` 无可利用高危；所有新服务器都生成 0600 host key；变更密钥会被拒绝；改密/登出/重启后旧 Token 均无效 |
| Gate 2：敏感数据 | S-08～S-15：进程 argv、Viewer DTO、MCP 脱敏、SSH/BMC 最小权限、Webhook DNS pin、备份权限/恢复策略 | Viewer/MCP 响应不含 BMC 用户、完整 argv、地址/序列号（除非显式授权）；恢复演练不会重启退役服务器 |
| Gate 3：核心正确性 | B-01～B-11：事务、新鲜度、禁用口径、卡时/能耗、功率、FK、逐机调度、最新行 tie、趋势去重 | 对应自动化用例全绿；8 卡和不同采集间隔下报表量纲正确；停止采集后在阈值内转 stale |
| Gate 4：生产工程 | readiness、资源限制、日志轮转、`.dockerignore`、可复现构建、CI、备份/恢复、监控告警 | CI 全绿；镜像 CVE 扫描无未豁免 High/Critical；readiness 能发现 DB/schema/scheduler/目录故障；完成一次恢复演练 |
| 上线验证 | 反向代理/TLS、权限矩阵、负载/DoS、故障注入、移动端/大规模 GPU、审计追踪 | 书面验收记录和回滚方案齐全；至少 24～72 小时预生产运行无错误/告警洪泛 |

如果当前 8300 或 3306 曾经暴露给不可信网络，应在修复入口后评估日志并轮换管理员、数据库、Viewer/MCP、SSH/BMC 凭据。**不要直接轮换现有 `SECRET_KEY`**；它同时用于解密 SSH/BMC 密文，未完成 S-19 的密钥拆分与迁移前直接轮换会让全部已存凭据失效。

## 八、上游依据

- [python-multipart 官方 Security Advisories](https://github.com/Kludex/python-multipart/security/advisories)
- [Starlette 官方 Security Advisories](https://github.com/Kludex/starlette/security/advisories)
- [Starlette Release Notes（含 FileResponse Range 修复）](https://github.com/Kludex/starlette/blob/main/docs/release-notes.md)
- [FastAPI 官方 Release Notes](https://fastapi.tiangolo.com/release-notes/)
- [FastAPI PyPI 当前发布信息](https://pypi.org/project/fastapi/)
- [Paramiko SHA-1 Advisory](https://github.com/advisories/ghsa-r374-rxx8-8654)
- [OWASP API4:2023 Unrestricted Resource Consumption](https://owasp.org/API-Security/editions/2023/en/0xa4-unrestricted-resource-consumption/)

## 九、审查边界

- 没有进行破坏性渗透、密码爆破、真实 Token 窃取、真实 SSH/BMC 中间人或远程命令测试。
- 没有调用生产写接口；生产数据库检查均为只读元数据/聚合检查。
- 没有检查宿主机外部防火墙、上游交换机/云安全组、DNS、证书私钥保管和组织级账号流程。
- 没有可用的容器 OS CVE 扫描器；上线前仍需对最终镜像运行 Trivy/Grype 等，并人工处置结果。
- 未审计 MCP 所连接的具体模型供应商和数据处理条款；该项必须由实际部署方补充。
