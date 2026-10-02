<template>
  <a-config-provider :theme="statusThemeConfig">
    <main class="status-page" :class="themeClass">
      <div class="status-container">
        <header class="status-header">
          <div class="status-title">
            <a-badge v-if="data?.overall" :status="overallState === 'online' ? 'success' : overallState === 'offline' ? 'error' : 'warning'" />
            <h1>{{ data?.title || '服务状态' }}</h1>
          </div>
          <p>{{ data?.description || '集群可用性与 GPU 资源状态' }}</p>
        </header>

        <a-card v-if="!loaded" aria-live="polite">
          <a-skeleton active :paragraph="{ rows: 3 }" />
        </a-card>

        <a-alert
          v-else-if="loadError"
          type="error"
          show-icon
          message="暂时无法获取服务状态"
          :description="loadError"
        >
          <template #action><a-button size="small" danger @click="load">重新加载</a-button></template>
        </a-alert>

        <a-alert
          v-if="preview"
          type="warning"
          show-icon
          banner
          message="预览模式：仅管理员可见，当前配置可能尚未对外发布。"
        />

        <a-result
          v-if="loaded && !loadError && !data?.published"
          status="info"
          title="此状态页未发布"
          sub-title="管理员可在「系统设置 → 公开状态页」中开启。"
        />

        <a-alert
          v-if="data?.published"
          :type="overallState === 'online' ? 'success' : overallState === 'offline' ? 'error' : 'warning'"
          show-icon
          :message="overallState === 'online' ? '全部系统正常运行' : overallState === 'offline' ? '部分系统异常' : '部分系统状态未知，等待有效探测'"
          :description="`${data.overall?.servers_online || 0}/${data.overall?.servers_total || 0} 台服务器具有有效在线探测`"
        />

        <section v-if="data?.published" class="server-list" aria-label="服务器状态">
          <a-card v-for="server in data.servers" :key="server.id" size="small" class="server-status-card">
            <template #title>
              <div class="server-title">
                <a-badge :status="serverState(server) === 'online' ? 'success' : serverState(server) === 'offline' ? 'error' : 'warning'" />
                <b>{{ server.name }}</b>
                <a-tag :color="server.server_type === 'cpu' ? undefined : 'blue'">
                  {{ server.server_type === 'cpu' ? 'CPU' : 'GPU' }}
                </a-tag>
              </div>
            </template>
            <template #extra>
              <div class="server-meta">
                <span v-if="data.show_latency && server.online">{{ server.avg_latency_ms }} ms</span>
                <b>{{ server.uptime_30d == null ? '—' : server.uptime_30d + '%' }}</b>
                <a-tag :color="serverState(server) === 'online' ? 'green' : serverState(server) === 'offline' ? 'red' : 'orange'">{{ stateLabel(server) }}</a-tag>
              </div>
            </template>

            <p class="server-last-check">最近 SSH 探测：{{ server.last_check ? fmtTime(server.last_check) : '暂无探测' }}<span v-if="serverState(server) === 'stale'">（数据已过期）</span></p>

            <div v-if="data.show_gpu && server.gpus?.length" class="gpu-list">
              <a-card v-for="gpu in server.gpus" :key="gpu.index" size="small" class="gpu-card">
                <div class="gpu-heading">
                  <b>GPU {{ gpu.index }}</b>
                  <span :title="gpu.name">{{ gpu.name }}</span>
                </div>
                <div class="gpu-metrics">
                  <a-progress
                    type="circle"
                    :percent="gpu.util"
                    :size="62"
                    :stroke-color="gpuColor(gpu.util)"
                  />
                  <div class="gpu-memory">
                    <span>显存占用 {{ gpu.mem_pct }}%</span>
                    <a-progress
                      :percent="gpu.mem_pct"
                      :show-info="false"
                      size="small"
                      :stroke-color="gpuColor(gpu.mem_pct)"
                    />
                  </div>
                </div>
              </a-card>
            </div>

            <div class="uptime-bars" aria-label="可用率历史">
              <a-tooltip v-for="(day, index) in server.history" :key="index" :title="historyTip(day)">
                <div class="uptime-bar" :class="barClass(day)"></div>
              </a-tooltip>
            </div>
            <div class="uptime-axis">
              <span>{{ axisLabel(server.history, 'first') }}</span>
              <span>{{ axisLabel(server.history, 'mid') }}</span>
              <span>今天</span>
            </div>
          </a-card>
        </section>

        <footer v-if="data?.footer" class="status-footer">{{ data.footer }}</footer>
        <footer v-if="data?.generated_at" class="status-footer secondary">
          状态查询时间：{{ fmtTime(data.generated_at) }} · 服务器最近探测时间见各卡片
        </footer>
      </div>
    </main>
  </a-config-provider>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { theme as antTheme } from 'ant-design-vue'
import axios from 'axios'
import api from '../api'
import { fmtTime } from '../format'
import { useTheme } from '../theme'

const route = useRoute()
const preview = computed(() => route.query.preview === '1')
const data = ref(null)
const loaded = ref(false)
const loadError = ref('')
const { resolved } = useTheme()
const refreshing = ref(false)
let timer = null
let disposed = false

const selectedTheme = computed(() => {
  const configured = data.value?.theme || 'auto'
  if (configured === 'dark' || configured === 'light') return configured
  return resolved.value
})
const themeClass = computed(() => `status-page--${selectedTheme.value}`)
const statusThemeConfig = computed(() => ({
  algorithm: selectedTheme.value === 'dark' ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
}))

function serverState(server) {
  return server.state || (server.online ? 'online' : 'offline')
}

function stateLabel(server) {
  return { online: '正常', offline: '异常', stale: '探测已过期', unknown: '暂无探测' }[serverState(server)] || '状态未知'
}

const overallState = computed(() => {
  const servers = data.value?.servers || []
  if (!servers.length) return 'unknown'
  if (servers.some(server => serverState(server) === 'offline')) return 'offline'
  return servers.every(server => serverState(server) === 'online') ? 'online' : 'unknown'
})

function gpuColor(value) {
  if (value >= 90) return '#ff4d4f'
  if (value >= 50) return '#1677ff'
  return '#52c41a'
}

function barClass(day) {
  if (day.uptime == null) return 'none'
  if (day.uptime >= 99.5) return 'ok'
  if (day.uptime >= 90) return 'warning'
  return 'error'
}

function historyTip(day) {
  if (day.uptime == null) return `${day.date}：无数据`
  return `${day.date}：${day.uptime}% 可用（${day.n} 次探测）`
}

function axisLabel(history, position) {
  if (!history?.length) return ''
  const index = position === 'first' ? 0 : Math.floor(history.length / 2)
  return history[index]?.date?.slice(5) || ''
}

async function load() {
  if (refreshing.value || disposed) return
  refreshing.value = true
  loadError.value = ''
  try {
    let response
    if (preview.value) {
      const token = route.query.draft
      if (token) {
        if (typeof token !== 'string' || !/^[a-zA-Z0-9-]{1,80}$/.test(token)) throw new Error('预览草稿标识无效，请重新打开预览。')
        const stored = sessionStorage.getItem(`gpumon:status-preview:${token}`)
        if (!stored) throw new Error('预览草稿不存在或已关闭，请从配置页重新打开预览。')
        response = await api.post('/status-page/preview', JSON.parse(stored))
      } else {
        response = await axios.get('/api/status-page/preview', { withCredentials: true, timeout: 30000 })
      }
    } else {
      response = await axios.get('/api/status-public', { timeout: 30000 })
    }
    if (!disposed) data.value = response.data
  } catch (error) {
    if (disposed) return
    // An unavailable monitor cannot assert that an old green snapshot is live.
    data.value = null
    loadError.value = error?.response?.status === 401 || error?.response?.status === 403
      ? '预览需要管理员登录和相应权限，请从系统设置重新打开。'
      : error?.friendlyMessage || error?.message || '请稍后重试，或联系平台管理员。'
  } finally {
    refreshing.value = false
    if (!disposed) loaded.value = true
  }
}

onMounted(() => {
  load()
  timer = setInterval(() => {
    if (!document.hidden) load()
  }, 60000)
})
onUnmounted(() => {
  disposed = true
  clearInterval(timer)
})
</script>

<style scoped>
.status-page {
  min-height: 100vh;
  padding: 48px 20px 40px;
}
.status-page--light {
  --ctext: rgba(0, 0, 0, .88);
  --csub: rgba(0, 0, 0, .45);
  background: #f5f5f5;
  color: var(--ctext);
}
.status-page--dark {
  --ctext: rgba(255, 255, 255, .85);
  --csub: rgba(255, 255, 255, .45);
  background: #141414;
  color: var(--ctext);
}
.status-container {
  max-width: 880px;
  margin: 0 auto;
  display: grid;
  gap: 16px;
}
.status-header {
  padding: 8px 0 12px;
  text-align: center;
}
.status-title {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}
.status-title h1 {
  margin: 0;
  font-size: 28px;
  line-height: 1.4;
}
.status-header p {
  margin: 6px 0 0;
  color: var(--csub);
  font-size: 13px;
}
.server-list {
  display: grid;
  gap: 12px;
}
.server-title,
.server-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}
.server-meta {
  color: var(--csub);
  font-size: 12px;
}
.server-meta b { color: var(--ctext); font-variant-numeric: tabular-nums; }
.server-last-check { margin: 0 0 12px; color: var(--csub); font-size: 12px; }
.gpu-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 8px;
  margin-bottom: 16px;
}
.gpu-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 12px;
}
.gpu-heading span {
  min-width: 0;
  overflow: hidden;
  color: var(--csub);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.gpu-metrics {
  display: flex;
  align-items: center;
  gap: 14px;
}
.gpu-memory { min-width: 0; flex: 1; }
.gpu-memory > span {
  display: block;
  margin-bottom: 7px;
  color: var(--csub);
  font-size: 11px;
}
.uptime-bars {
  height: 32px;
  display: flex;
  align-items: stretch;
  gap: 3px;
}
.uptime-bar {
  min-width: 3px;
  flex: 1;
  border-radius: 2px;
}
.uptime-bar.ok { background: #52c41a; }
.uptime-bar.warning { background: #faad14; }
.uptime-bar.error { background: #ff4d4f; }
.uptime-bar.none { background: #d9d9d9; opacity: .5; }
.uptime-axis {
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
  color: var(--csub);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.status-footer {
  margin-top: 4px;
  color: var(--csub);
  text-align: center;
  font-size: 12px;
}
.status-footer.secondary { margin-top: -10px; }

@media (max-width: 560px) {
  .status-page { padding: 28px 12px 24px; }
  .status-title h1 { font-size: 23px; }
  .server-status-card :deep(.ant-card-head) { padding-inline: 12px; }
  .server-status-card :deep(.ant-card-head-wrapper) { align-items: flex-start; flex-direction: column; gap: 8px; }
  .server-status-card :deep(.ant-card-extra) { margin-inline-start: 0; }
  .server-status-card :deep(.ant-card-body) { padding: 12px; }
  .server-meta { flex-wrap: wrap; }
  .gpu-list { grid-template-columns: 1fr; }
}
</style>
