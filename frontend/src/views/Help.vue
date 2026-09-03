<template>
  <div class="help-page cockpit">
    <section class="help-hero">
      <div class="hero-copy">
        <div class="eyebrow">GPU MONITOR · INTEGRATION GUIDE</div>
        <h1>让 AI 安全地读取 GPU 集群状态</h1>
        <p>
          内置 MCP Server 复用平台现有 API、JWT 权限与缓存，让 Codex、Claude Desktop、
          Cursor 等 MCP 宿主查询 GPU 状态、趋势、进程、风险和告警。
        </p>
        <div class="hero-tags">
          <el-tag type="success" effect="dark" round>只读工具</el-tag>
          <el-tag effect="plain" round>stdio 本地传输</el-tag>
          <el-tag type="info" effect="plain" round>官方 MCP SDK 2.1.1</el-tag>
          <el-tag type="warning" effect="plain" round>viewer 最小权限</el-tag>
        </div>
      </div>
      <div class="endpoint-card">
        <div class="endpoint-label">当前平台地址</div>
        <code>{{ monitorUrl }}</code>
        <el-button type="primary" plain size="small" @click="copyText(monitorUrl, '平台地址')">
          复制地址
        </el-button>
        <div class="endpoint-note">MCP 与浏览器不在同一台机器时，请换成 MCP 进程可访问的地址。</div>
      </div>
    </section>

    <div class="help-layout">
      <aside class="help-toc" aria-label="帮助文档目录">
        <el-card shadow="never">
          <div class="toc-title">本页目录</div>
          <button v-for="item in toc" :key="item.id" type="button" @click="scrollTo(item.id)">
            <span class="toc-index">{{ item.index }}</span>
            <span>{{ item.label }}</span>
          </button>
        </el-card>
      </aside>

      <main class="help-content">
        <section id="overview" class="doc-section">
          <el-card class="doc-card" shadow="never">
            <template #header>
              <div class="section-heading">
                <span class="section-number">01</span>
                <div>
                  <h2>MCP 是怎么接入的</h2>
                  <p>不重复采集，不绕过现有权限。</p>
                </div>
              </div>
            </template>

            <div class="flow" aria-label="MCP 数据流">
              <div class="flow-node">
                <strong>MCP 宿主</strong>
                <span>Codex / Claude / Cursor</span>
              </div>
              <span class="flow-arrow">→</span>
              <div class="flow-node accent">
                <strong>gpu_monitor_mcp</strong>
                <span>本地 stdio · 8 个只读工具</span>
              </div>
              <span class="flow-arrow">→</span>
              <div class="flow-node">
                <strong>GPU Monitor API</strong>
                <span>viewer JWT · 自动重新登录</span>
              </div>
              <span class="flow-arrow">→</span>
              <div class="flow-node">
                <strong>已采集数据</strong>
                <span>GPU 指标 · 风险 · 告警</span>
              </div>
            </div>

            <el-alert
              title="MCP Server 不直接连接 MySQL，也不会 SSH 到被监控服务器。"
              description="它只调用本系统已有的只读 API，因此平台中的角色权限、缓存和数据口径保持一致。"
              type="success"
              :closable="false"
              show-icon
            />
          </el-card>
        </section>

        <section id="quick-start" class="doc-section">
          <el-card class="doc-card" shadow="never">
            <template #header>
              <div class="section-heading">
                <span class="section-number">02</span>
                <div>
                  <h2>四步完成接入</h2>
                  <p>建议专门创建一个 viewer 用户供 MCP 使用。</p>
                </div>
              </div>
            </template>

            <div class="step-list">
              <article class="step-item">
                <div class="step-marker">1</div>
                <div class="step-body">
                  <h3>创建最小权限账号</h3>
                  <p>进入「用户管理」，创建角色为 <code>viewer</code> 的用户，例如 <code>mcp_viewer</code>。不要使用管理员账号。</p>
                  <el-button v-if="isAdmin" size="small" type="primary" plain @click="router.push('/users')">
                    前往用户管理
                  </el-button>
                  <el-tag v-else type="info" size="small">请联系管理员创建 viewer 用户</el-tag>
                </div>
              </article>

              <article class="step-item">
                <div class="step-marker">2</div>
                <div class="step-body">
                  <h3>安装独立 MCP 环境</h3>
                  <p>独立环境不会改变正在运行的 Web 后端依赖。</p>
                  <div class="code-block">
                    <div class="code-toolbar">
                      <span>Shell</span>
                      <button type="button" @click="copyText(installCommand, '安装命令')">复制</button>
                    </div>
                    <pre><code>{{ installCommand }}</code></pre>
                  </div>
                </div>
              </article>

              <article class="step-item">
                <div class="step-marker">3</div>
                <div class="step-body">
                  <h3>添加到 MCP 宿主</h3>
                  <p>把以下启动信息加入宿主的 MCP 配置，并替换项目路径、viewer 密码与独立 HMAC 密钥。</p>
                  <div class="code-block">
                    <div class="code-toolbar">
                      <span>JSON</span>
                      <button type="button" @click="copyText(hostConfig, 'MCP 宿主配置')">复制</button>
                    </div>
                    <pre><code>{{ hostConfig }}</code></pre>
                  </div>
                  <el-alert
                    class="inline-alert"
                    title="密码只应写入 MCP 宿主的本地环境配置，不要提交到 Git。"
                    type="warning"
                    :closable="false"
                    show-icon
                  />
                </div>
              </article>

              <article class="step-item last">
                <div class="step-marker">4</div>
                <div class="step-body">
                  <h3>重启宿主并验证</h3>
                  <p>先调用连接检查，再用自然语言查询 GPU。</p>
                  <div class="prompt-grid">
                    <button v-for="prompt in examplePrompts" :key="prompt" type="button" @click="copyText(prompt, '示例问题')">
                      <span>“{{ prompt }}”</span>
                      <small>点击复制</small>
                    </button>
                  </div>
                </div>
              </article>
            </div>
          </el-card>
        </section>

        <section id="tools" class="doc-section">
          <el-card class="doc-card" shadow="never">
            <template #header>
              <div class="section-heading">
                <span class="section-number">03</span>
                <div>
                  <h2>可用工具</h2>
                  <p>全部带有 MCP readOnlyHint，不会修改平台状态。</p>
                </div>
              </div>
            </template>

            <el-table :data="tools" class="tool-table desktop-only" stripe>
              <el-table-column prop="name" label="工具" min-width="280">
                <template #default="{ row }"><code class="tool-name">{{ row.name }}</code></template>
              </el-table-column>
              <el-table-column prop="purpose" label="用途" min-width="210" />
              <el-table-column prop="returns" label="主要返回" min-width="260" />
            </el-table>
            <div class="mobile-only tool-card-list">
              <article v-for="tool in tools" :key="tool.name" class="tool-card">
                <code class="tool-name">{{ tool.name }}</code>
                <p>{{ tool.purpose }}</p>
                <div><span>主要返回</span>{{ tool.returns }}</div>
              </article>
            </div>
          </el-card>
        </section>

        <section id="configuration" class="doc-section">
          <el-card class="doc-card" shadow="never">
            <template #header>
              <div class="section-heading">
                <span class="section-number">04</span>
                <div>
                  <h2>配置项</h2>
                  <p>环境变量由 MCP 宿主传给子进程。</p>
                </div>
              </div>
            </template>

            <div class="config-grid">
              <article v-for="item in envVars" :key="item.name" class="config-item">
                <div class="config-key">
                  <code>{{ item.name }}</code>
                  <el-tag v-if="item.required" type="danger" size="small" effect="plain">必填</el-tag>
                  <el-tag v-else type="info" size="small" effect="plain">可选</el-tag>
                </div>
                <p>{{ item.description }}</p>
                <div class="config-default">默认：<code>{{ item.default }}</code></div>
              </article>
            </div>

            <el-alert
              class="inline-alert"
              title="远程地址必须使用 HTTPS"
              description="只有解析后仍全部指向环回接口的地址可以使用 HTTP。远程明文 HTTP、关闭证书校验和 API 重定向都会被代码直接拒绝，没有绕过开关。"
              type="warning"
              :closable="false"
              show-icon
            />
          </el-card>
        </section>

        <section id="security" class="doc-section">
          <el-card class="doc-card" shadow="never">
            <template #header>
              <div class="section-heading">
                <span class="section-number">05</span>
                <div>
                  <h2>安全边界</h2>
                  <p>能读什么，以及明确不能做什么。</p>
                </div>
              </div>
            </template>

            <div class="boundary-grid">
              <div class="boundary-card allowed">
                <div class="boundary-title"><span>✓</span>允许读取</div>
                <ul>
                  <li>GPU 利用率、显存、温度、功耗与时钟</li>
                  <li>ECC、PCIe、降频原因和 24 小时风险评分</li>
                  <li>进程 PID/资源占用、历史趋势和告警事件</li>
                  <li>服务器名称与采集状态</li>
                </ul>
              </div>
              <div class="boundary-card blocked">
                <div class="boundary-title"><span>×</span>明确不提供</div>
                <ul>
                  <li>SSH/BMC 密码、私钥、管理地址及登录用户名</li>
                  <li>默认 strict 模式下的硬件序列号、主机名、标签、人员与命令行</li>
                  <li>进程 kill、renice 或任意远程命令</li>
                  <li>立即刷新采集、修改设置或管理服务器</li>
                  <li>确认、关闭、分派告警或管理用户</li>
                </ul>
              </div>
            </div>
          </el-card>
        </section>

        <section id="troubleshooting" class="doc-section">
          <el-card class="doc-card" shadow="never">
            <template #header>
              <div class="section-heading">
                <span class="section-number">06</span>
                <div>
                  <h2>验证与故障排查</h2>
                  <p>先检查连接，再定位账号、网络或数据问题。</p>
                </div>
              </div>
            </template>

            <div class="code-block compact">
              <div class="code-toolbar">
                <span>运行内置测试</span>
                <button type="button" @click="copyText(testCommand, '测试命令')">复制</button>
              </div>
              <pre><code>{{ testCommand }}</code></pre>
            </div>

            <el-collapse class="faq" accordion>
              <el-collapse-item v-for="item in troubleshooting" :key="item.title" :title="item.title">
                <p>{{ item.body }}</p>
                <code v-if="item.code">{{ item.code }}</code>
              </el-collapse-item>
            </el-collapse>
          </el-card>
        </section>

        <div class="doc-footer">
          <span>GPU Monitor MCP Server</span>
          <span>stdio · read-only · SDK 2.1.1</span>
        </div>
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { isAdminSession } from '../composables'

const router = useRouter()
const isAdmin = computed(() => isAdminSession())
const monitorUrl = window.location.origin
const projectRoot = '/path/to/gpu_monitor'

const toc = [
  { id: 'overview', index: '01', label: '工作方式' },
  { id: 'quick-start', index: '02', label: '快速接入' },
  { id: 'tools', index: '03', label: '工具清单' },
  { id: 'configuration', index: '04', label: '配置项' },
  { id: 'security', index: '05', label: '安全边界' },
  { id: 'troubleshooting', index: '06', label: '故障排查' },
]

const tools = [
  { name: 'gpu_monitor_connection_status', purpose: '检查 API 与 viewer 登录', returns: '平台状态、角色与隐私模式' },
  { name: 'gpu_monitor_list_servers', purpose: '列出 GPU 服务器', returns: '在线状态、GPU 数、利用率、显存与功耗' },
  { name: 'gpu_monitor_cluster_summary', purpose: '查看集群概况', returns: 'GPU 总数、忙闲、温度、功耗和高风险卡' },
  { name: 'gpu_monitor_get_server_gpu_info', purpose: '查看单机 GPU 明细', returns: 'ECC、PCIe、时钟、进程和风险评分' },
  { name: 'gpu_monitor_get_gpu_history', purpose: '查询 1–168 小时趋势', returns: '利用率、显存、温度、功耗和时钟序列' },
  { name: 'gpu_monitor_get_gpu_processes', purpose: '查看 GPU 计算进程资源', returns: 'PID 和 GPU 显存占用（不含用户/argv）' },
  { name: 'gpu_monitor_get_risk_analysis', purpose: '查询风险与空占', returns: '风险排行、XID/ECC 和持续空占时长' },
  { name: 'gpu_monitor_get_gpu_alerts', purpose: '查询 GPU 告警', returns: 'GPU/XID/ECC/PCIe 告警及处理状态' },
]

const envVars = [
  { name: 'GPU_MONITOR_URL', required: false, default: 'http://127.0.0.1:8300', description: 'MCP 进程能够访问的 GPU Monitor 根地址。' },
  { name: 'GPU_MONITOR_USERNAME', required: true, default: '无', description: '专用 viewer 用户名，建议使用 mcp_viewer。' },
  { name: 'GPU_MONITOR_PASSWORD', required: true, default: '无', description: 'viewer 密码，只存放在 MCP 宿主的本地环境配置中。' },
  { name: 'GPU_MONITOR_TIMEOUT', required: false, default: '15', description: '单次 API 请求超时秒数，必须大于 0 且不超过 120。' },
  { name: 'GPU_MONITOR_MCP_PRIVACY_MODE', required: false, default: 'strict', description: 'strict 默认脱敏；仅经数据治理批准后才使用 extended。' },
  { name: 'MCP_PRIVACY_HMAC_KEY', required: true, default: '无', description: 'strict 模式的硬件化名密钥；至少 32 个随机字符，禁止与其它密钥复用。' },
]

const examplePrompts = [
  '检查 GPU Monitor MCP 是否连接正常',
  '查看整个 GPU 集群当前的利用率、温度和高风险卡',
  '查看 gpu-01 每张 GPU 的 ECC、PCIe 和计算进程',
  '分析过去 24 小时 GPU 趋势，并找出持续空占显存的卡',
]

const troubleshooting = [
  {
    title: '提示 GPU_MONITOR_USERNAME 或 PASSWORD 缺失',
    body: 'MCP 宿主不会自动继承所有 shell 环境变量。请在该宿主的 MCP Server 配置中显式填写 env，并重启宿主。',
  },
  {
    title: '登录失败或提示尝试次数过多',
    body: '确认用户已启用、密码正确且角色为 viewer。连续失败会触发平台登录限速；修正配置后等待锁定期结束再试。',
  },
  {
    title: 'MCP 无法访问 127.0.0.1:8300',
    body: '127.0.0.1 指的是 MCP 进程所在机器。如果宿主运行在另一台电脑，请改成该电脑能访问的 GPU Monitor HTTPS 地址。',
  },
  {
    title: '提示拒绝 remote plain HTTP',
    body: '这是不可关闭的凭据保护机制。请为远程 GPU Monitor 配置可信 HTTPS；不要使用明文私网地址，也不要安装不受信任的根证书。',
  },
  {
    title: '手工运行后终端没有输出',
    body: '这是正常现象。stdio MCP Server 正在等待宿主通过标准输入发送协议消息；标准输出专门用于 MCP 数据帧。',
  },
  {
    title: '工具能调用，但 GPU 数据为空或过旧',
    body: '先在「服务器」和「GPU 矩阵」页面确认该机器采集正常。MCP 读取的是平台已有数据，不会自行绕过调度器重新 SSH 采集。',
  },
  {
    title: '使用一段时间后 JWT 过期',
    body: '无需人工更新 token。MCP 在收到 401 后会清除旧 token，并使用配置的 viewer 账号自动重新登录一次。',
  },
]

const installCommand = `cd ${projectRoot}
python3 -m venv .venv-mcp
.venv-mcp/bin/pip install --require-hashes -r mcp_server/requirements.lock`

const hostConfig = computed(() => JSON.stringify({
  mcpServers: {
    'gpu-monitor': {
      command: `${projectRoot}/.venv-mcp/bin/python`,
      args: ['-m', 'mcp_server.server'],
      cwd: projectRoot,
      env: {
        GPU_MONITOR_URL: monitorUrl,
        GPU_MONITOR_USERNAME: 'mcp_viewer',
        GPU_MONITOR_PASSWORD: '<替换为 viewer 密码>',
        GPU_MONITOR_MCP_PRIVACY_MODE: 'strict',
        MCP_PRIVACY_HMAC_KEY: '<替换为独立随机值>',
      },
    },
  },
}, null, 2))

const testCommand = `cd ${projectRoot}
.venv-mcp/bin/python -m pytest -q mcp_server/tests`

function scrollTo(id) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function copyText(text, label) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      textarea.remove()
    }
    ElMessage.success(`${label}已复制`)
  } catch {
    ElMessage.error('复制失败，请手动选择文本')
  }
}
</script>

<style scoped>
.help-page {
  --help-accent: var(--cprimary);
  --help-accent-soft: color-mix(in srgb, var(--cprimary) 12%, transparent);
  max-width: 1320px;
  margin: 0 auto;
}

.help-hero {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 24px;
  align-items: center;
  padding: 28px 32px;
  margin-bottom: 18px;
  overflow: hidden;
  border: 1px solid var(--cborder);
  border-radius: 14px;
  background:
    radial-gradient(circle at 85% 10%, color-mix(in srgb, var(--cpurple) 18%, transparent), transparent 38%),
    linear-gradient(135deg, var(--cpanel), var(--cpanel2));
  box-shadow: var(--cshadow);
}

.help-hero::after {
  content: '';
  position: absolute;
  right: -70px;
  bottom: -115px;
  width: 260px;
  height: 260px;
  border: 1px solid color-mix(in srgb, var(--cprimary) 25%, transparent);
  border-radius: 50%;
  pointer-events: none;
}

.hero-copy,
.endpoint-card {
  position: relative;
  z-index: 1;
}

.eyebrow {
  margin-bottom: 10px;
  color: var(--help-accent);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.13em;
}

.hero-copy h1 {
  margin: 0 0 12px;
  color: var(--ctext);
  font-size: clamp(27px, 3vw, 37px);
  line-height: 1.18;
  letter-spacing: -0.025em;
}

.hero-copy p {
  max-width: 760px;
  margin: 0;
  color: var(--csub);
  font-size: 15px;
  line-height: 1.8;
}

.hero-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
}

.endpoint-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
  padding: 20px;
  border: 1px solid color-mix(in srgb, var(--cprimary) 28%, var(--cborder));
  border-radius: 12px;
  background: color-mix(in srgb, var(--cpanel) 88%, transparent);
  backdrop-filter: blur(8px);
}

.endpoint-label {
  color: var(--csub);
  font-size: 12px;
  letter-spacing: 0.06em;
}

.endpoint-card code {
  max-width: 100%;
  overflow-wrap: anywhere;
  color: var(--ctext);
  font-size: 14px;
  font-weight: 700;
}

.endpoint-note {
  color: var(--csub);
  font-size: 12px;
  line-height: 1.6;
}

.help-layout {
  display: grid;
  grid-template-columns: 196px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.help-toc {
  position: sticky;
  top: 0;
}

.help-toc :deep(.el-card) {
  border-color: var(--cborder);
  background: var(--cpanel);
}

.help-toc :deep(.el-card__body) {
  padding: 12px;
}

.toc-title {
  padding: 7px 10px 11px;
  color: var(--csub);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.help-toc button {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--csub);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: color 0.18s ease, background 0.18s ease;
}

.help-toc button:hover,
.help-toc button:focus-visible {
  background: var(--help-accent-soft);
  color: var(--ctext);
  outline: none;
}

.toc-index {
  color: var(--help-accent);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  font-weight: 700;
}

.help-content {
  min-width: 0;
}

.doc-section {
  scroll-margin-top: 16px;
}

.doc-card {
  margin-bottom: 16px;
  border-color: var(--cborder);
  background: var(--cpanel);
}

.doc-card :deep(.el-card__header) {
  padding: 16px 20px;
  border-color: var(--cborder);
}

.doc-card :deep(.el-card__body) {
  padding: 20px;
}

.section-heading {
  display: flex;
  align-items: center;
  gap: 14px;
}

.section-number {
  display: grid;
  width: 42px;
  height: 42px;
  flex: 0 0 42px;
  place-items: center;
  border: 1px solid color-mix(in srgb, var(--cprimary) 35%, var(--cborder));
  border-radius: 10px;
  background: var(--help-accent-soft);
  color: var(--help-accent);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  font-weight: 800;
}

.section-heading h2 {
  margin: 0 0 3px;
  color: var(--ctext);
  font-size: 19px;
}

.section-heading p {
  margin: 0;
  color: var(--csub);
  font-size: 13px;
}

.flow {
  display: flex;
  align-items: stretch;
  gap: 9px;
  margin-bottom: 20px;
}

.flow-node {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  justify-content: center;
  gap: 5px;
  padding: 14px;
  border: 1px solid var(--cborder);
  border-radius: 10px;
  background: var(--cpanel2);
}

.flow-node.accent {
  border-color: color-mix(in srgb, var(--cprimary) 40%, var(--cborder));
  background: var(--help-accent-soft);
}

.flow-node strong {
  overflow-wrap: anywhere;
  color: var(--ctext);
  font-size: 13px;
}

.flow-node span {
  color: var(--csub);
  font-size: 11px;
  line-height: 1.5;
}

.flow-arrow {
  align-self: center;
  color: var(--csub);
  font-size: 17px;
}

.step-list {
  display: flex;
  flex-direction: column;
}

.step-item {
  position: relative;
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr);
  gap: 14px;
  padding-bottom: 28px;
}

.step-item:not(.last)::before {
  content: '';
  position: absolute;
  top: 36px;
  bottom: 0;
  left: 18px;
  width: 1px;
  background: var(--cborder);
}

.step-marker {
  position: relative;
  z-index: 1;
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  border: 1px solid color-mix(in srgb, var(--cprimary) 45%, var(--cborder));
  border-radius: 50%;
  background: var(--cpanel);
  color: var(--help-accent);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  font-weight: 800;
}

.step-body {
  min-width: 0;
  padding-top: 5px;
}

.step-body h3 {
  margin: 0 0 7px;
  color: var(--ctext);
  font-size: 15px;
}

.step-body > p {
  margin: 0 0 12px;
  color: var(--csub);
  font-size: 13px;
  line-height: 1.7;
}

.step-body p code,
.faq code,
.config-default code {
  padding: 2px 5px;
  border-radius: 4px;
  background: var(--cpanel2);
  color: var(--cprimary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.code-block {
  overflow: hidden;
  border: 1px solid #24324a;
  border-radius: 10px;
  background: #0b1220;
  box-shadow: 0 8px 22px rgba(2, 8, 23, 0.14);
}

.code-block.compact {
  margin-bottom: 20px;
}

.code-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid #24324a;
  background: #111b2e;
  color: #8da2c1;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.code-toolbar button {
  padding: 3px 8px;
  border: 1px solid #31425f;
  border-radius: 5px;
  background: transparent;
  color: #b9c8dc;
  cursor: pointer;
}

.code-toolbar button:hover,
.code-toolbar button:focus-visible {
  border-color: #22d3ee;
  color: #67e8f9;
  outline: none;
}

.code-block pre {
  max-height: 430px;
  margin: 0;
  overflow: auto;
  padding: 15px;
}

.code-block code {
  color: #d7e3f4;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.65;
  white-space: pre;
}

.inline-alert {
  margin-top: 14px;
}

.prompt-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 9px;
}

.prompt-grid button {
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: flex-start;
  gap: 7px;
  padding: 13px;
  border: 1px solid var(--cborder);
  border-radius: 9px;
  background: var(--cpanel2);
  color: var(--ctext);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.18s ease, transform 0.18s ease;
}

.prompt-grid button:hover,
.prompt-grid button:focus-visible {
  border-color: var(--cprimary);
  outline: none;
  transform: translateY(-1px);
}

.prompt-grid span {
  font-size: 13px;
  line-height: 1.55;
}

.prompt-grid small {
  color: var(--csub);
  font-size: 11px;
}

.tool-table {
  --el-table-border-color: var(--cborder);
  --el-table-header-bg-color: var(--cpanel2);
  --el-table-row-hover-bg-color: var(--ctable-hover);
}

.tool-name {
  color: var(--cprimary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  font-weight: 700;
}

.tool-card-list { min-width: 0; }
.tool-card {
  padding: 13px;
  border: 1px solid var(--cborder);
  border-radius: 9px;
  background: var(--cpanel2);
}
.tool-card + .tool-card { margin-top: 9px; }
.tool-card .tool-name {
  display: block;
  overflow-wrap: anywhere;
}
.tool-card p {
  margin: 7px 0 10px;
  color: var(--ctext);
  font-size: 13px;
}
.tool-card div {
  color: var(--csub);
  font-size: 12px;
  line-height: 1.55;
}
.tool-card div span {
  display: block;
  margin-bottom: 2px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .08em;
}

.config-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 11px;
}

.config-item {
  padding: 15px;
  border: 1px solid var(--cborder);
  border-radius: 10px;
  background: var(--cpanel2);
}

.config-key {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.config-key code {
  overflow-wrap: anywhere;
  color: var(--cprimary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  font-weight: 700;
}

.config-item p {
  min-height: 42px;
  margin: 10px 0;
  color: var(--csub);
  font-size: 12px;
  line-height: 1.65;
}

.config-default {
  color: var(--csub);
  font-size: 11px;
}

.boundary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.boundary-card {
  padding: 17px;
  border: 1px solid var(--cborder);
  border-radius: 10px;
  background: var(--cpanel2);
}

.boundary-card.allowed {
  border-color: color-mix(in srgb, var(--cgreen) 35%, var(--cborder));
}

.boundary-card.blocked {
  border-color: color-mix(in srgb, var(--cred) 30%, var(--cborder));
}

.boundary-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--ctext);
  font-size: 14px;
  font-weight: 700;
}

.boundary-card.allowed .boundary-title span {
  color: var(--cgreen);
}

.boundary-card.blocked .boundary-title span {
  color: var(--cred);
}

.boundary-card ul {
  margin: 13px 0 0;
  padding-left: 20px;
  color: var(--csub);
  font-size: 13px;
  line-height: 1.9;
}

.faq {
  --el-collapse-border-color: var(--cborder);
}

.faq :deep(.el-collapse-item__header) {
  background: transparent;
  color: var(--ctext);
  font-weight: 600;
}

.faq :deep(.el-collapse-item__wrap) {
  background: transparent;
}

.faq p {
  margin: 0 0 10px;
  color: var(--csub);
  font-size: 13px;
  line-height: 1.8;
}

.doc-footer {
  display: flex;
  justify-content: space-between;
  padding: 4px 4px 18px;
  color: var(--csub);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
}

@media (max-width: 1100px) {
  .help-hero {
    grid-template-columns: 1fr;
  }

  .endpoint-card {
    max-width: 560px;
  }

  .flow {
    display: grid;
    grid-template-columns: 1fr 24px 1fr;
  }

  .flow-arrow:nth-of-type(2) {
    display: none;
  }
}

@media (max-width: 860px) {
  .help-layout {
    grid-template-columns: 1fr;
  }

  .help-toc {
    position: sticky;
    top: 0;
    z-index: 5;
    min-width: 0;
  }

  .help-toc :deep(.el-card__body) {
    display: flex;
    gap: 3px;
    overflow-x: auto;
    padding: 7px;
    scrollbar-width: thin;
  }

  .toc-title {
    display: none;
  }

  .help-toc button {
    width: auto;
    min-width: max-content;
    padding: 8px 10px;
  }
}

@media (max-width: 620px) {
  .help-hero {
    gap: 18px;
    padding: 21px 17px;
    border-radius: 10px;
  }

  .hero-copy h1 {
    font-size: 25px;
    line-height: 1.25;
  }

  .hero-copy p { font-size: 13px; line-height: 1.7; }
  .endpoint-card { padding: 15px; }

  .doc-card :deep(.el-card__header),
  .doc-card :deep(.el-card__body) {
    padding: 16px;
  }

  .flow {
    grid-template-columns: 1fr;
  }

  .flow-arrow {
    transform: rotate(90deg);
    justify-self: center;
  }

  .flow-arrow:nth-of-type(2) {
    display: block;
  }

  .prompt-grid,
  .config-grid,
  .boundary-grid {
    grid-template-columns: 1fr;
  }

  .config-item p {
    min-height: 0;
  }

  .doc-footer {
    flex-direction: column;
    gap: 5px;
  }

  .code-block pre { padding: 12px; }
  .code-block code { font-size: 11px; }
}
</style>
