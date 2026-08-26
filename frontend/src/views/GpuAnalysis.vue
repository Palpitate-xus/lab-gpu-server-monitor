<template>
  <div class="cockpit">
    <div class="toolbar">
      <el-page-header content="GPU 智能分析" />
      <div style="display:flex;gap:10px;align-items:center">
        <span v-if="lastUpdated" style="font-size:12px;color:var(--csub)">更新于 {{ lastUpdated.toLocaleTimeString('zh-CN') }}</span>
        <el-radio-group v-model="viewMode" size="small">
          <el-radio-button value="idle">空占检测</el-radio-button>
          <el-radio-button value="risk">故障预测</el-radio-button>
          <el-radio-button value="all">全部 GPU</el-radio-button>
        </el-radio-group>
        <el-button size="small" :icon="Refresh" @click="load">刷新</el-button>
      </div>
    </div>

    <!-- ===== summary cards ===== -->
    <el-row :gutter="14" style="margin-bottom:14px">
      <el-col :span="6">
        <el-card class="stat-card cockpit-panel">
          <div class="kpi-value">{{ summary.total_gpus }}<span class="kpi-unit">卡</span></div>
          <div class="kpi-label">集群 GPU 总数</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card cockpit-panel kpi-accent-yellow">
          <div class="kpi-value" style="color:var(--cyellow)">{{ summary.idle_held_count }}<span class="kpi-unit">卡</span></div>
          <div class="kpi-label">空占（占卡不计算）</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card cockpit-panel kpi-accent-purple">
          <div class="kpi-value" style="color:var(--cpurple)">{{ summary.high_risk_count }}<span class="kpi-unit">卡</span></div>
          <div class="kpi-label">风险关注（≥30 分）</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card cockpit-panel kpi-accent-green">
          <div class="kpi-value" style="color:var(--cgreen)">{{ healthyCount }}<span class="kpi-unit">卡</span></div>
          <div class="kpi-label">健康（低风险无空占）</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- ===== main table ===== -->
    <el-card class="cockpit-panel">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>{{ viewTitle }}</span>
          <span style="font-size:12px;color:var(--csub)">{{ viewHint }}</span>
        </div>
      </template>
      <el-table :data="filtered" size="small" v-loading="loading" :row-class-name="rowClass" max-height="560">
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
      <el-empty v-if="!loading && !filtered.length" :description="emptyText" :image-size="60" />
    </el-card>

    <!-- ===== how it works ===== -->
    <el-card class="cockpit-panel" style="margin-top:14px">
      <template #header>判定规则</template>
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="空占（GPU Idle Held）">显存占用 ≥30% 且利用率 <5% 持续 30 分钟以上 —— 通常是僵尸进程或程序卡死后占着显存</el-descriptions-item>
        <el-descriptions-item label="疑似（观察中）">当前满足空占条件但持续时间不足 30 分钟，继续观察</el-descriptions-item>
        <el-descriptions-item label="风险评分（0-100）">近 24h：Xid 事件每条 +20（上限40）、不可纠正 ECC 每 条 +5（上限25）、热降频采样 +5~15、高温 ≥85°C +5、PCIe 链路降级 +5</el-descriptions-item>
        <el-descriptions-item label="风险分级">≥60 高危（建议检查/重启）、30-59 关注（观察趋势）、<30 健康</el-descriptions-item>
      </el-descriptions>
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
let timer = null

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/cluster/gpu-analysis')
    summary.value = data
    lastUpdated.value = new Date()
  } catch {
    /* ignore */
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
.risk-factors { display: flex; gap: 4px; flex-wrap: wrap; }
.proc-list { display: flex; flex-direction: column; gap: 2px; }
.proc-line { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
:deep(.row-idle-held) { background: color-mix(in srgb, var(--cyellow) 8%, transparent) !important; }
:deep(.row-high-risk) { background: color-mix(in srgb, var(--cred) 8%, transparent) !important; }
:deep(.row-watch) { background: color-mix(in srgb, var(--cyellow) 5%, transparent) !important; }
</style>
