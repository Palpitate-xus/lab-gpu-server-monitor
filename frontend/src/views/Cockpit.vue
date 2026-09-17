<template>
  <div class="cockpit-page">
    <a-alert v-if="error" type="error" show-icon class="load-alert"
              :message="`数据加载失败：${error}，正在重试`" />

    <!-- ===== header ===== -->
    <div class="cockpit-page-head">
      <div class="cockpit-page-identity">
        <a-badge :status="hasError ? 'error' : 'success'" />
        <span class="cockpit-page-title">GPU 集群驾驶舱</span>
      </div>
      <div class="cockpit-page-actions">
        <span v-if="lastUpdated">更新于 {{ lastUpdated.toLocaleTimeString('zh-CN') }}</span>
        <a-radio-group v-model:value="rangeHours" size="small" @change="loadHistory">
          <a-radio-button :value="1">1H</a-radio-button>
          <a-radio-button :value="6">6H</a-radio-button>
          <a-radio-button :value="24">24H</a-radio-button>
        </a-radio-group>
        <RateUnitPicker v-show="trendMetric === 'net'" kind="net" @change="onUnitChange" />
        <RateUnitPicker v-show="trendMetric === 'disk'" kind="disk" @change="onUnitChange" />
        <a-button v-if="isAdminSession()" size="small" :loading="refreshing" @click="refreshNow"><template #icon><ThunderboltOutlined /></template>立即采集</a-button>
      </div>
    </div>

    <!-- ===== KPI band ===== -->
    <div class="kpi-band">
      <a-card><a-statistic title="在线服务器" :value="nServers" :suffix="`/${stats.servers_total || 0}`" /></a-card>
      <a-card><a-statistic title="GPU 总数" :value="nGpus" suffix="卡" /><div class="kpi-note">空闲 {{ nIdle }} 卡</div></a-card>
      <a-card>
        <a-statistic title="GPU 平均利用率" :value="avgGpuUtil" :precision="1" suffix="%" />
        <a-progress :percent="gpuUtilDisplay" :show-info="false" size="small" :stroke-color="utilColor(gpuUtilDisplay)" />
      </a-card>
      <a-card>
        <a-statistic title="GPU 显存占用" :value="gpuMemPct" :precision="1" suffix="%" />
        <a-progress :percent="gpuMemoryDisplay" :show-info="false" size="small" :stroke-color="utilColor(gpuMemoryDisplay)" />
        <div class="kpi-note">{{ fmtSizeMB(gpuMemUsed) }} / {{ fmtSizeMB(gpuMemTotal) }}</div>
      </a-card>
      <a-card>
        <a-statistic title="CPU 平均利用率" :value="avgCpu" :precision="1" suffix="%" />
        <a-progress :percent="cpuDisplay" :show-info="false" size="small" :stroke-color="utilColor(cpuDisplay)" />
        <div class="kpi-note">内存 {{ fmtPct(memPct) }}%</div>
      </a-card>
      <a-card><a-statistic title="未恢复告警" :value="openAlerts" suffix="起" /></a-card>
      <a-card class="energy-kpi">
        <a-statistic title="GPU 集群功率" :value="fmtPower(clusterPowerW)" suffix="W" />
        <a-button type="link" size="small" class="energy-link" @click="showEnergy = true">
          今日电量 {{ energy?.days?.at(-1)?.kwh ?? '—' }} kWh
        </a-button>
      </a-card>
    </div>

    <!-- ===== daily energy panel ===== -->
    <a-card v-if="showEnergy" class="energy-panel" title="每日电量消耗（GPU）">
      <template #extra><a-button size="small" type="text" @click="showEnergy = false"><template #icon><CloseOutlined /></template>收起</a-button></template>
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
    </a-card>

    <!-- ===== cluster health strip ===== -->
    <div class="health-strip" v-if="healthSummary.length">
      <a-card v-for="h in healthSummary" :key="h.server_id" size="small" hoverable class="health-chip" :class="`hs-${h.overall}`"
        role="link" tabindex="0" :aria-label="`查看 ${h.name} 服务器详情`"
        @click="$router.push(`/servers/${h.server_id}`)"
        @keydown.enter.prevent="$router.push(`/servers/${h.server_id}`)"
        @keydown.space.prevent="$router.push(`/servers/${h.server_id}`)">
        <CheckCircleFilled v-if="h.overall === 'ok'" class="health-ok" />
        <CloseCircleFilled v-else-if="h.overall === 'critical'" class="health-error" />
        <WarningFilled v-else class="health-warning" />
        <b>{{ h.name }}</b>
        <span class="health-chip-detail">
          {{ h.overall === 'ok' ? '健康' : (h.error_code && h.error_code !== 'OK') ? faultLabel(h.error_code) : (h.critical ? `${h.critical} 严重` : `${h.warning} 警告`) }}
        </span>
      </a-card>
    </div>

    <!-- ===== main grid: GPU matrix + cluster trend ===== -->
    <div class="main-grid">
      <a-card class="matrix-panel">
        <template #title><div class="panel-heading matrix-panel-title">
          <b>GPU 资源矩阵</b>
          <span class="matrix-panel-actions">
            <a-select v-model:value="matrixSort" size="small" style="width:128px">
              <a-select-option value="server">按服务器</a-select-option>
              <a-select-option value="util-desc">利用率 ↓</a-select-option>
              <a-select-option value="util-asc">利用率 ↑</a-select-option>
              <a-select-option value="mem-desc">显存占用 ↓</a-select-option>
              <a-select-option value="temp-desc">温度 ↓</a-select-option>
            </a-select>
            <a-button size="small" type="primary" @click="$router.push('/gpu-matrix')">排序页 ↗</a-button>
            <span>
              <a-tag color="green">空闲</a-tag>
              <a-tag color="blue">繁忙</a-tag>
              <a-tag color="red">满载</a-tag>
            </span>
          </span>
        </div></template>

        <!-- sorted flat view -->
        <div v-if="matrixSort !== 'server'" class="gpu-matrix" style="margin-top:8px">
          <a-card v-for="g in sortedFlatGpus" :key="g.key" size="small" hoverable
               class="gpu-cell" :class="gpuCellClass(g)" @click="$router.push(`/servers/${g.server_id}`)">
            <div class="gpu-cell-head">
              <span class="gpu-cell-name">{{ g.server_short }}·{{ g.index }}</span>
              <span class="gpu-cell-badge">{{ g.pstate || shortName(g.name) }}</span>
            </div>
            <div class="gpu-meters">
              <div class="gpu-meter">
                <div class="gpu-meter-label"><span>负载</span><span class="mono">{{ gpuUtilPercent(g) }}%</span></div>
                <a-progress :percent="gpuUtilPercent(g)" :show-info="false" size="small" :stroke-color="utilColor(gpuUtilPercent(g))" aria-label="GPU 负载" />
              </div>
              <div class="gpu-meter">
                <div class="gpu-meter-label"><span>显存</span><span class="mono">{{ gpuMemoryPercent(g) }}%</span></div>
                <a-progress :percent="gpuMemoryPercent(g)" :show-info="false" size="small" :stroke-color="utilColor(gpuMemoryPercent(g))" aria-label="GPU 显存占用" />
              </div>
            </div>
            <div class="gpu-cell-meta">
              <span>温度 <span class="mono">{{ g.temperature }}°C</span></span>
              <span class="mono gpu-cell-memory" title="显存已用 / 总量">{{ fmtSizeMB(g.mem_used_mb) }} / {{ fmtSizeMB(g.mem_total_mb) }}</span>
            </div>
          </a-card>
        </div>

        <!-- grouped-by-server view (default) -->
        <div v-for="srv in gpuMatrix" v-show="matrixSort === 'server'" :key="srv.server_id" style="margin-bottom:12px">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:13px">
            <a-badge :status="srv.online ? 'success' : 'error'" />
            <b style="cursor:pointer" @click="$router.push(`/servers/${srv.server_id}`)">{{ srv.server_name }}</b>
            <span style="color:var(--csub);font-size:11px">{{ srv.hostname }}</span>
            <span v-if="!srv.enabled" style="color:var(--csub);font-size:11px">(已禁用)</span>
            <span v-if="!srv.online && srv.error" style="color:var(--cred);font-size:11px">{{ faultLabel(srv.error_code || srv.error).slice(0, 60) }}</span>
          </div>
          <div class="gpu-matrix" v-if="srv.gpus.length">
            <a-card v-for="g in srv.gpus" :key="srv.server_id + '-' + g.index" size="small" hoverable
                 class="gpu-cell" :class="gpuCellClass(g)" @click="$router.push(`/servers/${srv.server_id}`)">
              <div class="gpu-cell-head">
                <span class="gpu-cell-name">GPU {{ g.index }}</span>
                <span class="gpu-cell-badge">{{ g.pstate || shortName(g.name) }}</span>
              </div>
              <div class="gpu-meters">
                <div class="gpu-meter">
                  <div class="gpu-meter-label"><span>负载</span><span class="mono">{{ gpuUtilPercent(g) }}%</span></div>
                  <a-progress :percent="gpuUtilPercent(g)" :show-info="false" size="small" :stroke-color="utilColor(gpuUtilPercent(g))" aria-label="GPU 负载" />
                </div>
                <div class="gpu-meter">
                  <div class="gpu-meter-label"><span>显存</span><span class="mono">{{ gpuMemoryPercent(g) }}%</span></div>
                  <a-progress :percent="gpuMemoryPercent(g)" :show-info="false" size="small" :stroke-color="utilColor(gpuMemoryPercent(g))" aria-label="GPU 显存占用" />
                </div>
              </div>
              <div class="gpu-cell-meta">
                <span>温度 <span class="mono">{{ g.temperature }}°C</span></span>
                <span class="mono gpu-cell-memory" title="显存已用 / 总量">{{ fmtSizeMB(g.mem_used_mb) }} / {{ fmtSizeMB(g.mem_total_mb) }}</span>
              </div>
            </a-card>
          </div>
          <div v-else style="color:var(--csub);font-size:12px;padding:6px 0">
            {{ srv.online ? '无 GPU' : '离线' }}
          </div>
        </div>
        <a-empty v-if="!gpuMatrix.length" description="暂无服务器" />
      </a-card>

      <div style="display:flex;flex-direction:column;gap:14px;min-width:0">
        <a-card>
          <template #title><div class="panel-heading trend-panel-title">
            <b>集群资源趋势</b>
            <a-radio-group v-model:value="trendMetric" size="small">
              <a-radio-button value="gpu">GPU</a-radio-button>
              <a-radio-button value="cpu">CPU/内存</a-radio-button>
              <a-radio-button value="net">网络</a-radio-button>
              <a-radio-button value="disk">磁盘</a-radio-button>
              <a-radio-button value="power">功率</a-radio-button>
            </a-radio-group>
          </div></template>
          <v-chart :option="trendOption" class="cockpit-chart-lg" autoresize />
        </a-card>

        <a-card title="GPU 显存占用 TOP">
          <div class="rank-scroll">
          <div v-for="(r, i) in gpuMemRank" :key="r.key" class="rank-row">
            <span class="rank-no" :class="i === 0 ? 'top1' : i === 1 ? 'top2' : i === 2 ? 'top3' : ''">{{ i + 1 }}</span>
            <div class="rank-main">
              <div>{{ r.label }}</div>
              <div class="rank-sub">{{ r.server }} · {{ r.name }}</div>
            </div>
            <span class="rank-val mono">{{ fmtSizeMB(r.used) }}</span>
            <a-progress :percent="Math.round(r.pct)" :stroke-width="6" :stroke-color="utilColor(r.pct)" style="width:90px" :show-info="false" />
          </div>
          <a-empty v-if="!gpuMemRank.length" description="—" />
          </div>
        </a-card>
      </div>
    </div>

    <!-- ===== bottom: alerts ticker + process rank + net rank ===== -->
    <div class="bottom-grid">
      <a-card class="stack">
        <template #title><span>实时告警</span></template>
        <template #extra><span class="io-label">{{ openAlerts }} 条未恢复</span></template>
        <div class="ticker" v-if="alertTickerRows.length">
          <div class="ticker-inner">
            <div v-for="(a, i) in alertTickerRows" :key="i" class="ticker-row">
              <a-tag color="red">告警</a-tag>
              <span class="mono">{{ fmtTime(a.triggered_at) }}</span>
              <b>{{ a.server_name }}</b>
              <span>{{ a.message }}</span>
            </div>
          </div>
        </div>
        <div v-else class="ticker-empty">
          <CheckCircleFilled /> 全部指标正常，无未恢复告警
        </div>
      </a-card>

      <a-card class="stack" title="GPU 进程 TOP">
        <div class="fill-list">
          <div v-for="(p, i) in gpuProcRank" :key="p.pid" class="rank-row">
            <span class="rank-no" :class="i === 0 ? 'top1' : i === 1 ? 'top2' : i === 2 ? 'top3' : ''">{{ i + 1 }}</span>
            <div class="rank-main">
              <div class="mono" style="font-size:12px">{{ p.command || p.pid }}</div>
              <div class="rank-sub">{{ p.server }} · GPU{{ p.gpu }} · {{ p.user }}</div>
            </div>
            <span class="rank-val mono">{{ fmtSizeMB(p.mem_mb) }}</span>
          </div>
          <a-empty v-if="!gpuProcRank.length" description="无 GPU 进程" />
        </div>
      </a-card>

      <a-card class="stack" title="网络 / 磁盘吞吐">
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
      </a-card>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { App as AntApp } from 'ant-design-vue'
import {
  CheckCircleFilled,
  CloseCircleFilled,
  CloseOutlined,
  ThunderboltOutlined,
  WarningFilled,
} from '@ant-design/icons-vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent, DataZoomComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import api from '../api'
import RateUnitPicker from '../components/RateUnitPicker.vue'
import { diskAxisFormatter, fmtDiskRate, fmtNetRate, fmtSizeMB, fmtTime, netAxisFormatter } from '../format'
import { isAdminSession, useLatestOnly, usePoll } from '../composables'
import { chartTheme } from '../theme'

use([CanvasRenderer, LineChart, GridComponent, LegendComponent, TooltipComponent, DataZoomComponent])

const { message } = AntApp.useApp()
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
  if (r > 0.75) return '#ff4d4f'
  if (r > 0.45) return '#1677ff'
  return '#52c41a'
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
const gpuUtilDisplay = computed(() => normalizedPercent(avgGpuUtil.value))
const gpuMemoryDisplay = computed(() => normalizedPercent(gpuMemPct.value))
const cpuDisplay = computed(() => normalizedPercent(avgCpu.value))
const openAlerts = computed(() => alerts.value.filter(a => !a.recovered_at).length)

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

function normalizedPercent(value) {
  const number = Number(value)
  return Number.isFinite(number) ? Math.round(Math.min(100, Math.max(0, number))) : 0
}

function gpuUtilPercent(g) {
  return normalizedPercent(g.utilization)
}

function gpuMemoryPercent(g) {
  const total = Number(g.mem_total_mb)
  return total > 0 ? normalizedPercent((Number(g.mem_used_mb) / total) * 100) : 0
}

function gpuCellClass(g) {
  const utilization = gpuUtilPercent(g)
  const memory = gpuMemoryPercent(g)
  if (utilization >= 90 || memory >= 95) return 'gpu-cell-full'
  if (utilization >= 70 || memory >= 85) return 'gpu-cell-busy'
  return 'gpu-cell-idle'
}

async function loadAll() {
  // allSettled: one failing endpoint must never blank the whole cockpit;
  // each panel degrades independently with its own fallback value
  const [dash, gpus, energyData, powerNow, evts, latestAll, health] = await Promise.allSettled([
    api.get('/metrics/dashboard'),
    api.get('/metrics/cluster-gpus'),
    api.get('/metrics/cluster-energy?days=7'),
    api.get('/metrics/cluster-power-now'),
    api.get('/alerts/events?limit=20'),
    api.get('/metrics/latest?slim=1'),
    api.get('/cluster/health-summary'),
  ])
  const val = (r, fb) => (r.status === 'fulfilled' ? r.value.data : fb)
  stats.value = val(dash, { servers_online: 0, servers_total: 0 })
  gpuMatrix.value = val(gpus, [])
  alerts.value = val(evts, [])
  latest.value = val(latestAll, [])
  healthSummary.value = val(health, [])
  energy.value = val(energyData, null)
  const pw = val(powerNow, null)
  clusterPowerW.value = pw?.total_w ?? 0
  const failed = [dash, gpus, evts, latestAll].filter(r => r.status === 'rejected')
  if (failed.length) console.warn('[cockpit] endpoints failed:', failed.length)
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
    message.success('已触发采集')
    reloadTimer = setTimeout(() => { reload(); loadHistory() }, 5000)
  } catch (e) {
    if (e.response?.status === 409) message.info('采集进行中')
    else message.error(e.friendlyMessage || '触发失败')
  } finally {
    refreshing.value = false
  }
}

onMounted(loadHistory)
onUnmounted(() => { if (reloadTimer) clearTimeout(reloadTimer) })
</script>

<style scoped>
.cockpit-page { min-height: 100%; }
.load-alert { margin-bottom: 14px; }
.kpi-band {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}
.kpi-band :deep(.ant-card-body) { min-height: 126px; }
.kpi-note { margin-top: 4px; color: var(--csub); font-size: 12px; }
.energy-link { height: auto; margin-top: 2px; padding: 0; }
.cockpit-page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  margin-bottom: 16px;
}
.cockpit-page-identity { display: flex; align-items: center; gap: 12px; min-width: 0; }
.cockpit-page-title { font-size: 20px; font-weight: 700; letter-spacing: .035em; white-space: nowrap; }
.cockpit-page-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  color: var(--csub);
  font-size: 12px;
}
.matrix-panel-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
.panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.gpu-cell { padding: 0; }
.gpu-cell :deep(.ant-card-body) { padding: 8px 10px; }
.gpu-cell :deep(.ant-progress) { margin: 0; }
.health-chip { padding: 0; }
.health-chip :deep(.ant-card-body) {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
}
.health-ok { color: var(--cgreen); }
.health-error { color: var(--cred); }
.health-warning { color: var(--cyellow); }
.stack { display: flex; flex-direction: column; }
.stack :deep(.ant-card-body) { flex: 1; display: flex; flex-direction: column; }
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
@media (max-width: 1100px) {
  .kpi-band { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .cockpit-page-head { align-items: flex-start; }
  .cockpit-page-actions { flex-wrap: wrap; }
}
@media (max-width: 768px) {
  .cockpit-page-head { flex-direction: column; align-items: stretch; gap: 12px; }
  .cockpit-page-identity > div { flex-direction: column; gap: 2px; }
  .cockpit-page-title { font-size: 18px; }
  .cockpit-page-actions { justify-content: flex-start; gap: 8px; }
  .cockpit-page-actions > span:first-child { width: 100%; }
  .kpi-band { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  .energy-kpi { grid-column: 1 / -1; }
  .matrix-panel-title,
  .trend-panel-title { align-items: flex-start; flex-direction: column; gap: 10px; }
  .matrix-panel-actions { justify-content: flex-start; }
  .trend-panel-title :deep(.ant-radio-group) { max-width: 100%; overflow-x: auto; white-space: nowrap; }
  .health-strip { flex-wrap: wrap; overflow: visible; padding-bottom: 0; }
  .health-chip { min-width: 0; flex: 1 1 155px; }
  .cockpit-chart-lg { height: 260px; }
}
@media (max-width: 420px) {
  .kpi-value { font-size: 22px; }
  .kpi-label { letter-spacing: .02em; }
}
</style>
