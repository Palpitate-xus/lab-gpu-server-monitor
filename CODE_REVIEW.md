# GPU Monitor Code Review

> 审查日期：2026-08-29  
> 审查基线：`0db5a4a` (`feat(energy): prefer IPMI-measured power, GPU sum only as fallback`)  
> 审查范围：FastAPI 后端、采集/调度、数据库与迁移、Vue/Element Plus 前端、Docker 部署、界面布局与滚动策略。  
> 本次只生成审查报告，没有修改业务代码，也没有连接现有 MySQL、SSH 主机或 BMC。

## 结论摘要

系统可以完成 Python 编译、前端生产构建和 Docker Compose 配置解析，鉴权边界、凭据加密、SSH Host Key、Webhook SSRF 防护等方面已有较好的安全意识。不过当前仍存在会影响数据正确性、登录会话和生产部署的确定性问题。建议先处理 P1，再统一改造页面的视口高度与面板内滚动。

优先级定义：

| 优先级 | 含义 |
|---|---|
| P1 | 会造成安全风险、关键功能失败或核心监控数据明显错误，应优先修复 |
| P2 | 会造成局部错误、数据残留、误导性展示或明显可用性问题 |
| P3 | 性能、工程质量、响应式、可访问性或长期维护优化 |

## 一、Bug 与后端 Code Review

| ID | 优先级 | 状态 | 位置 | 问题与证据 | 影响 | 建议 |
|---|---|---|---|---|---|---|
| BE-01 | P1 | **已复现** | `backend/app/api/users.py:103-110`、`backend/app/token_revocation.py:35-52`、`backend/app/security.py:37-45` | 修改密码先用浮点秒记录撤销时间，再签发只含整数秒 `iat` 的新 JWT；同一秒内新令牌满足 `iat < epoch`。隔离 TestClient 中修改密码返回 200，随后用响应中的新令牌访问 `/api/auth/me` 返回 401。 | 用户看到“密码已修改”，但当前会话立刻失效；同一秒重新登录也可能受影响。 | 使用持久化 `token_version`（用户表字段、JWT 中携带版本）最稳妥；至少应统一时间精度并增加自动化回归测试。 |
| BE-02 | P1 | **已复现** | `backend/app/main.py:186-232`、`backend/app/main.py:261-275` | `_set_setting()` 每写一个键就 `commit()`。隔离测试提交“合法 poll_interval + 非法 webhook URL”时接口返回 400，但 `poll_interval` 已从 60 变成 61。阈值批量更新也有同类问题。 | API 报失败却发生部分配置变更，状态与用户认知不一致。 | 先完整校验所有字段，再在一个事务里更新并只提交一次；异常时统一 rollback。 |
| BE-03 | P1 | **代码确认** | `backend/app/api/enterprise.py:267-285`、`backend/app/scheduler.py:786-807` | 利用率报表把 `ok_samples / 60` 当作 GPU 卡时，既假定采集间隔恒为 60 秒，也没有乘 GPU 数量；`idle_ratio_pct = idle_min / (ok * 60)` 的量纲也错误。比如 8 张卡整小时空占，空占为 8 卡时、总卡时却只有 1，前端总占比可达到 800%。 | “GPU 运行卡时”“空占占比”等核心报表严重失真，非 60 秒采集间隔时误差进一步扩大。 | 小时聚合中持久化 `gpu_sample_minutes`/`gpu_count_avg`；总卡时按 `sum(ok_sample_interval × gpu_count) / 3600` 计算，空占占比用空占卡分钟除以总卡分钟。 |
| BE-04 | P1 | **代码确认** | `backend/app/api/cockpit.py:136-156` | “当前功率”子查询只在 `status == ok` 的历史里找最新记录。服务器已经离线或停用时，最后一次成功采集的功率会被无限期继续相加。 | 驾驶舱显示幽灵功率，电力 KPI 可能长期高于真实值。 | 先取每台启用服务器的绝对最新记录，再要求其状态正常且采集时间不超过 `max(2×poll_interval, 固定上限)`。 |
| BE-05 | P1 | **代码确认** | `backend/app/api/status_page.py:163-223` | 公开状态页的 `online` 只检查最后一条记录状态，不检查采集时间。调度器停止、数据库只读或采集线程整体失效时，页面仍可长期显示“全部正常”。 | 对外状态页会给出错误的可用性结论。 | 加入新鲜度阈值；过期记录应显示 `unknown/stale`，整体状态不应算作正常，并在响应中暴露数据年龄。 |
| BE-06 | P1 | **代码确认** | `backend/app/scheduler.py:648-653`、`backend/app/scheduler.py:680-693` | slow/inventory 是否执行由整张表的全局最大 `collected_at` 决定，而不是逐服务器判断。只要任一服务器刚成功，新增或上轮失败的服务器就会被一起延后；inventory 最坏需再等 24 小时。 | 新服务器资产信息长时间空白；单机采集失败后不能按自身节奏重试。 | 为每台服务器分别查询/缓存最近 slow 与 inventory 时间，只调度到期目标；失败目标采用有上限的退避重试。 |
| BE-07 | P1 | **配置确认** | `.env.example:5`、`backend/app/main.py:27-33` | 启动检查只拒绝精确的 `change-me-in-production-please` 或长度小于 16 的值，但示例文件中的公开占位符 `change-me-run-openssl-rand-hex-32` 长度足够，会通过检查。 | 用户若直接复制示例但忘记替换，攻击者可伪造管理员 JWT 并解密/伪造凭据密文。 | 将示例值留空；启动时拒绝一组已知占位符，并可增加简单熵/字符检查。 |
| BE-08 | P1 | **配置确认** | `docker-compose.yml:13-21`、`backend/app/config.py:39-42` | Compose 明文强制 `INIT_ADMIN_PASSWORD=admin123`，其优先级高于 `env_file`；配置类也有相同默认值。服务同时把 8300 端口发布到所有接口。 | 首次部署存在公开默认管理员口令窗口。 | 从 Compose 删除硬编码值，要求 `.env` 显式提供强密码；默认值/占位符时拒绝创建管理员或生成一次性随机密码并仅输出一次。 |
| BE-09 | P1 | **代码确认** | `backend/app/main.py:34-43` | 数据库迁移异常被记录后继续启动。`create_all()` 不能修复已有表的缺列/类型差异，继续运行可能让 API 和调度器面对半迁移 schema。 | 产生持续 500、采集写入失败，甚至新旧代码混用导致数据损坏。 | 迁移失败必须 fail-fast；仅对被明确判定为可忽略的幂等错误容忍。健康检查应包含 schema 版本。 |
| BE-10 | P1 | **配置确认** | 项目根目录（缺少 `.dockerignore`） | 当前 Docker build context 约 257 MB，包含 243 MB `frontend/node_modules`、6.2 MB `data`、`.git` 和真实 `.env`。即使 Dockerfile 未 COPY，敏感文件仍会发送给构建后端。 | 构建慢、缓存不稳定；远程 Docker/BuildKit 场景会扩大密钥和监控数据暴露面。 | 新增 `.dockerignore`，至少排除 `.env`、`data/`、`.git/`、`**/node_modules/`、`frontend/dist/`（多阶段构建时）和缓存文件。 |
| BE-11 | P2 | **已复现** | `backend/app/api/servers.py:135-153`、`backend/app/models.py:290-315` | 删除服务器的手工清理列表遗漏 `IpmiSnapshot`。隔离数据库中删除服务器返回 200，但同一 `server_id` 的 IPMI 快照仍有 1 行。 | 长期产生孤儿数据，能耗查询仍可能读到已删除服务器的历史。 | 给 IPMI/Inventory/Health/Note 等表补正式外键 `ON DELETE CASCADE`；迁移前清理孤儿，删除接口不再维护易漏的模型列表。 |
| BE-12 | P2 | **代码确认** | `backend/app/api/metrics.py:61-95` | Dashboard 虽统计了禁用数，却没有在在线、异常、CPU/GPU/内存汇总前跳过禁用服务器；禁用前最后一条成功记录仍会进入统计。 | 在线数量和资源总量可能同时包含“已禁用”设备，口径自相矛盾。 | 明确定义 total/enabled/disabled 口径；资源 KPI 只聚合启用且数据新鲜的服务器。 |
| BE-13 | P2 | **代码确认** | `backend/app/api/cockpit.py:301-320`、`frontend/src/views/Cockpit.vue:55,67-76` | 每日能耗无论当天实际过去多久，都用 `mean_w × 24h`，却在 UI 标为“今日电量/近 7 天合计”；历史小时聚合的 `coverage` 又按 1440 个分钟样本作分母，完整 24 个小时行也只约 2%。 | 当日电量被外推成全天估算，覆盖率提示错误，合计与电费具有误导性。 | 历史日按每小时 `W×1h` 积分；当天按采样间隔积分或明确标为“全天预测”；覆盖率按期望小时/分钟粒度分别计算。 |
| BE-14 | P2 | **代码确认** | `backend/app/api/cockpit.py:64-121` | 注释称同服务器同分钟重复采样会先平均，但网络和磁盘实际只是 append 后直接求和，只有 GPU 功率做了 `*_by_srv` 去重。手动采集或间隔小于 60 秒时趋势会被倍增。 | 网络/磁盘吞吐趋势出现假峰值。 | 像 GPU 功率一样按 `(minute, server_id)` 先平均；磁盘先按服务器求设备和，再做服务器级去重。 |
| BE-15 | P2 | **代码确认** | `backend/app/api/status_page.py:142-203` | 公开状态页对每台服务器分别执行总计、latest、每日聚合查询（约 `1 + 3N`），并把每日聚合计数扩展成 `[status] * n` 列表。365 天、多服务器时内存和查询次数都很高。 | 公共免登录接口容易成为数据库热点；缓存失效后的首个请求延迟明显。 | 用 2～3 条集合查询一次聚合全部服务器；直接保存每日 ok/total 数量，不展开状态数组；增加并发 single-flight。 |
| BE-16 | P2 | **代码确认** | `backend/app/api/metrics.py:23-41`、`backend/app/api/enterprise.py:328-340` 等 | “按 `max(collected_at)` 回表”在同一服务器同一时间存在两行时会返回多行；字典推导随机覆盖，`/metrics/latest` 也可能重复。模型没有 `(server_id, collected_at)` 唯一约束。 | 手动与定时采集碰撞时，最新状态不确定，可能选中成功或失败中的任意一条。 | 以 `max(id)` 作为最终 tie-breaker，或增加采集批次/序列并建立唯一约束。 |
| BE-17 | P2 | **代码确认** | `backend/app/api/metrics.py:291-295`、`backend/app/schemas.py:284-288` | signal 仅过滤为字母数字，不限制允许集合；管理员可传入语义不受控的 signal 字符串，远端 `kill` 行为依赖系统解析。 | 可能产生不可预测的远端操作和不清晰的审计记录。 | Schema 使用 `Literal["TERM", "KILL", "HUP", "INT"]`；后端建立 signal-to-number 白名单。 |
| BE-18 | P2 | **部署确认** | `Dockerfile.multistage:10-13`、`backend/app/scheduler.py:948-956` | 默认 Dockerfile 安装 `ipmitool`，多阶段 Dockerfile 却只安装 `libffi-dev`。文档推荐多阶段镜像，但该镜像会静默禁用 IPMI 周期。 | 同一项目的两种构建方式功能不一致，带外监控不可用。 | 两个运行时镜像共享同一系统依赖安装段，并为 `ipmitool_available()` 增加容器 smoke test。 |
| BE-19 | P2 | **代码确认** | `frontend/src/views/Layout.vue:105-111`、`backend/app/api/auth.py` | 前端“退出登录”只清 localStorage，后端没有 logout/JTI revoke 接口；`token_revocation.py` 的注释声称支持 logout，但实现未接入路由。 | 被复制的 JWT 在 2 小时内仍有效；用户主动退出并不能终止服务端会话。 | 新增 `/api/auth/logout`，解析当前 JWT 后撤销 jti；前端先调用接口，再清本地会话。 |
| BE-20 | P3 | **静态检查** | `backend/app/` | `ruff check backend/app` 报 30 项：22 个可自动清理的未使用导入，以及未使用变量、导入位置和歧义变量名。 | 增加噪声并掩盖真正的静态问题；当前没有 CI 门禁。 | 增加 `pyproject.toml` Ruff 配置，清理存量问题后在 CI 执行 `ruff check`。 |

## 二、前端功能、样式与布局

| ID | 优先级 | 状态 | 位置 | 问题与表现 | 优化方案 |
|---|---|---|---|---|---|
| FE-01 | P1 | **代码确认** | `frontend/src/views/Servers.vue:235-265,326-334` | 编辑服务器时故意把用户名和凭据留空表示“保持不变”，但弹窗底部“测试连接”把这些空值发给临时测试接口，而不是使用已存凭据，因此常规编辑场景测试必然失败。 | 编辑态默认调用 `/servers/{id}/test`；只有用户确实填写了新凭据时，才使用临时测试接口。 |
| FE-02 | P2 | **代码确认** | `frontend/src/views/Servers.vue:279-299` | “测试 IPMI”会先 `PUT` 保存整个编辑表单，再发测试请求。用户尚未点击“保存”，其它未确认改动就已经落库。 | 新增只接收临时 BMC 参数的测试接口；或明确改为“保存并测试”并二次确认。测试动作不应有隐藏持久化副作用。 |
| FE-03 | P2 | **代码确认** | `frontend/src/views/Dashboard.vue:145-160` | `Promise.allSettled()` 永远不会进入 catch；代码无论有多少子请求失败都清空 `loadError`。页面可能混合旧数据、零值和新数据，却显示正常。 | 检查每个 settled 结果；关键请求失败时保留旧值并显示部分失败 banner，全部失败时抛错。 |
| FE-04 | P2 | **代码确认** | `frontend/src/views/Cockpit.vue:487-510`、`frontend/src/composables.js:18-31` | `loadAll()` 吞掉所有子请求失败并正常返回，导致 `usePoll` 的 `error` 永远为空；模板顶部错误提示基本不会出现。 | 返回结构化 panel errors，或在关键接口失败时 throw；次要面板显示局部错误/重试而不是静默置零。 |
| FE-05 | P2 | **代码确认** | `frontend/src/views/Cockpit.vue:348,490-496`、`frontend/src/views/Layout.vue:94-99` | 驾驶舱只请求 20 条事件后把数组长度当未恢复告警总数，超过 20 条时 KPI 固定显示 20；侧栏同理最多取 100 条。 | 后端提供 `/alerts/events/count?open_only=true` 或分页响应 `{items,total}`，徽标与列表分开查询。 |
| FE-06 | P1 | **布局问题** | `frontend/src/views/Cockpit.vue:94-197,556-568`、`frontend/src/cockpit.css:333-357` | 驾驶舱主区左侧 GPU 矩阵与右侧“趋势 + 排行”共享一行并强制 stretch。GPU 少时左面板内部下方大面积空白；GPU 多时左侧把整行无限撑高，右侧下方又出现空白。 | 主工作区设置统一的视口相对高度（如 `clamp(480px, 60dvh, 680px)`）；左右列都 `min-height:0`，GPU 矩阵和排行在各自面板内 `overflow:auto`，下方模块始终紧接主区。 |
| FE-07 | P1 | **布局问题** | `frontend/src/views/Cockpit.vue:135-163`、`frontend/src/views/GpuMatrix.vue:38-78,186-190` | 驾驶舱和 GPU 矩阵页都渲染全部服务器/GPU 卡片，没有最大高度、分页或虚拟列表。规模增长后页面会无限变长，DOM 也线性增长。 | 驾驶舱只展示摘要/前 N 台并提供“查看全部”；完整矩阵使用固定可用高度的滚动容器 + 虚拟列表，或分页（建议每页 48/96 卡）。 |
| FE-08 | P2 | **布局问题** | `frontend/src/styles.css:3-26`、`frontend/src/views/Layout.vue:2-51,178-181` | 外壳只设置 `height:100%`，嵌套 flex 容器缺少显式 `min-height:0/min-width:0`。浏览器/组件内容变化时，滚动可能从主区泄漏到 body，固定头部与侧栏的可靠性不足。 | 使用 `100dvh` 作为应用壳高度；给内层 `.el-container`、`.dark-main` 和页面 flex 子项加 `min-height:0; min-width:0`，只允许 `.dark-main` 或指定面板滚动。 |
| FE-09 | P2 | **布局问题** | `frontend/src/views/Servers.vue:19`、`Users.vue:11`、`Reports.vue:35`、`GpuAnalysis.vue:54`、`Settings.vue:64,120` | 主表格使用 300/420/560/640px 等固定 `max-height`。大屏中表格下方留下大量空白，小屏中又可能超出可用高度并产生主区 + 表格双滚动。 | 页面用 `display:flex; flex-direction:column; min-height:100%`；主卡 `flex:1; min-height:0`；表格高度用 `calc(100dvh - header - toolbar - padding)`，次级小表保留合理 max-height。 |
| FE-10 | P2 | **响应式问题** | `frontend/src/views/Alerts.vue:16-97` | 规则与事件固定为 10/24、14/24 两列，没有 `xs/sm` 断点；手机上仍挤在同一行。 | `:xs="24" :sm="24" :md="10/14"`，移动端规则卡和事件卡上下排列；筛选条允许换行。 |
| FE-11 | P2 | **响应式问题** | `frontend/src/views/ServerDetail.vue:116-237,300-319,411-486,496-500,581-598` | 多处 12/12、16/8、6/6/6/6 列未设置小屏断点，GPU 卡、网络/磁盘、资产和 KPI 在手机上会严重压缩。 | 所有内容列统一补 `xs=24`；KPI 小屏 `xs=12`；描述列表在窄屏改 1 列，工具条折行。 |
| FE-12 | P2 | **响应式问题** | `frontend/src/views/Servers.vue:75`、`Alerts.vue:99`、`Users.vue:47,75`、`Settings.vue:130` | 弹窗固定宽 420～580px，没有 `max-width` 或移动端宽度，窄屏可能横向溢出。 | 统一 `width="min(92vw, 580px)"`（或 CSS 变量）；弹窗 body 设 `max-height:70dvh; overflow:auto`，footer 固定。 |
| FE-13 | P2 | **响应式问题** | `frontend/src/views/Cockpit.vue:7-23`、`GpuAnalysis.vue:3-13`、`ServerDetail.vue:6-26` | 顶部标题和多组按钮放在不换行的内层 flex 中；768px 以下虽隐藏侧栏，但这些工具条仍会横向溢出。 | 提取 `.page-heading/.page-actions`，允许 wrap；移动端让 actions 占满下一行，低优先级文字/更新时间可隐藏。 |
| FE-14 | P2 | **空白状态** | `frontend/src/views/GpuMatrix.vue:38-78`、`Cockpit.vue:27-263` | 首次加载时矩阵页既没有卡片也没有 skeleton；驾驶舱则先展示一组“0/—”，视觉上像真实数据或中间空白。 | 每个主面板设置稳定 `min-height`，加载时展示 skeleton，空数据展示 `el-empty + 下一步操作`，错误时保留上次成功数据并标注时间。 |
| FE-15 | P3 | **性能确认** | `frontend/src/main.js:3-8,17-23`、前端构建输出 | 全量引入 Element Plus 并注册全部图标。生产构建主 JS 约 1,259 KB，另一个公共块约 520 KB，Vite 给出 >500 KB 警告。 | 使用按需自动导入或显式导入组件/图标；将 Vue、Element Plus、ECharts 拆 vendor chunk，并检查 gzip 后首屏预算。 |
| FE-16 | P3 | **可访问性** | `frontend/src/views/Cockpit.vue:83-91,117-160`、`GpuMatrix.vue:39-75` | 多个可点击 `div` 只有鼠标行为，没有键盘焦点、Enter/Space 事件或语义标签；状态也较依赖颜色。 | 使用 button/router-link 语义，增加 `aria-label`、focus-visible 样式，并用图标/文字共同表达状态。 |

## 三、推荐的“填满视口 + 面板内滚动”布局标准

以下规则可直接解决“中间不能空、内容不能无限长、长内容必须滚动”的目标：

| 区域 | 推荐约束 | 预期效果 |
|---|---|---|
| 应用壳 | `height: 100dvh; overflow: hidden` | body 不滚动，头部和侧栏稳定 |
| 内层容器 | 所有 flex/grid 中间层设置 `min-height: 0; min-width: 0` | 内容不会把父容器强行撑开 |
| 主内容 | `.dark-main { min-height:0; overflow:auto; }` | 普通详情页仍可整页滚动 |
| 列表页 | 页面和主卡使用纵向 flex，主卡 `flex:1; min-height:0` | 表格自动吃满剩余高度，不在大屏留下中部/底部空白 |
| 主表格 | `height: calc(100dvh - 实际头部与工具栏高度)` | 表头固定、表体内部滚动，页面不无限长 |
| 驾驶舱主区 | 固定为 `clamp(480px, 60dvh, 680px)`，左右面板等高 | 中间区块边界对齐，没有一列空一大截 |
| GPU/排行/告警面板 | `min-height:0; overflow:auto; scrollbar-gutter:stable` | 内容多时在面板内滚动，少时面板仍填满 |
| 全量 GPU 矩阵 | 虚拟列表或分页，固定滚动视口 | 避免数百卡片造成长页面与大 DOM |
| 移动端 | 单列布局；弹窗不超过 `92vw/70dvh` | 无横向溢出，操作区可达 |
| Loading/Empty/Error | 同一面板保持相同最小高度，分别显示 skeleton、empty、error | 加载或无数据时中间不出现“空洞” |

建议页面层级只保留一个主要纵向滚动区；只有表格、GPU 矩阵、排行等明确的长列表使用内部滚动。避免主内容、卡片和表格同时出现三个纵向滚动条。

## 四、验证记录

| 检查项 | 结果 | 备注 |
|---|---|---|
| `python3 -m compileall -q backend/app` | 通过 | Python 源码可编译 |
| `npm run build` | 通过，有警告 | Vite 成功构建；主包与公共块超过 500 KB |
| `docker compose config` | 通过 | 配置可解析；同时确认默认管理员口令被 Compose 硬编码 |
| 隔离 FastAPI + 临时 SQLite smoke test | 部分失败，已定位 | 确认修改密码新 JWT 401、设置 400 仍部分提交、删除服务器残留 IPMI 行 |
| SQLite 全量 migration | 通过 | 临时库成功应用当前 SQLite migrations |
| `ruff check backend/app` | 失败（30 项） | 主要是未使用导入/变量及少量风格问题 |
| 自动化测试目录/脚本 | 未发现 | `frontend/package.json` 只有 dev/build/preview；仓库无 tests 目录 |
| 真实 MySQL、SSH、IPMI 端到端 | 未执行 | 为避免影响现有监控数据与远端主机；相关结论均标记为代码/配置确认 |

## 五、建议实施顺序

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| 1 | BE-01～BE-10：令牌、报表公式、数据新鲜度、调度、默认密钥/口令、迁移和 `.dockerignore` | 对应单元/接口测试通过；过期数据不再显示在线或计入当前功率 |
| 2 | BE-11～BE-19 与 FE-01～FE-05 | 删除无孤儿、配置事务原子、测试按钮无隐藏副作用、错误与告警总数准确 |
| 3 | FE-06～FE-14：统一视口布局、固定主区高度、表格/矩阵内部滚动、响应式 | 1366×768、1920×1080、390×844 三种视口无中部空洞、无横向溢出、无无限长列表 |
| 4 | FE-15～FE-16、BE-20、测试与 CI | 前端 chunk 达到预算；Ruff、后端测试、前端组件/E2E 测试进入 CI |

建议优先补的自动化用例：密码修改后新令牌可立即使用；设置更新全成或全败；1/8 GPU、30/60/120 秒采集间隔下的卡时公式；过期/失败记录的在线与功率判断；删除服务器的全部关联表清理；100+ GPU 矩阵的滚动和移动端布局。
