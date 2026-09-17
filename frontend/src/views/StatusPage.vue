<template>
  <a-config-provider :theme="statusThemeConfig">
    <main class="status-page" :class="themeClass">
      <div class="status-container">
        <header class="status-header">
          <div class="status-title">
            <a-badge v-if="data?.overall" :status="data.overall.all_operational ? 'success' : 'error'" />
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
          description="请稍后重试，或联系平台管理员确认监控服务是否可用。"
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
          :type="data.overall?.all_operational ? 'success' : 'error'"
          show-icon
          :message="data.overall?.all_operational ? '全部系统正常运行' : '部分系统异常'"
          :description="`${data.overall?.servers_online || 0}/${data.overall?.servers_total || 0} 台服务器在线`"
        />

        <section v-if="data?.published" class="server-list" aria-label="服务器状态">
          <a-card v-for="server in data.servers" :key="server.id" size="small" class="server-status-card">
            <template #title>
              <div class="server-title">
                <a-badge :status="server.online ? 'success' : 'error'" />
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
                <a-tag :color="server.online ? 'green' : 'red'">{{ server.online ? '正常' : '离线' }}</a-tag>
              </div>
            </template>

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
          数据实时来自 SSH 探测 · 更新于 {{ fmtTime(data.generated_at) }}
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
import { fmtTime } from '../format'

const route = useRoute()
const preview = computed(() => route.query.preview === '1')
const data = ref(null)
const loaded = ref(false)
const loadError = ref(false)
let timer = null

const selectedTheme = computed(() => {
  const configured = data.value?.theme || 'auto'
  if (configured === 'dark' || configured === 'light') return configured
  return document.documentElement.classList.contains('dark') ? 'dark' : 'light'
})
const themeClass = computed(() => `status-page--${selectedTheme.value}`)
const statusThemeConfig = computed(() => ({
  algorithm: selectedTheme.value === 'dark' ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
}))

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
  loadError.value = false
  try {
    let response
    if (preview.value) {
      try {
        response = await axios.get('/api/status-page/preview', { withCredentials: true })
      } catch (error) {
        if (error?.response?.status === 401 || error?.response?.status === 403) {
          response = await axios.get('/api/status-public')
        } else {
          throw error
        }
      }
    } else {
      response = await axios.get('/api/status-public')
    }
    data.value = response.data
  } catch {
    data.value = null
    loadError.value = true
  } finally {
    loaded.value = true
  }
}

onMounted(() => {
  load()
  timer = setInterval(() => {
    if (!document.hidden) load()
  }, 60000)
})
onUnmounted(() => clearInterval(timer))
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
