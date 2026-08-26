<template>
  <div class="cockpit" v-loading="loading">
    <div class="toolbar">
      <el-page-header @back="$router.push('/servers')" :content="server?.name || '...'" />
      <div style="display:flex;gap:10px;align-items:center">
        <el-tag v-if="metric?.status === 'ok'" type="success">正常</el-tag>
        <el-tag v-else-if="metric" type="danger">采集异常</el-tag>
        <el-button size="small" :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <template v-if="metric">
      <el-alert v-if="metric.status !== 'ok'" :title="`采集失败: ${metric.error}`" type="error" show-icon :closable="false" style="margin-bottom:14px" />

      <!-- ===== btop-style overview stats ===== -->
      <el-row :gutter="14">
        <el-col :span="6"><el-card class="stat-card">
          <div class="stat-value" :style="{color: utilColor(metric.cpu_percent)}">{{ metric.cpu_percent }}%</div>
          <div class="stat-label">CPU ({{ metric.cpu_count }} 核 {{ fmtFreq(metric.cpu_freq_avg) }})</div>
          <div class="stat-sub">{{ metric.cpu_model || '—' }}</div>
        </el-card></el-col>
        <el-col :span="6"><el-card class="stat-card">
          <div class="stat-value">{{ fmtSizeMB(metric.mem_used_mb) }} / {{ fmtSizeMB(metric.mem_total_mb) }}</div>
          <div class="stat-label">内存 ({{ memPct }}%)</div>
          <div class="stat-sub">可用 {{ fmtSizeMB(metric.mem_available_mb) }} · 缓存 {{ fmtSizeMB(metric.mem_cached_mb) }} · Swap {{ fmtSizeMB(metric.swap_used_mb) }}/{{ fmtSizeMB(metric.swap_total_mb) }}</div>
        </el-card></el-col>
        <el-col :span="6"><el-card class="stat-card">
          <div class="stat-value">{{ metric.disk_used_gb.toFixed(0) }} / {{ metric.disk_total_gb.toFixed(0) }} GB</div>
          <div class="stat-label">磁盘 ({{ diskPct }}%)</div>
          <div class="stat-sub">{{ (metric.disks||[]).length }} 个挂载点</div>
        </el-card></el-col>
        <el-col :span="6"><el-card class="stat-card">
          <div class="stat-value">{{ fmtUptime(metric.uptime_seconds) }}</div>
          <div class="stat-label">运行时长</div>
          <div class="stat-sub">{{ metric.os }} · {{ metric.kernel }}</div>
        </el-card></el-col>
      </el-row>

      <!-- ===== per-core grid (btop style) ===== -->
      <el-card class="page-card" style="margin-top:14px">
        <template #header>
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span>CPU 核心 ({{ cores.length }})</span>
            <div style="display:flex;gap:16px;font-size:12px;color:#909399;align-items:center">
              <span>负载 {{ metric.load1.toFixed(2) }} / {{ metric.load5.toFixed(2) }} / {{ metric.load15.toFixed(2) }}</span>
              <span v-if="metric.cpu_temp_package">封装温度 {{ metric.cpu_temp_package }}°C</span>
              <span>采集耗时 {{ metric.duration }}s</span>
            </div>
          </div>
        </template>
        <div class="core-grid">
          <el-tooltip v-for="c in cores" :key="c.id" :placement="'top'">
            <template #content>
              核心 {{ c.id }}: {{ c.util }}% · {{ fmtFreq(c.freq_mhz) }}<span v-if="c.temp"> · {{ c.temp }}°C</span>
            </template>
            <div class="core-block" :class="coreClass(c.util)">
              <div class="core-fill" :style="{height: c.util + '%'}"></div>
              <span class="core-text">{{ c.util > 60 ? c.util : (c.util > 25 ? c.util : '') }}</span>
            </div>
          </el-tooltip>
        </div>
      </el-card>

      <!-- ===== GPU cards ===== -->
      <el-card class="page-card">
        <template #header>
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span>GPU ({{ gpus.length }})</span>
            <span style="color:#909399;font-size:13px">驱动 {{ metric.gpu_driver || '—' }}</span>
          </div>
        </template>
        <el-empty v-if="!gpus.length" description="未检测到 GPU（nvidia-smi 不可用）" :image-size="60" />
        <el-row :gutter="14" v-else>
          <el-col :span="12" v-for="g in gpus" :key="g.uuid + g.index">
            <el-card class="gpu-card" shadow="hover">
              <div style="display:flex;justify-content:space-between;margin-bottom:8px;align-items:center">
                <b>GPU {{ g.index }} · {{ g.name }}</b>
                <div style="display:flex;gap:6px;align-items:center">
                  <el-tag v-if="g.pstate" size="small" type="info">{{ g.pstate }}</el-tag>
                  <el-tag v-if="g.compute_mode && g.compute_mode !== 'Default'" size="small" type="warning">{{ g.compute_mode }}</el-tag>
                </div>
              </div>
              <el-descriptions :column="2" size="small" border>
                <el-descriptions-item label="利用率">
                  <el-progress :percentage="pct(g.utilization)" :color="utilColor(g.utilization)" :stroke-width="12" style="width:130px" />
                </el-descriptions-item>
                <el-descriptions-item label="显存">
                  <el-progress :percentage="gpuMemPct(g)" :color="utilColor(gpuMemPct(g))" :stroke-width="12" style="width:130px" />
                  <div class="mono" style="font-size:12px">{{ fmtSizeMB(g.mem_used_mb) }} / {{ fmtSizeMB(g.mem_total_mb) }}</div>
                </el-descriptions-item>
                <el-descriptions-item label="温度">
                  <span :style="{ color: tempColor(g.temperature) }">{{ g.temperature }}°C</span>
                </el-descriptions-item>
                <el-descriptions-item label="功耗">{{ g.power_draw }} / {{ g.power_limit }} W</el-descriptions-item>
                <el-descriptions-item label="核心频率">{{ g.clock_graphics ? (g.clock_graphics + ' MHz') : '—' }}<span v-if="g.clock_graphics_max" style="color:#c0c4cc"> / {{ g.clock_graphics_max }}</span></el-descriptions-item>
                <el-descriptions-item label="显存频率">{{ g.clock_memory ? (g.clock_memory + ' MHz') : '—' }}<span v-if="g.clock_memory_max" style="color:#c0c4cc"> / {{ g.clock_memory_max }}</span></el-descriptions-item>
                <el-descriptions-item label="风扇">{{ g.fan_speed }}%</el-descriptions-item>
                <el-descriptions-item label="编解码">编码 {{ g.encoder_sessions ?? 0 }} · 解码 {{ g.decoder_sessions ?? 0 }}</el-descriptions-item>
              </el-descriptions>
              <div v-if="g.processes?.length" style="margin-top:8px">
                <div style="font-size:12px;color:#909399;margin-bottom:4px">GPU 进程</div>
                <el-table :data="g.processes" size="small">
                  <el-table-column prop="pid" label="PID" width="80" />
                  <el-table-column prop="user" label="用户" width="100" show-overflow-tooltip />
                  <el-table-column label="显存" width="100">
                    <template #default="{ row }">{{ fmtSizeMB(row.mem_mb) }}</template>
                  </el-table-column>
                  <el-table-column prop="command" label="进程" min-width="140" show-overflow-tooltip />
                </el-table>
              </div>
            </el-card>
          </el-col>
        </el-row>
      </el-card>

      <!-- ===== network & disk IO rates ===== -->
      <el-row :gutter="14">
        <el-col :span="12">
          <el-card class="page-card">
            <template #header>网络速率 (实时)</template>
            <el-table :data="metric.net_ifaces || []" size="small">
              <el-table-column prop="iface" label="接口" min-width="110" />
              <el-table-column label="↓ 接收" width="120">
                <template #default="{ row }"><span class="mono">{{ fmtBps(row.rx_bps) }}</span></template>
              </el-table-column>
              <el-table-column label="↑ 发送" width="120">
                <template #default="{ row }"><span class="mono">{{ fmtBps(row.tx_bps) }}</span></template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!(metric.net_ifaces||[]).length" description="暂无活动接口" :image-size="40" />
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card class="page-card">
            <template #header>磁盘 IO (实时)</template>
            <el-table :data="metric.disk_io || []" size="small">
              <el-table-column prop="device" label="设备" min-width="90" />
              <el-table-column label="读" width="110">
                <template #default="{ row }"><span class="mono">{{ fmtBps(row.read_bps) }}</span></template>
              </el-table-column>
              <el-table-column label="写" width="110">
                <template #default="{ row }"><span class="mono">{{ fmtBps(row.write_bps) }}</span></template>
              </el-table-column>
              <el-table-column label="IOPS r/w" width="110">
                <template #default="{ row }"><span class="mono">{{ row.read_iops }}/{{ row.write_iops }}</span></template>
              </el-table-column>
              <el-table-column label="繁忙" width="90">
                <template #default="{ row }">{{ row.busy_percent }}%</template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!(metric.disk_io||[]).length" description="暂无活动 IO" :image-size="40" />
          </el-card>
        </el-col>
      </el-row>

      <!-- ===== disks + logged users ===== -->
      <el-row :gutter="14">
        <el-col :span="16">
          <el-card class="page-card">
            <template #header>磁盘分区</template>
            <el-table :data="metric.disks || []" size="small">
              <el-table-column prop="mount" label="挂载点" min-width="130" show-overflow-tooltip />
              <el-table-column prop="device" label="设备" min-width="110" show-overflow-tooltip class-name="mono" />
              <el-table-column label="用量" width="200">
                <template #default="{ row }">
                  <el-progress :percentage="pct(row.percent)" :color="utilColor(row.percent)" :stroke-width="10" />
                </template>
              </el-table-column>
              <el-table-column label="已用/总量" width="140">
                <template #default="{ row }"><span class="mono">{{ row.used_gb.toFixed(0) }}/{{ row.total_gb.toFixed(0) }} GB</span></template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card class="page-card">
            <template #header>登录用户</template>
            <el-table :data="metric.users || []" size="small">
              <el-table-column prop="user" label="用户" width="90" />
              <el-table-column prop="from" label="来源" min-width="110" show-overflow-tooltip />
              <el-table-column prop="login" label="登录时间" min-width="110" show-overflow-tooltip />
            </el-table>
            <el-empty v-if="!(metric.users||[]).length" description="无登录用户" :image-size="40" />
          </el-card>
        </el-col>
      </el-row>

      <!-- ===== live process table (btop parity: sort/kill/renice) ===== -->
      <el-card class="page-card">
        <template #header>
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span>进程 (实时 SSH · {{ procs.length }})</span>
            <div style="display:flex;gap:8px;align-items:center">
              <el-radio-group v-model="procSort" size="small" @change="loadProcs">
                <el-radio-button value="cpu">CPU</el-radio-button>
                <el-radio-button value="mem">内存</el-radio-button>
                <el-radio-button value="time">时长</el-radio-button>
              </el-radio-group>
              <el-input v-model="procFilter" placeholder="过滤..." size="small" style="width:150px" clearable />
              <el-button size="small" :icon="Refresh" @click="loadProcs">刷新</el-button>
            </div>
          </div>
        </template>
        <el-table :data="filteredProcs" size="small" height="420" v-loading="procsLoading"
                  :default-sort="{ prop: procSort === 'mem' ? 'rss_mb' : 'cpu', order: 'descending' }">
          <el-table-column prop="pid" label="PID" width="80" sortable />
          <el-table-column prop="user" label="用户" width="100" show-overflow-tooltip sortable />
          <el-table-column prop="cpu" label="CPU%" width="85" sortable>
            <template #default="{ row }">{{ row.cpu.toFixed(1) }}</template>
          </el-table-column>
          <el-table-column prop="rss_mb" label="内存 MB" width="95" sortable>
            <template #default="{ row }">{{ row.rss_mb.toFixed(0) }}</template>
          </el-table-column>
          <el-table-column prop="mem" label="mem%" width="80" sortable>
            <template #default="{ row }">{{ row.mem.toFixed(1) }}</template>
          </el-table-column>
          <el-table-column prop="stat" label="状态" width="70" />
          <el-table-column label="运行时长" width="95" sortable :sort-method="(a,b)=>a.etimes-b.etimes">
            <template #default="{ row }">{{ fmtDuration(row.etimes) }}</template>
          </el-table-column>
          <el-table-column prop="command" label="命令" min-width="240" show-overflow-tooltip class-name="mono" />
          <el-table-column v-if="isAdmin" label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="warning" @click="renice(row)">renice</el-button>
              <el-popconfirm :title="`确定 kill 进程 ${row.pid} (${row.command.slice(0,30)})？`" @confirm="kill(row, 'TERM')">
                <template #reference>
                  <el-button size="small" type="danger">kill</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- ===== history charts (cockpit style, multi-panel) ===== -->
      <el-card class="page-card">
        <template #header>
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span>资源消耗趋势</span>
            <el-radio-group v-model="hours" size="small" @change="loadHistory">
              <el-radio-button :value="1">1小时</el-radio-button>
              <el-radio-button :value="3">3小时</el-radio-button>
              <el-radio-button :value="6">6小时</el-radio-button>
              <el-radio-button :value="24">24小时</el-radio-button>
              <el-radio-button :value="168">7天</el-radio-button>
            </el-radio-group>
          </div>
        </template>
        <el-row :gutter="14">
          <el-col :span="12">
            <div class="chart-sub-title">GPU 利用率 / 显存 / 温度 / 功耗</div>
            <v-chart v-if="history.length" :option="gpuChartOption" class="chart-box" autoresize />
            <el-empty v-else description="暂无历史数据" :image-size="50" />
          </el-col>
          <el-col :span="12">
            <div class="chart-sub-title">CPU / 内存 / Swap / 每核负载</div>
            <v-chart v-if="history.length" :option="sysChartOption" class="chart-box" autoresize />
            <el-empty v-else description="暂无历史数据" :image-size="50" />
          </el-col>
        </el-row>
        <el-row :gutter="14" style="margin-top:8px">
          <el-col :span="12">
            <div class="chart-sub-title">网络吞吐 (接收 / 发送)</div>
            <v-chart v-if="history.length" :option="netChartOption" class="chart-box-sm" autoresize />
          </el-col>
          <el-col :span="12">
            <div class="chart-sub-title">磁盘 IO (读 / 写)</div>
            <v-chart v-if="history.length" :option="diskChartOption" class="chart-box-sm" autoresize />
          </el-col>
        </el-row>
      </el-card>
    </template>
    <el-empty v-else-if="!loading" description="暂无采集数据，请等待采集周期或点击「立即采集」" />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import api from '../api'
import { fmtBps, fmtDuration, fmtFreq, fmtSizeMB, fmtUptime, pct } from '../format'

use([CanvasRenderer, LineChart, GridComponent, LegendComponent, TooltipComponent])

const route = useRoute()
const serverId = Number(route.params.id)
const loading = ref(false)
const server = ref(null)
const metric = ref(null)
const history = ref([])
const hours = ref(3)

const procs = ref([])
const procsLoading = ref(false)
const procSort = ref('cpu')
const procFilter = ref('')
let liveTimer = null

const isAdmin = computed(() => localStorage.getItem('role') === 'admin')
const gpus = computed(() => metric.value?.gpus || [])
const cores = computed(() => metric.value?.cores || [])

const memPct = computed(() => pct(metric.value?.mem_total_mb ? metric.value.mem_used_mb / metric.value.mem_total_mb * 100 : 0))
const diskPct = computed(() => pct(metric.value?.disk_total_gb ? metric.value.disk_used_gb / metric.value.disk_total_gb * 100 : 0))

const filteredProcs = computed(() => {
  if (!procFilter.value) return procs.value
  const k = procFilter.value.toLowerCase()
  return procs.value.filter(p =>
    String(p.pid).includes(k) ||
    p.user.toLowerCase().includes(k) ||
    (p.command || '').toLowerCase().includes(k)
  )
})

function gpuMemPct(g) {
  return pct(g.mem_total_mb ? g.mem_used_mb / g.mem_total_mb * 100 : 0)
}

function utilColor(v) {
  if (v >= 90) return '#f56c6c'
  if (v >= 70) return '#e6a23c'
  return '#67c23a'
}

function tempColor(t) {
  if (t >= 80) return '#f56c6c'
  if (t >= 70) return '#e6a23c'
  return '#67c23a'
}

function coreClass(util) {
  if (util >= 90) return 'core-crit'
  if (util >= 70) return 'core-warn'
  if (util >= 25) return 'core-ok'
  return 'core-idle'
}

const _axisTime = computed(() => {
  const p = (n) => String(n).padStart(2, '0')
  return history.value.map((t) => {
    const d = new Date(t.time)
    return hours.value >= 24 ? `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}` : `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
  })
})

const _darkBase = {
  backgroundColor: 'transparent',
  tooltip: { trigger: 'axis', backgroundColor: '#101a2e', borderColor: '#1e2d47', textStyle: { color: '#dce7f5' } },
  legend: { textStyle: { color: '#7d90ad' }, top: 0, icon: 'roundRect', itemWidth: 14, itemHeight: 4 },
  grid: { left: 50, right: 54, top: 32, bottom: 28 },
  dataZoom: [{ type: 'inside' }],
}

const _mk = (name, data, color, extra = {}) => ({
  name, type: 'line', showSymbol: false, smooth: true, data,
  lineStyle: { width: 2, color }, itemStyle: { color },
  areaStyle: { opacity: 0.1, color }, ...extra,
})

const gpuChartOption = computed(() => ({
  ..._darkBase,
  xAxis: { type: 'category', data: _axisTime.value, axisLine: { lineStyle: { color: '#1e2d47' } }, axisLabel: { color: '#7d90ad' } },
  yAxis: [
    { type: 'value', max: 100, axisLabel: { color: '#7d90ad' }, splitLine: { lineStyle: { color: 'rgba(30,45,71,.5)' } } },
    { type: 'value', axisLabel: { color: '#7d90ad' }, splitLine: { show: false } },
  ],
  series: [
    _mk('利用率 %', history.value.map(h => h.gpu_util), '#22d3ee'),
    _mk('显存 %', history.value.map(h => h.gpu_mem_percent), '#a78bfa'),
    _mk('温度 °C', history.value.map(h => h.gpu_temp), '#fbbf24', { yAxisIndex: 1 }),
    _mk('功耗 W', history.value.map(h => h.gpu_power), '#f87171', { yAxisIndex: 1 }),
  ],
}))

const sysChartOption = computed(() => ({
  ..._darkBase,
  xAxis: { type: 'category', data: _axisTime.value, axisLine: { lineStyle: { color: '#1e2d47' } }, axisLabel: { color: '#7d90ad' } },
  yAxis: [
    { type: 'value', max: 100, axisLabel: { color: '#7d90ad' }, splitLine: { lineStyle: { color: 'rgba(30,45,71,.5)' } } },
    { type: 'value', axisLabel: { color: '#7d90ad' }, splitLine: { show: false } },
  ],
  series: [
    _mk('CPU %', history.value.map(h => h.cpu_percent), '#34d399'),
    _mk('内存 %', history.value.map(h => h.mem_percent), '#22d3ee'),
    _mk('Swap %', history.value.map(h => h.swap_percent ?? 0), '#fbbf24'),
    _mk('每核负载', history.value.map(h => h.load_per_core ?? 0), '#a78bfa', { yAxisIndex: 1 }),
  ],
}))

const netChartOption = computed(() => ({
  ..._darkBase,
  xAxis: { type: 'category', data: _axisTime.value, axisLine: { lineStyle: { color: '#1e2d47' } }, axisLabel: { color: '#7d90ad' } },
  yAxis: [{ type: 'value', axisLabel: { color: '#7d90ad', formatter: (v) => fmtBps(v) }, splitLine: { lineStyle: { color: 'rgba(30,45,71,.5)' } } }],
  series: [
    _mk('接收', history.value.map(h => h.net_rx_bps ?? 0), '#22d3ee'),
    _mk('发送', history.value.map(h => h.net_tx_bps ?? 0), '#a78bfa'),
  ],
}))

const diskChartOption = computed(() => ({
  ..._darkBase,
  xAxis: { type: 'category', data: _axisTime.value, axisLine: { lineStyle: { color: '#1e2d47' } }, axisLabel: { color: '#7d90ad' } },
  yAxis: [{ type: 'value', axisLabel: { color: '#7d90ad', formatter: (v) => fmtBps(v) }, splitLine: { lineStyle: { color: 'rgba(30,45,71,.5)' } } }],
  series: [
    _mk('读', history.value.map(h => h.disk_read_bps ?? 0), '#fbbf24'),
    _mk('写', history.value.map(h => h.disk_write_bps ?? 0), '#f87171'),
  ],
}))

async function load() {
  loading.value = true
  try {
    const [serverList, latest] = await Promise.all([
      api.get('/servers').then(r => r.data),
      api.get(`/metrics/server/${serverId}/latest`).then(r => r.data).catch(() => null),
      loadHistory()
    ])
    server.value = serverList.find(s => s.id === serverId) || null
    metric.value = latest
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '加载失败')
  } finally {
    loading.value = false
  }
}

async function loadHistory() {
  try {
    const { data } = await api.get(`/metrics/server/${serverId}/history?hours=${hours.value}`)
    history.value = data
  } catch {
    history.value = []
  }
}

async function loadProcs() {
  procsLoading.value = true
  try {
    const { data } = await api.get(`/metrics/server/${serverId}/processes?sort=${procSort.value}`)
    procs.value = data.processes
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '获取进程失败')
  } finally {
    procsLoading.value = false
  }
}

async function kill(row, signal) {
  try {
    const { data } = await api.post(`/metrics/server/${serverId}/processes/action`, { action: 'kill', pid: row.pid, signal })
    ElMessage.success(`已发送 ${signal} 到 ${row.pid}: ${data.message}`)
    setTimeout(loadProcs, 800)
  } catch (e) {
    ElMessage.error(e.friendlyMessage || 'kill 失败')
  }
}

async function renice(row) {
  try {
    const { value } = await ElMessageBox.prompt(`调整进程 ${row.pid} 的 nice 值 (-20 最高优先级 ~ 19 最低)`, 'Renice', {
      inputValue: '10', inputPattern: /^-?\d+$/, inputErrorMessage: '请输入 -20 到 19 之间的整数'
    })
    const nice = Math.max(-20, Math.min(19, parseInt(value)))
    await api.post(`/metrics/server/${serverId}/processes/action`, { action: 'renice', pid: row.pid, nice })
    ElMessage.success(`已 renice ${row.pid} -> ${nice}`)
  } catch (e) {
    if (e !== 'cancel' && e?.friendlyMessage) ElMessage.error(e.friendlyMessage)
  }
}

onMounted(() => {
  load()
  loadProcs()
  liveTimer = setInterval(loadProcs, 15000)
})
onUnmounted(() => clearInterval(liveTimer))
</script>

<style scoped>
.core-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(46px, 1fr));
  gap: 6px;
}
.core-block {
  position: relative;
  height: 60px;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  overflow: hidden;
  background: #f5f7fa;
  cursor: default;
}
.core-fill {
  position: absolute;
  bottom: 0; left: 0; right: 0;
  transition: height .4s;
}
.core-idle .core-fill { background: #c0c4cc66; }
.core-ok   .core-fill { background: #67c23a88; }
.core-warn .core-fill { background: #e6a23c99; }
.core-crit .core-fill { background: #f56c6caa; }
.core-text {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  color: #303133;
}
</style>
