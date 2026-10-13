<template>
  <div class="dashboard-page">
    <a-alert
      v-if="loadError"
      type="error"
      show-icon
      :message="`数据加载失败：${loadError}，正在重试`"
      class="load-alert"
    />

    <div class="toolbar dashboard-toolbar">
      <a-button v-if="isAdminSession()" type="primary" :loading="refreshing" @click="refreshNow">
        <template #icon><ThunderboltOutlined /></template>
        立即采集
      </a-button>
      <a-button :loading="loading" @click="load()">
        <template #icon><ReloadOutlined /></template>
        刷新数据
      </a-button>
      <span v-if="lastUpdate" class="last-update">上次采集：{{ fmtTime(lastUpdate) }}</span>
    </div>

    <a-row :gutter="[16, 16]" class="kpi-row dashboard-kpis">
      <a-col :xs="12" :lg="6">
        <a-card>
          <a-statistic title="在线服务器" :value="`${stats.servers_online || 0}/${stats.servers_total || 0}`" />
          <div class="stat-sub">异常 {{ stats.servers_error || 0 }} · 禁用 {{ stats.servers_disabled || 0 }}</div>
        </a-card>
      </a-col>
      <a-col :xs="12" :lg="6">
        <a-card>
          <a-statistic title="GPU 总数" :value="stats.gpus_total || 0" />
          <div class="stat-sub">平均利用率 {{ stats.avg_gpu_util || 0 }}%</div>
        </a-card>
      </a-col>
      <a-col :xs="12" :lg="6">
        <a-card>
          <a-statistic title="GPU 显存" :value="fmtSizeMB(stats.gpu_mem_used_mb)" />
          <div class="stat-sub">总计 {{ fmtSizeMB(stats.gpu_mem_total_mb) }} · 已用 {{ gpuMemPct }}%</div>
          <a-progress :percent="gpuMemPct" :show-info="false" size="small" />
        </a-card>
      </a-col>
      <a-col :xs="12" :lg="6">
        <a-card>
          <a-statistic title="平均 CPU 使用率" :value="stats.avg_cpu_percent || 0" suffix="%" />
          <div class="stat-sub">内存 {{ fmtSizeMB(stats.mem_used_mb) }} / {{ fmtSizeMB(stats.mem_total_mb) }}</div>
        </a-card>
      </a-col>
    </a-row>

    <a-card title="服务器状态" class="server-card">
      <a-table
        class="desktop-only"
        :data-source="rows"
        :loading="loading"
        :pagination="false"
        :custom-row="customRow"
        :scroll="{ x: 1120 }"
        row-key="server_id"
        size="middle"
      >
        <a-table-column title="状态" :width="90">
          <template #default="{ record: row }">
            <a-badge :status="statusBadge(row)" :text="statusText(row)" />
          </template>
        </a-table-column>
        <a-table-column data-index="server_name" title="名称" :width="150" ellipsis>
          <template #default="{ record: row }">
            <a-button type="link" size="small" class="server-link" :title="row.server_name" @click.stop="goDetail(row)">
              {{ row.server_name }}
            </a-button>
          </template>
        </a-table-column>
        <a-table-column data-index="hostname" title="主机名" :width="140" ellipsis />
        <a-table-column title="CPU" :width="140">
          <template #default="{ record: row }">
            <a-progress :percent="pct(row.cpu_percent)" :stroke-color="cpuColor(row.cpu_percent)" size="small" />
          </template>
        </a-table-column>
        <a-table-column title="内存" :width="140">
          <template #default="{ record: row }">
            <a-progress :percent="memPct(row)" :stroke-color="cpuColor(memPct(row))" size="small" />
          </template>
        </a-table-column>
        <a-table-column title="GPU" :width="140">
          <template #default="{ record: row }">
            <a-progress
              v-if="!row.is_cpu_server && row.gpu_count"
              :percent="pct(row.avgGpuUtil)"
              :stroke-color="cpuColor(row.avgGpuUtil)"
              size="small"
            />
            <span v-else class="secondary-text">{{ row.is_cpu_server ? 'CPU 服务器' : '无' }}</span>
          </template>
        </a-table-column>
        <a-table-column title="GPU 显存" :width="160">
          <template #default="{ record: row }">
            <div v-if="row.gpu_count" :title="`${fmtSizeMB(row.gpuMemUsed)} / ${fmtSizeMB(row.gpuMemTotal)}`">
              <a-progress :percent="gpuMemPctForRow(row)" :stroke-color="cpuColor(gpuMemPctForRow(row))" size="small" />
            </div>
            <span v-else class="secondary-text">—</span>
          </template>
        </a-table-column>
        <a-table-column title="磁盘" :width="160">
          <template #default="{ record: row }">
            <span class="mono">{{ (row.disk_used_gb ?? 0).toFixed(0) }} / {{ (row.disk_total_gb ?? 0).toFixed(0) }} GB</span>
          </template>
        </a-table-column>
        <a-table-column title="采集时间" :width="170">
          <template #default="{ record: row }">{{ fmtTime(row.collected_at) }}</template>
        </a-table-column>
      </a-table>

      <a-spin wrapper-class-name="mobile-only dashboard-mobile-list" :spinning="loading">
        <div v-if="rows.length" class="mobile-card-list">
          <article
            v-for="row in rows"
            :key="row.server_id"
            class="mobile-data-card dashboard-server-card"
            role="button"
            tabindex="0"
            @click="goDetail(row)"
            @keyup.enter="goDetail(row)"
          >
            <div class="mobile-data-card__head">
              <div class="dashboard-server-name">
                <a-badge :status="statusBadge(row)" />
                <b>{{ row.server_name }}</b>
                <span>{{ row.hostname || '—' }}</span>
              </div>
              <a-tag :color="statusTagColor(row)">{{ statusText(row) }}</a-tag>
            </div>
            <div class="dashboard-resource-grid">
              <div>
                <span>CPU</span><b>{{ pct(row.cpu_percent) }}%</b>
                <a-progress :percent="pct(row.cpu_percent)" :show-info="false" size="small" :stroke-color="cpuColor(row.cpu_percent)" />
              </div>
              <div>
                <span>内存</span><b>{{ memPct(row) }}%</b>
                <a-progress :percent="memPct(row)" :show-info="false" size="small" :stroke-color="cpuColor(memPct(row))" />
              </div>
              <div>
                <span>GPU</span><b>{{ row.is_cpu_server ? 'CPU 服务器' : row.gpu_count ? pct(row.avgGpuUtil) + '%' : '无' }}</b>
                <a-progress
                  v-if="!row.is_cpu_server && row.gpu_count"
                  :percent="pct(row.avgGpuUtil)"
                  :show-info="false"
                  size="small"
                  :stroke-color="cpuColor(row.avgGpuUtil)"
                />
              </div>
              <div>
                <span>GPU 显存</span><b>{{ row.gpu_count ? gpuMemPctForRow(row) + '%' : '无' }}</b>
                <a-progress
                  v-if="row.gpu_count"
                  :percent="gpuMemPctForRow(row)"
                  :show-info="false"
                  size="small"
                  :stroke-color="cpuColor(gpuMemPctForRow(row))"
                />
              </div>
            </div>
            <div class="dashboard-gpu-memory">
              磁盘 {{ (row.disk_used_gb ?? 0).toFixed(0) }} / {{ (row.disk_total_gb ?? 0).toFixed(0) }} GB
            </div>
          </article>
        </div>
        <a-empty v-else description="暂无服务器数据" />
      </a-spin>
    </a-card>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { App as AntApp } from 'ant-design-vue'
import { ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons-vue'
import api from '../api'
import { fmtSizeMB, fmtTime, pct } from '../format'
import { isAdminSession } from '../composables'
import { createRequestScope } from '../requestState'

const router = useRouter()
const { message } = AntApp.useApp()
const loading = ref(false)
const refreshing = ref(false)
const loadError = ref('')
const stats = ref({})
const metrics = ref([])
const servers = ref([])
const lastUpdate = computed(() => metrics.value.length ? metrics.value.map(m => m.collected_at).sort().pop() : null)
let timer = null
let refreshTimer = null
let busy = false
const requests = createRequestScope()

const rows = computed(() => metrics.value.map(m => {
  const server = servers.value.find(s => s.id === m.server_id)
  const gpus = m.gpus || []
  const utils = gpus.map(g => g.utilization || 0)
  const avgGpuUtil = utils.length ? utils.reduce((a, b) => a + b, 0) / utils.length : 0
  const gpuMemUsed = gpus.reduce((a, g) => a + (g.mem_used_mb || 0), 0)
  const gpuMemTotal = gpus.reduce((a, g) => a + (g.mem_total_mb || 0), 0)
  return {
    ...m,
    server_name: server?.name || `#${m.server_id}`,
    server_enabled: server?.enabled ?? true,
    is_cpu_server: (server?.server_type ?? 'gpu') === 'cpu',
    avgGpuUtil: Math.round(avgGpuUtil * 10) / 10,
    gpuMemUsed,
    gpuMemTotal,
  }
}))

const gpuMemPct = computed(() => {
  if (!stats.value.gpu_mem_total_mb) return 0
  return Math.round(stats.value.gpu_mem_used_mb / stats.value.gpu_mem_total_mb * 1000) / 10
})

function memPct(row) {
  if (!row.mem_total_mb) return 0
  return pct(row.mem_used_mb / row.mem_total_mb * 100)
}

function gpuMemPctForRow(row) {
  if (!row.gpuMemTotal) return 0
  return pct(row.gpuMemUsed / row.gpuMemTotal * 100)
}

function cpuColor(value) {
  if (value == null) return 'var(--cprimary)'
  if (value >= 90) return 'var(--cred)'
  if (value >= 70) return 'var(--cyellow)'
  return 'var(--cgreen)'
}

function statusText(row) {
  if (!row.server_enabled) return '已禁用'
  return row.status === 'ok' ? '正常' : '异常'
}

function statusBadge(row) {
  if (!row.server_enabled) return 'default'
  return row.status === 'ok' ? 'success' : 'error'
}

function statusTagColor(row) {
  if (!row.server_enabled) return undefined
  return row.status === 'ok' ? 'green' : 'red'
}

function goDetail(row) {
  router.push(`/servers/${row.server_id}`)
}

function customRow(row) {
  return {
    onClick: () => goDetail(row),
    style: { cursor: 'pointer' },
  }
}

async function load(silent = false) {
  if (busy || document.hidden) return
  busy = true
  const request = requests.begin()
  if (!silent) loading.value = true
  try {
    const [a, b, c] = await Promise.allSettled([
      api.get('/metrics/dashboard', { signal: request.signal }),
      api.get('/metrics/latest?slim=1', { signal: request.signal }),
      api.get('/servers', { signal: request.signal }),
    ])
    if (!request.current()) return
    if (a.status === 'fulfilled') stats.value = a.value.data
    if (b.status === 'fulfilled') metrics.value = b.value.data
    if (c.status === 'fulfilled') servers.value = c.value.data
    const failed = [a, b, c].filter(result => result.status === 'rejected').length
    loadError.value = failed ? `${failed} 项数据暂时不可用，页面保留已加载内容` : ''
  } catch (e) {
    if (!request.current()) return
    loadError.value = e.friendlyMessage || '加载失败'
  } finally {
    busy = false
    if (request.current()) loading.value = false
  }
}

async function refreshNow() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await api.post('/metrics/refresh')
    message.success('已触发采集，稍后刷新查看')
    refreshTimer = setTimeout(load, 6000)
  } catch (e) {
    if (e.response?.status === 409) message.info('采集进行中')
    else message.error(e.friendlyMessage || '触发失败')
  } finally {
    refreshing.value = false
  }
}

function onVisibilityChange() { if (!document.hidden) load(true) }
onMounted(() => {
  document.addEventListener('visibilitychange', onVisibilityChange)
  load()
  timer = setInterval(() => {
    if (!document.hidden) load(true)
  }, 30000)
})
onUnmounted(() => {
  requests.dispose()
  document.removeEventListener('visibilitychange', onVisibilityChange)
  clearInterval(timer)
  if (refreshTimer) clearTimeout(refreshTimer)
})
</script>

<style scoped>
.load-alert { margin-bottom: 12px; }
.last-update { color: var(--csub); font-size: 13px; }
.stat-sub { margin-top: 6px; }
.dashboard-kpis :deep(.ant-statistic-content) { font-variant-numeric: tabular-nums; }
.dashboard-kpis .stat-sub { min-height: 22px; }
.server-card { margin-top: 16px; }
.server-link { padding: 0; }
.secondary-text { color: var(--csub); }
.dashboard-mobile-list { min-height: 120px; }
.dashboard-server-card { cursor: pointer; }
.dashboard-server-name {
  min-width: 0;
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: center;
  column-gap: 6px;
}
.dashboard-server-name :deep(.ant-badge) { grid-row: 1 / 3; }
.dashboard-server-name b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dashboard-server-name span:last-child { color: var(--csub); font: 11px ui-monospace, monospace; }
.dashboard-resource-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.dashboard-resource-grid > div {
  min-width: 0;
  padding: 10px;
  border-radius: 8px;
  background: var(--cpanel2);
}
.dashboard-resource-grid span { display: block; margin-bottom: 4px; color: var(--csub); font-size: 11px; }
.dashboard-resource-grid b { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.dashboard-resource-grid :deep(.ant-progress) { margin-top: 6px; }
.dashboard-gpu-memory { margin-top: 10px; color: var(--csub); font: 11px ui-monospace, monospace; }

@media (max-width: 768px) {
  .dashboard-toolbar > span { flex-basis: 100%; order: 3; }
  :deep(.ant-card-body) { padding: 16px 12px; }
  :deep(.ant-statistic-content) { font-size: 20px; }
}
</style>
