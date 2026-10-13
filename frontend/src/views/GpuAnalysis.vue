<template>
  <div class="cockpit">
    <div class="toolbar analysis-toolbar">
      <div class="analysis-heading">
        <b>GPU 分析</b>
        <span>找出占着显存却没在算的卡，以及有故障风险的卡</span>
      </div>
      <div class="analysis-controls">
        <span v-if="lastUpdated" class="analysis-updated">更新于 {{ lastUpdated.toLocaleTimeString('zh-CN') }}</span>
        <a-radio-group v-model:value="viewMode">
          <a-radio-button value="idle">空占检测</a-radio-button>
          <a-radio-button value="risk">故障预测</a-radio-button>
          <a-radio-button value="all">全部 GPU</a-radio-button>
        </a-radio-group>
        <a-button @click="load"><template #icon><ReloadOutlined /></template>刷新</a-button>
      </div>
    </div>

    <a-alert v-if="loadError" :message="`数据加载失败：${loadError}（保留上次数据，1 分钟后重试）`" type="error" show-icon class="load-alert" />

    <!-- ===== summary cards ===== -->
    <a-row :gutter="[16, 16]" class="analysis-kpis kpi-row">
      <a-col :xs="12" :lg="6">
        <a-card><a-statistic title="集群 GPU 总数" :value="summary.total_gpus" suffix="卡" /></a-card>
      </a-col>
      <a-col :xs="12" :lg="6">
        <a-card><a-statistic title="已确认空占" :value="summary.idle_held_count" suffix="卡" /></a-card>
      </a-col>
      <a-col :xs="12" :lg="6">
        <a-card><a-statistic title="风险关注（≥30 分）" :value="summary.high_risk_count" suffix="卡" /></a-card>
      </a-col>
      <a-col :xs="12" :lg="6">
        <a-card><a-statistic title="健康（低风险无空占）" :value="healthyCount" suffix="卡" /></a-card>
      </a-col>
    </a-row>

    <!-- ===== main table ===== -->
    <a-card>
      <template #title>
        <div class="analysis-card-head">
          <span>{{ viewTitle }}</span>
          <span>{{ viewHint }}</span>
        </div>
      </template>
      <a-table class="desktop-only" :data-source="filtered" size="small" :loading="loading" :pagination="false" :row-class-name="rowClass" :scroll="{ x: 1180, y: 560 }" :row-key="rowKey">
        <a-table-column title="服务器 / GPU" :width="210" ellipsis>
          <template #default="{ record: row }">
            <a-button type="link" size="small" class="table-link" :title="row.server_name" @click="$router.push(`/servers/${row.server_id}`)">{{ row.server_name }}</a-button>
            <div class="analysis-server-meta">GPU {{ row.gpu_index }} · {{ row.name }}</div>
          </template>
        </a-table-column>
        <a-table-column title="利用率" :width="90">
          <template #default="{ record: row }">
            <span :style="{ color: row.util > 5 ? '' : 'var(--cyellow)' }">{{ row.util }}%</span>
          </template>
        </a-table-column>
        <a-table-column title="显存占用" :width="150">
          <template #default="{ record: row }">
            <a-progress :percent="pct(row.mem_pct)" :stroke-width="8" :stroke-color="utilColor(row.mem_pct)" :show-info="false" style="width:80px" />
            <span class="mono" style="font-size:11px;margin-left:6px">{{ row.mem_used_gb }}G</span>
          </template>
        </a-table-column>
        <a-table-column title="空占状态" :width="160">
          <template #default="{ record: row }">
            <a-tag v-if="row.idle_held" color="red">
              空占 {{ fmtIdleMin(row.idle_minutes) }}
            </a-tag>
            <a-tag v-else-if="row.mem_pct >= 30 && row.util < 5" color="orange">疑似（观察中）</a-tag>
            <a-tag v-else-if="row.util < 5 && row.mem_pct < 30">空闲</a-tag>
            <a-tag v-else color="green">使用中</a-tag>
          </template>
        </a-table-column>
        <a-table-column title="风险评分" :width="190">
          <template #default="{ record: row }">
            <div style="display:flex;align-items:center;gap:8px">
              <a-progress :percent="pct(row.risk)" :stroke-width="8" :show-info="false" :stroke-color="riskColor(row.risk)" style="width:90px" />
              <b :style="{ color: riskColor(row.risk) }">{{ row.risk }}</b>
              <a-tag :color="riskTagColor(row.risk)">{{ row.risk_label }}</a-tag>
            </div>
          </template>
        </a-table-column>
        <a-table-column title="风险因素" :width="230">
          <template #default="{ record: row }">
            <div class="risk-factors">
              <a-tag v-if="row.xid_events" color="red">Xid×{{ row.xid_events }}</a-tag>
              <a-tag v-if="row.ecc_uncorrected" color="red">ECC不可纠正×{{ row.ecc_uncorrected }}</a-tag>
              <a-tag v-if="row.thermal_throttle" color="orange">热降频×{{ row.thermal_throttle }}</a-tag>
              <a-tag v-if="row.max_temp >= 80" color="orange">{{ row.max_temp }}°C</a-tag>
              <span v-if="!row.xid_events && !row.ecc_uncorrected && !row.thermal_throttle && row.max_temp < 80" style="color:var(--csub)">无异常信号</span>
            </div>
          </template>
        </a-table-column>
        <a-table-column title="持有进程" :width="240">
          <template #default="{ record: row }">
            <div v-if="row.processes?.length" class="proc-list">
              <div v-for="p in row.processes" :key="p.pid" class="proc-line">
                <span class="mono" style="color:var(--cprimary)">{{ p.pid }}</span>
                <span style="color:var(--csub);margin:0 4px">{{ p.user }}</span>
                <span class="mono" style="font-size:11px">{{ p.command }}</span>
              </div>
            </div>
            <span v-else style="color:var(--csub)">—</span>
          </template>
        </a-table-column>
      </a-table>

      <a-spin wrapper-class-name="mobile-only" :spinning="loading">
        <div v-if="filtered.length" class="mobile-card-list">
          <article
            v-for="row in filtered"
            :key="`${row.server_id}-${row.gpu_index}`"
            class="mobile-data-card analysis-gpu-card"
            :class="{
              'analysis-gpu-card--danger': row.idle_held || row.risk >= 60,
              'analysis-gpu-card--warning': !row.idle_held && row.risk >= 30 && row.risk < 60,
            }"
          >
            <div class="mobile-data-card__head">
              <div class="mobile-data-card__title">
                <a-button type="link" size="small" class="table-link" @click="$router.push(`/servers/${row.server_id}`)">{{ row.server_name }}</a-button>
                <span class="analysis-gpu-index">GPU {{ row.gpu_index }}</span>
              </div>
              <a-tag :color="riskTagColor(row.risk)">
                {{ row.risk_label }} · {{ row.risk }} 分
              </a-tag>
            </div>
            <div class="analysis-gpu-model">{{ row.name }}</div>
            <div class="analysis-mobile-metrics">
              <div>
                <span>GPU 利用率</span>
                <b :class="{ 'metric-warning': row.util < 5 }">{{ row.util }}%</b>
                <a-progress :percent="pct(row.util)" :stroke-width="6" :show-info="false" :stroke-color="utilColor(row.util)" />
              </div>
              <div>
                <span>显存占用</span>
                <b>{{ row.mem_used_gb }} GB · {{ row.mem_pct }}%</b>
                <a-progress :percent="pct(row.mem_pct)" :stroke-width="6" :show-info="false" :stroke-color="utilColor(row.mem_pct)" />
              </div>
            </div>
            <div class="analysis-status-line">
              <span>资源状态</span>
              <a-tag v-if="row.idle_held" color="red">空占 {{ fmtIdleMin(row.idle_minutes) }}</a-tag>
              <a-tag v-else-if="row.mem_pct >= 30 && row.util < 5" color="orange">疑似空占（观察中）</a-tag>
              <a-tag v-else-if="row.util < 5 && row.mem_pct < 30">空闲</a-tag>
              <a-tag v-else color="green">使用中</a-tag>
            </div>
            <div class="analysis-mobile-section">
              <span>风险因素</span>
              <div class="risk-factors">
                <a-tag v-if="row.xid_events" color="red">Xid×{{ row.xid_events }}</a-tag>
                <a-tag v-if="row.ecc_uncorrected" color="red">ECC 不可纠正×{{ row.ecc_uncorrected }}</a-tag>
                <a-tag v-if="row.thermal_throttle" color="orange">热降频×{{ row.thermal_throttle }}</a-tag>
                <a-tag v-if="row.max_temp >= 80" color="orange">{{ row.max_temp }}°C</a-tag>
                <span v-if="!row.xid_events && !row.ecc_uncorrected && !row.thermal_throttle && row.max_temp < 80" class="analysis-muted">无异常信号</span>
              </div>
            </div>
            <div class="analysis-mobile-section">
              <span>持有进程</span>
              <div v-if="row.processes?.length" class="proc-list">
                <div v-for="p in row.processes" :key="p.pid" class="analysis-mobile-proc">
                  <span class="mono">{{ p.pid }}</span>
                  <span>{{ p.user }}</span>
                  <span class="mono">{{ p.command }}</span>
                </div>
              </div>
              <span v-else class="analysis-muted">暂无进程</span>
            </div>
          </article>
        </div>
      </a-spin>
      <a-empty v-if="!loading && !filtered.length" :description="emptyText" />
    </a-card>

    <!-- ===== how it works ===== -->
    <a-card title="判定规则" style="margin-top:14px">
      <a-descriptions class="desktop-only" :column="2" border size="small">
        <a-descriptions-item label="空占（GPU Idle Held）">显存占用 ≥30% 且利用率 <5% 持续 30 分钟以上 —— 通常是僵尸进程或程序卡死后占着显存</a-descriptions-item>
        <a-descriptions-item label="疑似（观察中）">当前满足空占条件但持续时间不足 30 分钟，继续观察</a-descriptions-item>
        <a-descriptions-item label="风险评分（0-100）">近 24h：Xid 事件每条 +20（上限40）、不可纠正 ECC 每 条 +5（上限25）、热降频采样 +5~15、高温 ≥85°C +5、PCIe 链路降级 +5</a-descriptions-item>
        <a-descriptions-item label="风险分级">≥60 高危（建议检查/重启）、30-59 关注（观察趋势）、<30 健康</a-descriptions-item>
      </a-descriptions>
      <div class="mobile-only analysis-rule-list">
        <section>
          <b>空占（GPU Idle Held）</b>
          <p>显存占用 ≥30% 且利用率 &lt;5% 持续 30 分钟以上，通常是僵尸进程或程序异常后仍占用显存。</p>
        </section>
        <section>
          <b>疑似（观察中）</b>
          <p>当前满足空占条件，但持续时间不足 30 分钟，系统会继续观察。</p>
        </section>
        <section>
          <b>风险评分（0–100）</b>
          <p>综合近 24 小时 Xid、ECC、热降频、高温和 PCIe 链路信号计算。</p>
        </section>
        <section>
          <b>风险分级</b>
          <p>60 分及以上为高危，30–59 分需要关注，低于 30 分为健康。</p>
        </section>
      </div>
    </a-card>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ReloadOutlined } from '@ant-design/icons-vue'
import api from '../api'
import { fmtDuration, pct } from '../format'
import { chartTheme } from '../theme'
import { createRequestScope } from '../requestState'

const loading = ref(false)
const summary = ref({ total_gpus: 0, idle_held_count: 0, high_risk_count: 0, gpus: [] })
const viewMode = ref('idle')
const lastUpdated = ref(null)
const loadError = ref('')
let timer = null
const requests = createRequestScope()

async function load() {
  if (document.hidden) return
  const request = requests.begin()
  loading.value = true
  try {
    const { data } = await api.get('/cluster/gpu-analysis', { signal: request.signal })
    if (!request.current()) return
    summary.value = data
    lastUpdated.value = new Date()
    loadError.value = ''
  } catch (e) {
    if (!request.current()) return
    loadError.value = e?.friendlyMessage || String(e)
  } finally {
    if (request.current()) loading.value = false
  }
}

const gpus = computed(() => summary.value.gpus || [])
const healthyCount = computed(() =>
  gpus.value.filter(g => !g.idle_held && g.risk < 30).length)

const filtered = computed(() => {
  if (viewMode.value === 'idle') {
    return gpus.value.filter(g => g.idle_held || (g.mem_pct >= 30 && g.util < 5))
  }
  if (viewMode.value === 'risk') {
    return gpus.value.filter(g => g.risk >= 30)
  }
  return gpus.value
})

const viewTitle = computed(() => ({
  idle: '空占检测：已确认与疑似候选', risk: '风险 GPU（故障预测）', all: '全部 GPU',
}[viewMode.value]))

const viewHint = computed(() => ({
  idle: '疑似候选仍在观察，不计入「已确认空占」；确认状态由后端持续检测判定',
  risk: '基于 24h Xid/ECC/热降频/高温/PCIe 信号的加权评分',
  all: '集群全部 GPU 当前状态与风险',
}[viewMode.value]))

const emptyText = computed(() => ({
  idle: '没有空占 GPU，资源利用健康', risk: '没有风险 GPU，全部健康', all: '暂无数据',
}[viewMode.value]))

const rowKey = row => `${row.server_id}-${row.gpu_index}`

function rowClass(row) {
  if (row.idle_held) return 'row-idle-held'
  if (row.risk >= 60) return 'row-high-risk'
  if (row.risk >= 30) return 'row-watch'
  return ''
}

function fmtIdleMin(m) {
  if (!m || m <= 0) return '—'
  // idle state is tracked per minute, so fmtDuration's seconds are always zero
  return fmtDuration(m * 60).replace(/ 0s$/, '')
}
function riskColor(v) {
  const T = chartTheme.value
  if (v >= 60) return T.red
  if (v >= 30) return T.yellow
  return T.green
}
function riskTagColor(value) {
  if (value >= 60) return 'red'
  if (value >= 30) return 'orange'
  return 'green'
}
function utilColor(v) {
  const T = chartTheme.value
  if (v >= 90) return T.red
  if (v >= 70) return T.yellow
  return T.green
}

function onVisibilityChange() { if (!document.hidden) load() }
onMounted(() => {
  document.addEventListener('visibilitychange', onVisibilityChange)
  load()
  timer = setInterval(load, 60000)
})
onUnmounted(() => {
  requests.dispose()
  clearInterval(timer)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<style scoped>
.analysis-toolbar {
  justify-content: space-between;
}
.analysis-heading {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.analysis-heading b { font-size: 16px; }
.analysis-heading span,
.analysis-updated,
.analysis-card-head > span:last-child {
  color: var(--csub);
  font-size: 12px;
}
.analysis-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.analysis-kpis { margin-bottom: 16px; }
.load-alert { margin-bottom: 12px; }
.table-link { height: auto; padding: 0; }
.analysis-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.analysis-card-head > span { min-width: 0; white-space: normal; overflow-wrap: anywhere; }
.analysis-card-head > span:last-child { flex: 1; line-height: 1.6; font-weight: 400; }
.analysis-server-meta {
  margin-top: 3px;
  overflow: hidden;
  color: var(--csub);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.kpi-solid-yellow { background: none; -webkit-background-clip: unset; background-clip: unset; color: var(--cyellow); }
.kpi-solid-purple { background: none; -webkit-background-clip: unset; background-clip: unset; color: var(--cpurple); }
.kpi-solid-green  { background: none; -webkit-background-clip: unset; background-clip: unset; color: var(--cgreen); }
.risk-factors { display: flex; gap: 4px; flex-wrap: wrap; }
.proc-list { display: flex; flex-direction: column; gap: 2px; }
.proc-line { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
:deep(.row-idle-held) { background: color-mix(in srgb, var(--cyellow) 8%, transparent) !important; }
:deep(.row-high-risk) { background: color-mix(in srgb, var(--cred) 8%, transparent) !important; }
:deep(.row-watch) { background: color-mix(in srgb, var(--cyellow) 5%, transparent) !important; }
.analysis-gpu-card--danger { border-left: 3px solid var(--cred); }
.analysis-gpu-card--warning { border-left: 3px solid var(--cyellow); }
.analysis-gpu-index {
  margin-left: 7px;
  color: var(--csub);
  font-size: 12px;
}
.analysis-gpu-model {
  margin: -3px 0 12px;
  color: var(--csub);
  font-size: 12px;
}
.analysis-mobile-metrics {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.analysis-mobile-metrics > div {
  min-width: 0;
  padding: 10px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--cprimary) 5%, var(--cpanel));
}
.analysis-mobile-metrics span,
.analysis-mobile-metrics b { display: block; }
.analysis-mobile-metrics span {
  margin-bottom: 4px;
  color: var(--csub);
  font-size: 11px;
}
.analysis-mobile-metrics b {
  margin-bottom: 7px;
  font-size: 14px;
}
.metric-warning { color: var(--cyellow); }
.analysis-status-line,
.analysis-mobile-section {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-top: 12px;
}
.analysis-status-line > span:first-child,
.analysis-mobile-section > span:first-child {
  flex: 0 0 68px;
  color: var(--csub);
  font-size: 12px;
}
.analysis-mobile-section .risk-factors,
.analysis-mobile-section .proc-list { min-width: 0; flex: 1; }
.analysis-mobile-proc {
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr);
  gap: 6px;
  font-size: 11px;
}
.analysis-mobile-proc > span:last-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.analysis-muted { color: var(--csub); font-size: 12px; }
.analysis-rule-list {
  display: grid;
  gap: 10px;
}
.analysis-rule-list section {
  padding: 12px;
  border: 1px solid var(--cborder);
  border-radius: 8px;
  background: color-mix(in srgb, var(--cprimary) 3%, var(--cpanel));
}
.analysis-rule-list section + section { margin-top: 10px; }
.analysis-rule-list b { font-size: 13px; }
.analysis-rule-list p {
  margin: 5px 0 0;
  color: var(--csub);
  font-size: 12px;
  line-height: 1.6;
}

@media (max-width: 768px) {
  .analysis-toolbar { align-items: stretch; }
  .analysis-heading { width: 100%; }
  .analysis-controls { width: 100%; flex-wrap: wrap; }
  .analysis-updated { order: 3; width: 100%; text-align: right; }
  .analysis-controls .ant-radio-group { min-width: 0; flex: 1; display: flex; }
  .analysis-controls :deep(.ant-radio-button-wrapper) { flex: 1; padding-inline: 8px; text-align: center; }
  .analysis-kpis :deep(.ant-card-body) { padding: 16px 12px; }
  .analysis-kpis :deep(.ant-statistic-title) { min-height: 44px; }
  .analysis-card-head { align-items: flex-start; flex-direction: column; gap: 5px; }
  .analysis-gpu-card .ant-tag { max-width: 48%; }
}
</style>
