<template>
  <div class="cockpit">
    <el-alert v-if="error" type="error" :closable="false" show-icon style="margin-bottom:14px"
              :title="`数据加载失败：${error}，正在重试`" />

    <!-- ===== header ===== -->
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <div style="display:flex;align-items:center;gap:12px">
        <span class="live-dot" :class="{ err: hasError }"></span>
        <span style="font-size:20px;font-weight:700;letter-spacing:0.04em">GPU 集群驾驶舱</span>
        <span style="font-size:12px;color:var(--csub)">CLUSTER COCKPIT</span>
      </div>
      <div style="display:flex;gap:14px;align-items:center;font-size:12px;color:var(--csub)">
        <span v-if="lastUpdated">更新于 {{ lastUpdated.toLocaleTimeString('zh-CN') }}</span>
        <el-radio-group v-model="rangeHours" size="small" @change="loadHistory">
          <el-radio-button :value="1">1H</el-radio-button>
          <el-radio-button :value="6">6H</el-radio-button>
          <el-radio-button :value="24">24H</el-radio-button>
        </el-radio-group>
        <RateUnitPicker v-show="trendMetric === 'net'" kind="net" @change="onUnitChange" />
        <RateUnitPicker v-show="trendMetric === 'disk'" kind="disk" @change="onUnitChange" />
        <el-button v-if="isAdminSession()" size="small" :icon="Refresh" :loading="refreshing" @click="refreshNow">立即采集</el-button>
      </div>
    </div>

    <!-- ===== KPI band ===== -->
    <div class="kpi-band">
      <div class="cockpit-panel kpi-accent-cyan">
        <div class="kpi-value">{{ nServers }}<span class="kpi-unit">/ {{ stats.servers_total }} 在线</span></div>
        <div class="kpi-label">服务器 ONLINE</div>
      </div>
      <div class="cockpit-panel kpi-accent-purple">
        <div class="kpi-value">{{ nGpus }}<span class="kpi-unit">卡</span></div>
        <div class="kpi-label">GPU 总数 · 空闲 {{ nIdle }} 卡</div>
      </div>
      <div class="cockpit-panel kpi-accent-cyan">
        <div class="kpi-value">{{ fmtPct(avgGpuUtil) }}<span class="kpi-unit">%</span></div>
        <div class="kpi-label">GPU 平均利用率</div>
      </div>
      <div class="cockpit-panel" :class="gpuMemClass">
        <div class="kpi-value">{{ fmtPct(gpuMemPct) }}<span class="kpi-unit">%</span></div>
        <div class="kpi-label">显存 {{ fmtSizeMB(gpuMemUsed) }} / {{ fmtSizeMB(gpuMemTotal) }}</div>
      </div>
      <div class="cockpit-panel kpi-accent-green">
        <div class="kpi-value">{{ fmtPct(avgCpu) }}<span class="kpi-unit">%</span></div>
        <div class="kpi-label">CPU 平均 · 内存 {{ fmtPct(memPct) }}%</div>
      </div>
      <div class="cockpit-panel" :class="alertClass">
        <div class="kpi-value">{{ openAlerts }}<span class="kpi-unit">告警</span></div>
        <div class="kpi-label">未恢复告警 EVENTS</div>
      </div>
      <div class="cockpit-panel kpi-accent-yellow">
        <div class="kpi-value">{{ fmtPower(clusterPowerW) }}<span class="kpi-unit">W</span></div>
        <div class="kpi-label" style="cursor:pointer" title="GPU 集群功率 · 点击查看每日电量统计" @click="showEnergy = true">
          今日电量 {{ energy?.days?.at(-1)?.kwh ?? '—' }} kWh
        </div>
      </div>
    </div>

    <!-- ===== daily energy panel ===== -->
    <div class="cockpit-panel energy-panel" v-if="showEnergy">
      <div class="cockpit-panel-title">
        <b>每日电量消耗（GPU）</b>
        <el-button size="small" text :icon="Close" @click="showEnergy = false">收起</el-button>
      </div>
      <div class="energy-summary">
        <span>近 7 天合计 <b class="mono">{{ energy?.total_kwh ?? '—' }}</b> kWh</span>
        <span>日均 <b class="mono">{{ energy?.avg_kwh_per_day ?? '—' }}</b> kWh</span>
        <span v-if="energy?.total_cost != null">电费 <b class="mono">¥{{ energy.total_cost }}</b></span>
        <span v-if="energy?.price">电价 ¥{{ energy.price }}/kWh</span>
      </div>
      <div class="energy-bars">
        <div v-for="d in energy?.days || []" :key="d.date" class="energy-col" :title="`${d.date}: ${d.kwh} kWh · 平均 ${d.avg_w}W · 峰值 ${d.peak_w}W · 采样覆盖 ${(d.coverage*100).toFixed(0)}%`">
          <div class="energy-col-bar" :style="{ height: barH(d.kwh) + '%', background: energyGrad(d.kwh) }"></div>
          <span class="energy-col-val">{{ d.kwh }}</span>
          <span class="energy-col-date">{{ d.date.slice(5) }}</span>
        </div>
      </div>
    </div>

    <!-- ===== cluster health strip ===== -->
    <div class="health-strip" v-if="healthSummary.length">
      <div v-for="h in healthSummary" :key="h.server_id" class="health-chip" :class="`hs-${h.overall}`" @click="$router.push(`/servers/${h.server_id}`)">
        <span class="live-dot" v-if="h.overall === 'ok'"></span>
        <el-icon v-else-if="h.overall === 'critical'" color="var(--cred)"><CircleCloseFilled /></el-icon>
        <el-icon v-else color="var(--cyellow)"><WarningFilled /></el-icon>
        <b>{{ h.name }}</b>
        <span class="health-chip-detail">
          {{ h.overall === 'ok' ? '健康' : (h.error_code && h.error_code !== 'OK') ? faultLabel(h.error_code) : (h.critical ? `${h.critical} 严重` : `${h.warning} 警告`) }}
        </span>
      </div>
    </div>

    <!-- ===== main grid: GPU matrix + cluster trend ===== -->
    <div class="main-grid">
      <div class="cockpit-panel">
        <div class="cockpit-panel-title">
          <b>GPU 资源矩阵</b>
          <span style="display:flex;gap:10px;align-items:center">
            <el-select :value="matrixSort" size="small" style="width:128px" @change="matrixSort = $event">
              <el-option value="server" label="按服务器" />
              <el-option value="util-desc" label="利用率 ↓" />
              <el-option value="util-asc" label="利用率 ↑" />
              <el-option value="mem-desc" label="显存占用 ↓" />
              <el-option value="temp-desc" label="温度 ↓" />
            </el-select>
            <span>
              <el-tag size="small" type="success" effect="dark" class="tag-idle">空闲</el-tag>
              <el-tag size="small" effect="dark" class="tag-busy">繁忙</el-tag>
              <el-tag size="small" effect="dark" class="tag-full">满载</el-tag>
            </span>
          </span>
        </div>

        <!-- sorted flat view -->
        <div v-if="matrixSort !== 'server'" class="gpu-matrix" style="margin-top:8px">
          <div v-for="g in sortedFlatGpus" :key="g.key"
               class="gpu-cell" :class="gpuCellClass(g)" @click="$router.push(`/servers/${g.server_id}`)">
            <div class="gpu-cell-head">
              <span class="gpu-cell-name">{{ g.server_short }}·{{ g.index }}</span>
              <span class="gpu-cell-badge">{{ g.pstate || shortName(g.name) }}</span>
            </div>
            <div class="gpu-util-bar">
              <div class="gpu-util-fill" :style="{ width: g.utilization + '%', background: utilGradient(g.utilization) }"></div>
            </div>
            <div class="gpu-cell-rows">
              <span>利用 <span class="mono">{{ g.utilization }}%</span> · {{ g.temperature }}°C</span>
              <span class="mono">{{ fmtSizeMB(g.mem_used_mb) }} / {{ fmtSizeMB(g.mem_total_mb) }}</span>
            </div>
          </div>
        </div>

        <!-- grouped-by-server view (default) -->
        <div v-for="srv in gpuMatrix" v-show="matrixSort === 'server'" :key="srv.server_id" style="margin-bottom:12px">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:13px">
            <span class="live-dot" :class="{ err: !srv.online }" style="width:6px;height:6px"></span>
            <b style="cursor:pointer" @click="$router.push(`/servers/${srv.server_id}`)">{{ srv.server_name }}</b>
            <span style="color:var(--csub);font-size:11px">{{ srv.hostname }}</span>
            <span v-if="!srv.enabled" style="color:var(--csub);font-size:11px">(已禁用)</span>
            <span v-if="!srv.online && srv.error" style="color:var(--cred);font-size:11px">{{ srv.error.slice(0, 60) }}</span>
          </div>
          <div class="gpu-matrix" v-if="srv.gpus.length">
            <div v-for="g in srv.gpus" :key="srv.server_id + '-' + g.index"
                 class="gpu-cell" :class="gpuCellClass(g)" @click="$router.push(`/servers/${srv.server_id}`)">
              <div class="gpu-cell-head">
                <span class="gpu-cell-name">GPU {{ g.index }}</span>
                <span class="gpu-cell-badge">{{ g.pstate || shortName(g.name) }}</span>
              </div>
              <div class="gpu-util-bar">
                <div class="gpu-util-fill" :style="{ width: g.utilization + '%', background: utilGradient(g.utilization) }"></div>
              </div>
              <div class="gpu-cell-rows">
                <span>利用 <span class="mono">{{ g.utilization }}%</span> · {{ g.temperature }}°C</span>
                <span class="mono">{{ fmtSizeMB(g.mem_used_mb) }} / {{ fmtSizeMB(g.mem_total_mb) }}</span>
              </div>
            </div>
          </div>
          <div v-else style="color:var(--csub);font-size:12px;padding:6px 0">
            {{ srv.online ? '无 GPU' : '离线' }}
          </div>
        </div>
        <el-empty v-if="!gpuMatrix.length" description="暂无服务器" :image-size="60" />
      </div>

      <div style="display:flex;flex-direction:column;gap:14px;min-width:0">
        <div class="cockpit-panel">
          <div class="cockpit-panel-title">
            <b>集群资源趋势</b>
            <el-radio-group v-model="trendMetric" size="small">
              <el-radio-button value="gpu">GPU</el-radio-button>
              <el-radio-button value="cpu">CPU/内存</el-radio-button>
              <el-radio-button value="net">网络</el-radio-button>
              <el-radio-button value="disk">磁盘</el-radio-button>
              <el-radio-button value="power">功率</el-radio-button>
            </el-radio-group>
          </div>
          <v-chart :option="trendOption" class="cockpit-chart-lg" autoresize />
        </div>

        <div class="cockpit-panel">
          <div class="cockpit-panel-title"><b>GPU 显存占用 TOP</b></div>
          <div class="rank-scroll">
          <div v-for="(r, i) in gpuMemRank" :key="r.key" class="rank-row">
            <span class="rank-no" :class="i === 0 ? 'top1' : i === 1 ? 'top2' : i === 2 ? 'top3' : ''">{{ i + 1 }}</span>
            <div class="rank-main">
              <div>{{ r.label }}</div>
              <div class="rank-sub">{{ r.server }} · {{ r.name }}</div>
            </div>
            <span class="rank-val mono">{{ fmtSizeMB(r.used) }}</span>
            <el-progress :percentage="r.pct" :stroke-width="6" :color="utilColor(r.pct)" style="width:90px" :show-text="false" />
          </div>
          <el-empty v-if="!gpuMemRank.length" description="—" :image-size="40" />
          </div>
        </div>
      </div>
    </div>

    <!-- ===== bottom: alerts ticker + process rank + net rank ===== -->
    <div class="bottom-grid">
      <div class="cockpit-panel stack">
        <div class="cockpit-panel-title"><b>实时告警</b><span class="io-label">{{ openAlerts }} 条未恢复</span></div>
        <div class="ticker" v-if="alertTickerRows.length">
          <div class="ticker-inner">
            <div v-for="(a, i) in alertTickerRows" :key="i" class="ticker-row">
              <el-tag size="small" type="danger" effect="dark">告警</el-tag>
              <span class="mono">{{ fmtTime(a.triggered_at) }}</span>
              <b>{{ a.server_name }}</b>
              <span>{{ a.message }}</span>
            </div>
          </div>
        </div>
        <div v-else class="ticker-empty">
          <el-icon><CircleCheckFilled /></el-icon> 全部指标正常，无未恢复告警
        </div>
      </div>

      <div class="cockpit-panel stack">
        <div class="cockpit-panel-title"><b>GPU 进程 TOP</b></div>
        <div class="fill-list">
          <div v-for="(p, i) in gpuProcRank" :key="p.pid" class="rank-row">
            <span class="rank-no" :class="i === 0 ? 'top1' : i === 1 ? 'top2' : i === 2 ? 'top3' : ''">{{ i + 1 }}</span>
            <div class="rank-main">
              <div class="mono" style="font-size:12px">{{ p.command || p.pid }}</div>
              <div class="rank-sub">{{ p.server }} · GPU{{ p.gpu }} · {{ p.user }}</div>
            </div>
            <span class="rank-val mono">{{ fmtSizeMB(p.mem_mb) }}</span>
          </div>
          <el-empty v-if="!gpuProcRank.length" description="无 GPU 进程" :image-size="40" />
        </div>
      </div>

      <div class="cockpit-panel stack">
        <div class="cockpit-panel-title"><b>网络 / 磁盘吞吐</b></div>
        <div class="io-rows fill-list">
          <div class="io-row">
            <span class="io-label">↓ 集群接收</span>
            <b class="mono">{{ fmtNetRate(totalNetRx) }}</b>
          </div>
          <div class="io-row">
            <span class="io-label">↑ 集群发送</span>
            <b class="mono">{{ fmtNetRate(totalNetTx) }}</b>
          </div>
          <div class="io-row">
            <span class="io-label">▩ 磁盘读</span>
            <b class="mono">{{ fmtDiskRate(totalDiskRead) }}</b>
          </div>
          <div class="io-row">
            <span class="io-label">▩ 磁盘写</span>
            <b class="mono">{{ fmtDiskRate(totalDiskWrite) }}</b>
          </div>
          <div class="io-row" v-if="latestMetric">
            <span class="io-label">温度峰值</span>
            <b class="mono" :style="{ color: tempColor(maxGpuTemp) }">{{ maxGpuTemp }}°C</b>
          </div>
          <div class="io-row" v-if="latestMetric">
            <span class="io-label">总功耗</span>
            <b class="mono">{{ totalGpuPower }} W</b>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Close, Refresh, CircleCheckFilled } from '@element-plus/icons-vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent, DataZoomComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import api from '../api'
import RateUnitPicker from '../components/RateUnitPicker.vue'
import { diskAxisFormatter, fmtDiskRate, fmtNetRate, fmtSizeMB, fmtTime, netAxisFormatter } from '../format'
import '../cockpit.css'
import { isAdminSession, useLatestOnly, usePoll } from '../composables'
import { chartTheme } from '../theme'

use([CanvasRenderer, LineChart, GridComponent, LegendComponent, TooltipComponent, DataZoomComponent])

const rangeHours = ref(6)
const trendMetric = ref('gpu')
const unitEpoch = ref(0)
function onUnitChange() { unitEpoch.value++ }
const refreshing = ref(false)
const history = ref([])

const stats = ref({})
const healthSummary = ref([])
const gpuMatrix = ref([])
const clusterPowerW = ref(0)
const energy = ref(null)
const showEnergy = ref(false)

function barH(kwh) {
  const max = Math.max(...(energy.value?.days || []).map(d => d.kwh), 1)
  return Math.max(6, (kwh / max) * 100)
}
function energyGrad(kwh) {
  const max = Math.max(...(energy.value?.days || []).map(d => d.kwh), 1)
  const r = kwh / max
  if (r > 0.75) return 'linear-gradient(180deg, #f59e0b, #ef4444)'
  if (r > 0.45) return 'linear-gradient(180deg, #22d3ee, #0891b2)'
  return 'linear-gradient(180deg, #34d399, #10b981)'
}
function fmtPower(w) {
  return w >= 1000 ? (w / 1000).toFixed(2) + 'k' : Math.round(w)
}
const matrixSort = ref('server')

const sortedFlatGpus = computed(() => {
  const flat = gpuMatrix.value.flatMap(s =>
    s.gpus.map(g => ({
      ...g,
      key: `${s.server_id}-${g.index}`,
      server_id: s.server_id,
      server_short: s.server_name.replace(/^gpu-/, '').replace(/-\d+$/, ''),
    }))
  )
  const memPct = g => (g.mem_total_mb ? g.mem_used_mb / g.mem_total_mb : 0)
  switch (matrixSort.value) {
    case 'util-desc': return [...flat].sort((a, b) => b.utilization - a.utilization)
    case 'util-asc': return [...flat].sort((a, b) => a.utilization - b.utilization)
    case 'mem-desc': return [...flat].sort((a, b) => memPct(b) - memPct(a))
    case 'temp-desc': return [...flat].sort((a, b) => (b.temperature || 0) - (a.temperature || 0))
    default: return flat
  }
})
const alerts = ref([])
const latest = ref([])

const { lastUpdated, reload, error } = usePoll(loadAll, 30000)

const nServers = computed(() => stats.value.servers_online ?? 0)
const hasError = computed(() => (stats.value.servers_error ?? 0) > 0 || openAlerts.value > 0)
const allGpus = computed(() => gpuMatrix.value.flatMap(s => s.gpus.map(g => ({ ...g, server: s.server_name }))))
const nGpus = computed(() => allGpus.value.length)
const nIdle = computed(() => allGpus.value.filter(g => g.utilization < 10 && (g.mem_used_mb / (g.mem_total_mb || 1)) < 0.15).length)
const avgGpuUtil = computed(() => stats.value.avg_gpu_util ?? 0)
const gpuMemTotal = computed(() => stats.value.gpu_mem_total_mb ?? 0)
const gpuMemUsed = computed(() => stats.value.gpu_mem_used_mb ?? 0)
const gpuMemPct = computed(() => (gpuMemTotal.value ? (gpuMemUsed.value / gpuMemTotal.value) * 100 : 0))
const avgCpu = computed(() => stats.value.avg_cpu_percent ?? 0)
const memPct = computed(() => (stats.value.mem_total_mb ? (stats.value.mem_used_mb / stats.value.mem_total_mb) * 100 : 0))
const openAlerts = computed(() => alerts.value.filter(a => !a.recovered_at).length)
const alertClass = computed(() => (openAlerts.value > 0 ? 'kpi-accent-yellow' : 'kpi-accent-green'))
const gpuMemClass = computed(() => (gpuMemPct.value >= 90 ? 'kpi-accent-yellow' : 'kpi-accent-cyan'))

const gpuMemRank = computed(() =>
  allGpus.value
    .map(g => ({
      key: `${g.server}-${g.index}`, label: `GPU ${g.index}`,
      server: g.server, name: shortName(g.name), used: g.mem_used_mb,
      pct: g.mem_total_mb ? (g.mem_used_mb / g.mem_total_mb) * 100 : 0,
    }))
    .sort((a, b) => b.used - a.used).slice(0, 6)
)

const gpuProcRank = computed(() =>
  allGpus.value
    .flatMap(g => (g.processes || []).map(p => ({ ...p, server: g.server, gpu: g.index })))
    .sort((a, b) => b.mem_mb - a.mem_mb).slice(0, 6)
)

const alertTickerRows = computed(() => {
  // enough rows to both fill the panel (~8+ rows) and keep the -50% scroll seamless
  const rows = alerts.value.slice(0, 12)
  if (!rows.length) return []
  const repeats = Math.max(2, Math.ceil(12 / rows.length))
  return Array.from({ length: repeats }).flatMap(() => rows)
})

const latestMetric = computed(() => latest.value[0] || null)
const totalNetRx = computed(() => latest.value.reduce((s, m) => s + (m.net_ifaces || []).reduce((a, i) => a + (i.rx_bps || 0), 0), 0))
const totalNetTx = computed(() => latest.value.reduce((s, m) => s + (m.net_ifaces || []).reduce((a, i) => a + (i.tx_bps || 0), 0), 0))
const totalDiskRead = computed(() => latest.value.reduce((s, m) => s + (m.disk_io || []).reduce((a, d) => a + (d.read_bps || 0), 0), 0))
const totalDiskWrite = computed(() => latest.value.reduce((s, m) => s + (m.disk_io || []).reduce((a, d) => a + (d.write_bps || 0), 0), 0))
const maxGpuTemp = computed(() => Math.max(0, ...allGpus.value.map(g => g.temperature || 0)))
const totalGpuPower = computed(() => Math.round(allGpus.value.reduce((s, g) => s + (g.power_draw || 0), 0)))

const trendOption = computed(() => {
  unitEpoch.value  // recompute when rate unit preference changes
  const T = chartTheme.value
  const mk = (name, data, color, extra = {}) => ({
    name, type: 'line', showSymbol: false, smooth: true, data,
    lineStyle: { width: 2, color }, itemStyle: { color }, areaStyle: { opacity: 0.12, color }, ...extra,
  })
  const t = history.value.map(h => fmtAxisTime(h.time))
  let series = []
  let percentMode = true
  let axisFmt = null
  if (trendMetric.value === 'gpu') {
    series = [
      mk('GPU 利用率 %', history.value.map(h => h.gpu_util), T.cyan),
      mk('GPU 显存 %', history.value.map(h => h.gpu_mem_percent), T.purple),
      mk('GPU 温度 °C', history.value.map(h => h.gpu_temp), T.yellow, { yAxisIndex: 1 }),
    ]
  } else if (trendMetric.value === 'cpu') {
    series = [
      mk('CPU %', history.value.map(h => h.cpu_percent), T.green),
      mk('内存 %', history.value.map(h => h.mem_percent), T.cyan),
    ]
  } else if (trendMetric.value === 'net') {
    percentMode = false
    axisFmt = netAxisFormatter()
    series = [
      mk('集群接收', history.value.map(h => h.net_bps), T.cyan),
      mk('集群发送', history.value.map(h => h.net_bps_tx || h.net_tx_bps), T.purple),
    ]
  } else if (trendMetric.value === 'disk') {
    percentMode = false
    axisFmt = diskAxisFormatter()
    series = [
      mk('磁盘读', history.value.map(h => h.disk_bps), T.yellow),
      mk('磁盘写', history.value.map(h => h.disk_bps_write || h.disk_write_bps), T.red),
    ]
  } else { // power
    percentMode = false
    axisFmt = (v) => v + ' W'
    series = [
      mk('GPU 集群功率', history.value.map(h => h.gpu_power || 0), T.red,
        { areaStyle: { opacity: 0.18, color: T.red } }),
    ]
  }
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', backgroundColor: T.tooltipBg, borderColor: T.tooltipBorder, textStyle: { color: T.tooltipText } },
    legend: { textStyle: { color: T.label }, top: 0, right: 0, icon: 'roundRect', itemWidth: 14, itemHeight: 4 },
    grid: { left: 12, right: 20, top: 30, bottom: 42, containLabel: true },
    xAxis: { type: 'category', data: t, boundaryGap: false, axisLine: { lineStyle: { color: T.axisLine } }, axisLabel: { color: T.label } },
    yAxis: [
      { type: 'value', max: percentMode ? 100 : undefined, axisLabel: { color: T.label, formatter: percentMode ? '{value}' : axisFmt }, splitLine: { lineStyle: { color: T.splitLine } } },
      { type: 'value', show: !percentMode ? false : true, axisLabel: { color: T.label }, splitLine: { show: false } },
    ],
    dataZoom: [{ type: 'inside' }],
    series,
  }
})

function shortName(n) {
  if (!n) return ''
  return n.replace('NVIDIA ', '').replace('GeForce ', '')
}

function fmtPct(v) { return (Math.round((Number(v) || 0) * 10) / 10).toFixed(1) }

// cluster-history now returns ISO UTC strings; show local time on the X axis
function fmtAxisTime(iso) {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const p = n => String(n).padStart(2, '0')
  const hm = `${p(d.getHours())}:${p(d.getMinutes())}`
  return rangeHours.value >= 24 ? `${p(d.getMonth() + 1)}-${p(d.getDate())} ${hm}` : hm
}

function utilColor(v) {
  const T = chartTheme.value
  if (v >= 90) return T.red
  if (v >= 70) return T.yellow
  return T.green
}

function tempColor(t) {
  const T = chartTheme.value
  if (t >= 80) return T.red
  if (t >= 70) return T.yellow
  return T.green
}

function utilGradient(u) {
  if (u >= 90) return 'linear-gradient(90deg,#fb7185,#f87171)'
  if (u >= 70) return 'linear-gradient(90deg,#fbbf24,#f59e0b)'
  if (u >= 30) return 'linear-gradient(90deg,#22d3ee,#0ea5e9)'
  return 'linear-gradient(90deg,#34d399,#10b981)'
}

function gpuCellClass(g) {
  const memPct = g.mem_total_mb ? (g.mem_used_mb / g.mem_total_mb) * 100 : 0
  if (g.utilization >= 90 || memPct >= 95) return 'gpu-cell-full'
  if (g.utilization >= 70 || memPct >= 85) return 'gpu-cell-busy'
  return 'gpu-cell-idle'
}

async function loadAll() {
  const [dash, gpus, energyData, powerNow, evts, latestAll, health] = await Promise.all([
    api.get('/metrics/dashboard').then(r => r.data),
    api.get('/metrics/cluster-gpus').then(r => r.data),
    api.get('/metrics/cluster-energy?days=7').then(r => r.data).catch(() => null),
    api.get('/metrics/cluster-power-now').then(r => r.data).catch(() => null),
    api.get('/alerts/events?limit=20').then(r => r.data),
    api.get('/metrics/latest').then(r => r.data),
    api.get('/cluster/health-summary').then(r => r.data).catch(() => []),
  ])
  stats.value = dash
  gpuMatrix.value = gpus
  alerts.value = evts
  latest.value = latestAll
  healthSummary.value = health
  energy.value = energyData
  clusterPowerW.value = powerNow?.total_w ?? 0
}

const FAULT_LABELS = {
  SSH_AUTH_FAILED: '认证失败', SSH_HOSTKEY_CHANGED: '主机密钥变更', SSH_DNS_FAILED: 'DNS 失败',
  SSH_REFUSED: '连接拒绝', SSH_DOWN: 'SSH 不可达', COLLECT_TIMEOUT: '采集超时', COLLECT_FAILED: '采集失败',
  CRED_DECRYPT_FAILED: '凭据需重新录入',
}
function faultLabel(code) { return FAULT_LABELS[code] || code }

const applyHistory = useLatestOnly()

async function loadHistory() {
  // only the newest request may write (fast 1H/6H/24H switching race guard)
  await applyHistory(
    api.get(`/metrics/cluster-history?hours=${rangeHours.value}`).catch(() => ({ data: [] })),
    ({ data }) => { history.value = data }
  )
}

let reloadTimer = null

async function refreshNow() {
  refreshing.value = true
  try {
    await api.post('/metrics/refresh')
    ElMessage.success('已触发采集')
    reloadTimer = setTimeout(() => { reload(); loadHistory() }, 5000)
  } catch (e) {
    if (e.response?.status === 409) ElMessage.info('采集进行中')
    else ElMessage.error(e.friendlyMessage || '触发失败')
  } finally {
    refreshing.value = false
  }
}

onMounted(loadHistory)
onUnmounted(() => { if (reloadTimer) clearTimeout(reloadTimer) })
</script>

<style scoped>
.kpi-band {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}
.main-grid {
  display: grid;
  grid-template-columns: 1.25fr 1fr;
  gap: 14px;
  margin-bottom: 14px;
  align-items: stretch;
}
.bottom-grid {
  display: grid;
  grid-template-columns: 1.4fr 1fr 0.8fr;
  gap: 14px;
}
.cockpit-chart-lg { height: 320px; width: 100%; }
.io-rows { display: flex; flex-direction: column; gap: 10px; justify-content: space-evenly; }
.io-row { display: flex; justify-content: space-between; align-items: baseline; font-size: 13px; }
.rank-no-fix { min-width: 22px; }
@media (max-width: 1400px) {
  .main-grid { grid-template-columns: 1fr; }
  .bottom-grid { grid-template-columns: 1fr; }
}
</style>
