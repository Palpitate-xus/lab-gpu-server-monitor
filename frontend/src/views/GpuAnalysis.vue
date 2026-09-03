<template>
  <div class="cockpit">
    <div class="toolbar analysis-toolbar">
      <div class="analysis-heading">
        <b>GPU 智能分析</b>
        <span>识别空占资源与潜在硬件风险</span>
      </div>
      <div class="analysis-controls">
        <span v-if="lastUpdated" class="analysis-updated">更新于 {{ lastUpdated.toLocaleTimeString('zh-CN') }}</span>
        <el-radio-group v-model="viewMode" size="small">
          <el-radio-button value="idle">空占检测</el-radio-button>
          <el-radio-button value="risk">故障预测</el-radio-button>
          <el-radio-button value="all">全部 GPU</el-radio-button>
        </el-radio-group>
        <el-button size="small" :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <el-alert v-if="loadError" :title="`数据加载失败：${loadError}（保留上次数据，1 分钟后重试）`" type="error" show-icon :closable="false" style="margin-bottom:12px" />

    <!-- ===== summary cards ===== -->
    <el-row :gutter="14" class="analysis-kpis">
      <el-col :span="6" :xs="{ span: 12 }">
        <div class="cockpit-panel kpi-accent-cyan">
          <div class="kpi-value">{{ summary.total_gpus }}<span class="kpi-unit">卡</span></div>
          <div class="kpi-label">集群 GPU 总数</div>
        </div>
      </el-col>
      <el-col :span="6" :xs="{ span: 12 }">
        <div class="cockpit-panel kpi-accent-yellow">
          <div class="kpi-value kpi-solid-yellow">{{ summary.idle_held_count }}<span class="kpi-unit">卡</span></div>
          <div class="kpi-label">空占（占卡不计算）</div>
        </div>
      </el-col>
      <el-col :span="6" :xs="{ span: 12 }">
        <div class="cockpit-panel kpi-accent-purple">
          <div class="kpi-value kpi-solid-purple">{{ summary.high_risk_count }}<span class="kpi-unit">卡</span></div>
          <div class="kpi-label">风险关注（≥30 分）</div>
        </div>
      </el-col>
      <el-col :span="6" :xs="{ span: 12 }">
        <div class="cockpit-panel kpi-accent-green">
          <div class="kpi-value kpi-solid-green">{{ healthyCount }}<span class="kpi-unit">卡</span></div>
          <div class="kpi-label">健康（低风险无空占）</div>
        </div>
      </el-col>
    </el-row>

    <!-- ===== main table ===== -->
    <el-card class="cockpit-panel">
      <template #header>
        <div class="analysis-card-head">
          <span>{{ viewTitle }}</span>
          <span>{{ viewHint }}</span>
        </div>
      </template>
      <el-table class="desktop-only" :data="filtered" size="small" v-loading="loading" :row-class-name="rowClass" max-height="560">
        <el-table-column label="服务器" width="130" show-overflow-tooltip>
          <template #default="{ row }">
            <el-link @click="$router.push(`/servers/${row.server_id}`)">{{ row.server_name }}</el-link>
          </template>
        </el-table-column>
        <el-table-column label="GPU" width="60">
          <template #default="{ row }"><b>{{ row.gpu_index }}</b></template>
        </el-table-column>
        <el-table-column prop="name" label="型号" width="160" show-overflow-tooltip />
        <el-table-column label="利用率" width="100">
          <template #default="{ row }">
            <span :style="{ color: row.util > 5 ? '' : 'var(--cyellow)' }">{{ row.util }}%</span>
          </template>
        </el-table-column>
        <el-table-column label="显存占用" width="130">
          <template #default="{ row }">
            <el-progress :percentage="pct(row.mem_pct)" :stroke-width="8" :color="utilColor(row.mem_pct)" :show-text="false" style="width:80px" />
            <span class="mono" style="font-size:11px;margin-left:6px">{{ row.mem_used_gb }}G</span>
          </template>
        </el-table-column>
        <el-table-column label="空占状态" width="150">
          <template #default="{ row }">
            <el-tag v-if="row.idle_held" type="danger" effect="dark" size="small">
              空占 {{ fmtIdleMin(row.idle_minutes) }}
            </el-tag>
            <el-tag v-else-if="row.mem_pct >= 30 && row.util < 5" type="warning" size="small">疑似（观察中）</el-tag>
            <el-tag v-else-if="row.util < 5 && row.mem_pct < 30" type="info" size="small">空闲</el-tag>
            <el-tag v-else type="success" size="small">使用中</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="风险评分" width="200">
          <template #default="{ row }">
            <div style="display:flex;align-items:center;gap:8px">
              <el-progress :percentage="pct(row.risk)" :stroke-width="8" :show-text="false" :color="riskColor(row.risk)" style="width:90px" />
              <b :style="{ color: riskColor(row.risk) }">{{ row.risk }}</b>
              <el-tag size="small" :type="row.risk >= 60 ? 'danger' : row.risk >= 30 ? 'warning' : 'success'">{{ row.risk_label }}</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="风险因素" min-width="220">
          <template #default="{ row }">
            <div class="risk-factors">
              <el-tag v-if="row.xid_events" type="danger" size="small" effect="plain">Xid×{{ row.xid_events }}</el-tag>
              <el-tag v-if="row.ecc_uncorrected" type="danger" size="small" effect="plain">ECC不可纠正×{{ row.ecc_uncorrected }}</el-tag>
              <el-tag v-if="row.thermal_throttle" type="warning" size="small" effect="plain">热降频×{{ row.thermal_throttle }}</el-tag>
              <el-tag v-if="row.max_temp >= 80" type="warning" size="small" effect="plain">{{ row.max_temp }}°C</el-tag>
              <span v-if="!row.xid_events && !row.ecc_uncorrected && !row.thermal_throttle && row.max_temp < 80" style="color:var(--csub)">无异常信号</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="持有进程" min-width="200">
          <template #default="{ row }">
            <div v-if="row.processes?.length" class="proc-list">
              <div v-for="p in row.processes" :key="p.pid" class="proc-line">
                <span class="mono" style="color:var(--cprimary)">{{ p.pid }}</span>
                <span style="color:var(--csub);margin:0 4px">{{ p.user }}</span>
                <span class="mono" style="font-size:11px">{{ p.command }}</span>
              </div>
            </div>
            <span v-else style="color:var(--csub)">—</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-only" v-loading="loading">
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
                <el-link @click="$router.push(`/servers/${row.server_id}`)">{{ row.server_name }}</el-link>
                <span class="analysis-gpu-index">GPU {{ row.gpu_index }}</span>
              </div>
              <el-tag size="small" :type="row.risk >= 60 ? 'danger' : row.risk >= 30 ? 'warning' : 'success'">
                {{ row.risk_label }} · {{ row.risk }} 分
              </el-tag>
            </div>
            <div class="analysis-gpu-model">{{ row.name }}</div>
            <div class="analysis-mobile-metrics">
              <div>
                <span>GPU 利用率</span>
                <b :class="{ 'metric-warning': row.util < 5 }">{{ row.util }}%</b>
                <el-progress :percentage="pct(row.util)" :stroke-width="6" :show-text="false" :color="utilColor(row.util)" />
              </div>
              <div>
                <span>显存占用</span>
                <b>{{ row.mem_used_gb }} GB · {{ row.mem_pct }}%</b>
                <el-progress :percentage="pct(row.mem_pct)" :stroke-width="6" :show-text="false" :color="utilColor(row.mem_pct)" />
              </div>
            </div>
            <div class="analysis-status-line">
              <span>资源状态</span>
              <el-tag v-if="row.idle_held" type="danger" effect="dark" size="small">空占 {{ fmtIdleMin(row.idle_minutes) }}</el-tag>
              <el-tag v-else-if="row.mem_pct >= 30 && row.util < 5" type="warning" size="small">疑似空占（观察中）</el-tag>
              <el-tag v-else-if="row.util < 5 && row.mem_pct < 30" type="info" size="small">空闲</el-tag>
              <el-tag v-else type="success" size="small">使用中</el-tag>
            </div>
            <div class="analysis-mobile-section">
              <span>风险因素</span>
              <div class="risk-factors">
                <el-tag v-if="row.xid_events" type="danger" size="small" effect="plain">Xid×{{ row.xid_events }}</el-tag>
                <el-tag v-if="row.ecc_uncorrected" type="danger" size="small" effect="plain">ECC 不可纠正×{{ row.ecc_uncorrected }}</el-tag>
                <el-tag v-if="row.thermal_throttle" type="warning" size="small" effect="plain">热降频×{{ row.thermal_throttle }}</el-tag>
                <el-tag v-if="row.max_temp >= 80" type="warning" size="small" effect="plain">{{ row.max_temp }}°C</el-tag>
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
      </div>
      <el-empty v-if="!loading && !filtered.length" :description="emptyText" :image-size="60" />
    </el-card>

    <!-- ===== how it works ===== -->
    <el-card class="cockpit-panel" style="margin-top:14px">
      <template #header>判定规则</template>
      <el-descriptions class="desktop-only" :column="2" border size="small">
        <el-descriptions-item label="空占（GPU Idle Held）">显存占用 ≥30% 且利用率 <5% 持续 30 分钟以上 —— 通常是僵尸进程或程序卡死后占着显存</el-descriptions-item>
        <el-descriptions-item label="疑似（观察中）">当前满足空占条件但持续时间不足 30 分钟，继续观察</el-descriptions-item>
        <el-descriptions-item label="风险评分（0-100）">近 24h：Xid 事件每条 +20（上限40）、不可纠正 ECC 每 条 +5（上限25）、热降频采样 +5~15、高温 ≥85°C +5、PCIe 链路降级 +5</el-descriptions-item>
        <el-descriptions-item label="风险分级">≥60 高危（建议检查/重启）、30-59 关注（观察趋势）、<30 健康</el-descriptions-item>
      </el-descriptions>
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
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import api from '../api'
import { pct } from '../format'
import { chartTheme } from '../theme'

const loading = ref(false)
const summary = ref({ total_gpus: 0, idle_held_count: 0, high_risk_count: 0, gpus: [] })
const viewMode = ref('idle')
const lastUpdated = ref(null)
const loadError = ref('')
let timer = null

async function load() {
  if (document.hidden) return
  loading.value = true
  try {
    const { data } = await api.get('/cluster/gpu-analysis')
    summary.value = data
    lastUpdated.value = new Date()
    loadError.value = ''
  } catch (e) {
    loadError.value = e?.friendlyMessage || String(e)
  } finally {
    loading.value = false
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
  idle: '空占 GPU（占卡不计算）', risk: '风险 GPU（故障预测）', all: '全部 GPU',
}[viewMode.value]))

const viewHint = computed(() => ({
  idle: '显存占用≥30% 且利用率≈0 —— 疑似僵尸进程，可联系用户或清理',
  risk: '基于 24h Xid/ECC/热降频/高温/PCIe 信号的加权评分',
  all: '集群全部 GPU 当前状态与风险',
}[viewMode.value]))

const emptyText = computed(() => ({
  idle: '没有空占 GPU，资源利用健康', risk: '没有风险 GPU，全部健康', all: '暂无数据',
}[viewMode.value]))

function rowClass({ row }) {
  if (row.idle_held) return 'row-idle-held'
  if (row.risk >= 60) return 'row-high-risk'
  if (row.risk >= 30) return 'row-watch'
  return ''
}

function fmtIdleMin(m) {
  if (m >= 60) return `${Math.floor(m / 60)}h${Math.round(m % 60)}m`
  return `${m}分钟`
}
function riskColor(v) {
  const T = chartTheme.value
  if (v >= 60) return T.red
  if (v >= 30) return T.yellow
  return T.green
}
function utilColor(v) {
  const T = chartTheme.value
  if (v >= 90) return T.red
  if (v >= 70) return T.yellow
  return T.green
}

onMounted(() => {
  load()
  timer = setInterval(load, 60000)
})
onUnmounted(() => clearInterval(timer))
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
  gap: 10px;
}
.analysis-kpis { margin-bottom: 14px; }
.analysis-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
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
  .analysis-controls .el-radio-group { min-width: 0; flex: 1; }
  .analysis-controls :deep(.el-radio-button) { flex: 1; }
  .analysis-controls :deep(.el-radio-button__inner) { width: 100%; padding-inline: 8px; }
  .analysis-kpis .el-col { margin-bottom: 10px; }
  .analysis-kpis { margin-bottom: 4px; }
  .analysis-card-head { align-items: flex-start; flex-direction: column; gap: 5px; }
  .analysis-gpu-card .el-tag { max-width: 48%; }
}
</style>
