<template>
  <div class="cockpit">
    <el-alert v-if="loadError" type="error" :closable="false" show-icon style="margin-bottom:12px"
              :title="`数据加载失败：${loadError}，正在重试`" />

    <div class="toolbar dashboard-toolbar">
      <el-button v-if="isAdminSession()" type="primary" :icon="Refresh" :loading="refreshing" @click="refreshNow">立即采集</el-button>
      <el-button :icon="DataLine" @click="load()">刷新数据</el-button>
      <span style="color:var(--csub);font-size:13px" v-if="lastUpdate">上次采集: {{ fmtTime(lastUpdate) }}</span>
    </div>

    <el-row :gutter="14" class="dashboard-kpis">
      <el-col :span="6" :xs="{ span: 12 }"><el-card class="stat-card dashboard-stat-card">
        <div class="stat-value">{{ stats.servers_online }}/{{ stats.servers_total }}</div>
        <div class="stat-label">在线服务器</div>
        <div class="stat-sub">异常 {{ stats.servers_error }} · 禁用 {{ stats.servers_disabled }}</div>
      </el-card></el-col>
      <el-col :span="6" :xs="{ span: 12 }"><el-card class="stat-card dashboard-stat-card">
        <div class="stat-value">{{ stats.gpus_total }}</div>
        <div class="stat-label">GPU 总数</div>
        <div class="stat-sub">平均利用率 {{ stats.avg_gpu_util }}%</div>
      </el-card></el-col>
      <el-col :span="6" :xs="{ span: 12 }"><el-card class="stat-card dashboard-stat-card">
        <div class="stat-value dashboard-memory-value"><span>{{ fmtSizeMB(stats.gpu_mem_used_mb) }}</span><i>/</i><span>{{ fmtSizeMB(stats.gpu_mem_total_mb) }}</span></div>
        <div class="stat-label">GPU 显存</div>
        <div class="stat-sub">{{ gpuMemPct }}% 已用</div>
      </el-card></el-col>
      <el-col :span="6" :xs="{ span: 12 }"><el-card class="stat-card dashboard-stat-card">
        <div class="stat-value">{{ stats.avg_cpu_percent }}%</div>
        <div class="stat-label">平均 CPU 使用率</div>
        <div class="stat-sub">内存 {{ fmtSizeMB(stats.mem_used_mb) }} / {{ fmtSizeMB(stats.mem_total_mb) }}</div>
      </el-card></el-col>
    </el-row>

    <el-card class="page-card" style="margin-top:14px">
      <template #header>服务器状态</template>
      <el-table class="desktop-only" :data="rows" v-loading="loading" @row-click="goDetail" style="cursor:pointer">
        <el-table-column label="状态" width="60">
          <template #default="{ row }">
            <span v-if="!row.server_enabled" class="tag-dot dot-off" title="已禁用"></span>
            <span v-else-if="row.status === 'ok'" class="tag-dot dot-ok" title="正常"></span>
            <span v-else class="tag-dot dot-err" :title="row.error"></span>
          </template>
        </el-table-column>
        <el-table-column prop="server_name" label="名称" min-width="120">
          <template #default="{ row }">
            <el-link type="primary" @click.stop="goDetail(row)">{{ row.server_name }}</el-link>
          </template>
        </el-table-column>
        <el-table-column prop="hostname" label="主机名" min-width="110" show-overflow-tooltip />
        <el-table-column label="CPU" width="130">
          <template #default="{ row }">
            <el-progress :percentage="pct(row.cpu_percent)" :color="cpuColor(row.cpu_percent)" :stroke-width="10" />
          </template>
        </el-table-column>
        <el-table-column label="内存" width="130">
          <template #default="{ row }">
            <el-progress :percentage="memPct(row)" :color="cpuColor(memPct(row))" :stroke-width="10" />
          </template>
        </el-table-column>
        <el-table-column label="GPU" width="130">
          <template #default="{ row }">
            <el-progress v-if="!row.is_cpu_server && row.gpu_count" :percentage="pct(row.avgGpuUtil)" :color="cpuColor(row.avgGpuUtil)" :stroke-width="10" />
            <span v-else-if="row.is_cpu_server" style="color:var(--csub)">CPU 服务器</span>
            <span v-else style="color:var(--csub)">无</span>
          </template>
        </el-table-column>
        <el-table-column label="GPU 显存" width="150">
          <template #default="{ row }">
            <span v-if="row.gpu_count" class="mono">{{ fmtSizeMB(row.gpuMemUsed) }} / {{ fmtSizeMB(row.gpuMemTotal) }}</span>
            <span v-else style="color:var(--csub)">—</span>
          </template>
        </el-table-column>
        <el-table-column label="磁盘" width="120">
          <template #default="{ row }">
            <span class="mono">{{ (row.disk_used_gb ?? 0).toFixed(0) }} / {{ (row.disk_total_gb ?? 0).toFixed(0) }} GB</span>
          </template>
        </el-table-column>
        <el-table-column label="采集时间" width="150">
          <template #default="{ row }">{{ fmtTime(row.collected_at) }}</template>
        </el-table-column>
      </el-table>
      <div class="mobile-only dashboard-mobile-list" v-loading="loading">
        <div v-if="rows.length" class="mobile-card-list">
          <article v-for="row in rows" :key="row.server_id" class="mobile-data-card dashboard-server-card" role="button" tabindex="0" @click="goDetail(row)" @keyup.enter="goDetail(row)">
            <div class="mobile-data-card__head">
              <div class="dashboard-server-name">
                <span class="tag-dot" :class="!row.server_enabled ? 'dot-off' : row.status === 'ok' ? 'dot-ok' : 'dot-err'"></span>
                <b>{{ row.server_name }}</b>
                <span>{{ row.hostname || '—' }}</span>
              </div>
              <el-tag size="small" :type="!row.server_enabled ? 'info' : row.status === 'ok' ? 'success' : 'danger'">
                {{ !row.server_enabled ? '已禁用' : row.status === 'ok' ? '正常' : '异常' }}
              </el-tag>
            </div>
            <div class="dashboard-resource-grid">
              <div><span>CPU</span><b>{{ pct(row.cpu_percent) }}%</b><el-progress :percentage="pct(row.cpu_percent)" :show-text="false" :stroke-width="6" :color="cpuColor(row.cpu_percent)" /></div>
              <div><span>内存</span><b>{{ memPct(row) }}%</b><el-progress :percentage="memPct(row)" :show-text="false" :stroke-width="6" :color="cpuColor(memPct(row))" /></div>
              <div><span>GPU</span><b>{{ row.is_cpu_server ? 'CPU 服务器' : row.gpu_count ? pct(row.avgGpuUtil) + '%' : '无' }}</b><el-progress v-if="!row.is_cpu_server && row.gpu_count" :percentage="pct(row.avgGpuUtil)" :show-text="false" :stroke-width="6" :color="cpuColor(row.avgGpuUtil)" /></div>
              <div><span>磁盘</span><b>{{ (row.disk_used_gb ?? 0).toFixed(0) }} / {{ (row.disk_total_gb ?? 0).toFixed(0) }} GB</b></div>
            </div>
            <div v-if="row.gpu_count" class="dashboard-gpu-memory">显存 {{ fmtSizeMB(row.gpuMemUsed) }} / {{ fmtSizeMB(row.gpuMemTotal) }}</div>
          </article>
        </div>
        <el-empty v-else description="暂无服务器数据" :image-size="56" />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh, DataLine } from '@element-plus/icons-vue'
import api from '../api'
import { fmtSizeMB, fmtTime, pct } from '../format'
import { isAdminSession } from '../composables'

const router = useRouter()
const loading = ref(false)
const refreshing = ref(false)
const loadError = ref('')
const stats = ref({})
const metrics = ref([])
const servers = ref([])
const lastUpdate = computed(() => metrics.value.length ? metrics.value.map(m => m.collected_at).sort().pop() : null)
let timer = null

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
    gpuMemTotal
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

function cpuColor(v) {
  if (v == null) return 'var(--cprimary)'
  if (v >= 90) return 'var(--cred)'
  if (v >= 70) return 'var(--cyellow)'
  return 'var(--cgreen)'
}

function goDetail(row) {
  router.push(`/servers/${row.server_id}`)
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const [a, b, c] = await Promise.allSettled([
      api.get('/metrics/dashboard'),
      api.get('/metrics/latest'),
      api.get('/servers')
    ])
    if (a.status === 'fulfilled') stats.value = a.value.data
    if (b.status === 'fulfilled') metrics.value = b.value.data
    if (c.status === 'fulfilled') servers.value = c.value.data
    const failed = [a, b, c].filter(result => result.status === 'rejected').length
    loadError.value = failed ? `${failed} 项数据暂时不可用，页面保留已加载内容` : ''
  } catch (e) {
    loadError.value = e.friendlyMessage || '加载失败'
  } finally {
    if (!silent) loading.value = false
  }
}

let refreshTimer = null

async function refreshNow() {
  refreshing.value = true
  try {
    await api.post('/metrics/refresh')
    ElMessage.success('已触发采集，稍后刷新查看')
    refreshTimer = setTimeout(load, 6000)
  } catch (e) {
    if (e.response?.status === 409) ElMessage.info('采集进行中')
    else ElMessage.error(e.friendlyMessage || '触发失败')
  } finally {
    refreshing.value = false
  }
}

onMounted(() => {
  load()
  timer = setInterval(() => load(true), 30000)
})
onUnmounted(() => {
  clearInterval(timer)
  if (refreshTimer) clearTimeout(refreshTimer)
})
</script>

<style scoped>
.dashboard-stat-card { min-height: 116px; }
.dashboard-memory-value { display: flex; align-items: baseline; justify-content: center; gap: 7px; }
.dashboard-memory-value i { color: var(--csub); font-size: .7em; font-style: normal; }
.dashboard-mobile-list { min-height: 120px; }
.dashboard-server-card { cursor: pointer; }
.dashboard-server-name { min-width: 0; display: grid; grid-template-columns: auto 1fr; align-items: center; column-gap: 5px; }
.dashboard-server-name .tag-dot { grid-row: 1 / 3; }
.dashboard-server-name b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dashboard-server-name span:last-child { color: var(--csub); font: 11px ui-monospace, monospace; }
.dashboard-resource-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.dashboard-resource-grid > div { min-width: 0; padding: 9px; border-radius: 8px; background: var(--cpanel2); }
.dashboard-resource-grid span { display: block; margin-bottom: 4px; color: var(--csub); font-size: 11px; }
.dashboard-resource-grid b { display: block; min-height: 19px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.dashboard-resource-grid :deep(.el-progress) { margin-top: 6px; }
.dashboard-gpu-memory { margin-top: 10px; color: var(--csub); font: 11px ui-monospace, monospace; }
@media (max-width: 768px) {
  .dashboard-toolbar > span { flex-basis: 100%; order: 3; }
  .dashboard-kpis { row-gap: 10px; }
  .dashboard-stat-card { min-height: 105px; }
  .dashboard-memory-value { flex-direction: column; align-items: center; gap: 0; font-size: 17px; line-height: 1.15; }
  .dashboard-memory-value i { display: none; }
  .dashboard-kpis :deep(.el-card__body) { padding: 16px 10px; }
}
</style>
