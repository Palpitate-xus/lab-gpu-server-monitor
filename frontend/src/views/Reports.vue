<template>
  <div class="cockpit">
    <div class="toolbar report-toolbar">
      <el-radio-group v-model="hours" size="small" @change="load">
        <el-radio-button :value="24">24小时</el-radio-button>
        <el-radio-button :value="72">3天</el-radio-button>
        <el-radio-button :value="168">7天</el-radio-button>
      </el-radio-group>
      <el-select v-model="tag" class="report-tag-filter" placeholder="按标签筛选" clearable size="small" aria-label="按服务器标签筛选" @change="load">
        <el-option v-for="t in allTags" :key="t" :value="t" :label="t" />
      </el-select>
      <el-button size="small" :icon="Refresh" @click="load">刷新</el-button>
      <el-button size="small" :icon="Download" @click="exportCsv">导出 CSV</el-button>
    </div>

    <el-row :gutter="14" class="report-kpis">
      <el-col :span="8" :xs="{ span: 12 }"><el-card class="stat-card report-kpi-card">
        <div class="stat-value">{{ report?.total_gpu_hours ?? 0 }}</div>
        <div class="stat-label" title="窗口内">GPU 运行卡时</div>
      </el-card></el-col>
      <el-col :span="8" :xs="{ span: 12 }"><el-card class="stat-card report-kpi-card">
        <div class="stat-value" style="color:var(--cyellow)">{{ report?.total_idle_gpu_hours ?? 0 }}</div>
        <div class="stat-label" title="显存≥30% 且利用率≈0">空占卡时</div>
      </el-card></el-col>
      <el-col :span="8" :xs="{ span: 24 }"><el-card class="stat-card report-kpi-card report-kpi-card--ratio">
        <div class="stat-value">{{ idleRatio }}%</div>
        <div class="stat-label" title="空占卡时 / 总卡时">空占占比</div>
      </el-card></el-col>
    </el-row>

    <el-card class="page-card report-data-card">
      <template #header>
        <div class="report-card-head">
          <span>按服务器利用率</span>
          <span>{{ hours }}h 窗口 · 每小时聚合数据</span>
        </div>
      </template>
      <el-table class="desktop-only" :data="report?.servers || []" v-loading="loading" size="small" max-height="560"
                :default-sort="{ prop: 'idle_held_minutes', order: 'descending' }">
        <el-table-column label="服务器" min-width="150">
          <template #default="{ row }">
            <el-link type="primary" @click="$router.push(`/servers/${row.server_id}`)">{{ row.server_name }}</el-link>
          </template>
        </el-table-column>
        <el-table-column label="标签" min-width="120">
          <template #default="{ row }">
            <el-tag v-for="t in row.tags" :key="t" size="small" style="margin-right:4px">{{ t }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="hours_covered" label="覆盖小时" width="100" sortable />
        <el-table-column label="GPU 平均利用率" width="150" sortable prop="gpu_util_avg">
          <template #default="{ row }">
            <el-progress :percentage="Math.min(100, row.gpu_util_avg)" :stroke-width="10"
                         :color="row.gpu_util_avg >= 60 ? '#67c23a' : row.gpu_util_avg >= 30 ? '#e6a23c' : '#f56c6c'" />
          </template>
        </el-table-column>
        <el-table-column prop="gpu_power_avg_w" label="平均功耗 W" width="110" sortable />
        <el-table-column prop="idle_held_gpu_hours" label="空占卡时" width="110" sortable />
        <el-table-column prop="idle_ratio_pct" label="空占占比 %" width="120" sortable>
          <template #default="{ row }">
            <span :style="row.idle_ratio_pct > 30 ? 'color:var(--cred);font-weight:600' : ''">{{ row.idle_ratio_pct }}%</span>
          </template>
        </el-table-column>
        <el-table-column prop="success_rate" label="采集成功率 %" width="120" sortable />
      </el-table>

      <div class="mobile-only" v-loading="loading">
        <div v-if="report?.servers?.length" class="mobile-card-list">
          <article v-for="row in report.servers" :key="row.server_id" class="mobile-data-card report-server-card">
            <div class="mobile-data-card__head">
              <div class="mobile-data-card__title">
                <el-link type="primary" @click="$router.push(`/servers/${row.server_id}`)">{{ row.server_name }}</el-link>
              </div>
              <el-tag :type="row.idle_ratio_pct > 30 ? 'danger' : row.idle_ratio_pct > 10 ? 'warning' : 'success'" size="small">
                空占 {{ row.idle_ratio_pct }}%
              </el-tag>
            </div>
            <div v-if="row.tags?.length" class="report-server-tags">
              <el-tag v-for="t in row.tags" :key="t" size="small" effect="plain">{{ t }}</el-tag>
            </div>
            <div class="report-util-block">
              <div><span>GPU 平均利用率</span><b>{{ row.gpu_util_avg }}%</b></div>
              <el-progress
                :percentage="Math.min(100, row.gpu_util_avg)"
                :stroke-width="8"
                :show-text="false"
                :color="row.gpu_util_avg >= 60 ? '#67c23a' : row.gpu_util_avg >= 30 ? '#e6a23c' : '#f56c6c'"
              />
            </div>
            <div class="mobile-data-card__meta">
              <span>覆盖小时</span><span>{{ row.hours_covered }} h</span>
              <span>平均功耗</span><span>{{ row.gpu_power_avg_w }} W</span>
              <span>空占卡时</span><span>{{ row.idle_held_gpu_hours }}</span>
              <span>采集成功率</span><span>{{ row.success_rate }}%</span>
            </div>
          </article>
        </div>
      </div>
      <el-empty v-if="!loading && !(report?.servers?.length)" description="暂无聚合数据（小时级聚合在系统运行满 1 小时后开始产生）" :image-size="60" />
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, Refresh } from '@element-plus/icons-vue'
import api from '../api'
import { csvRow } from '../csv'

const hours = ref(24)
const tag = ref('')
const loading = ref(false)
const report = ref(null)
const allTags = ref([])

const idleRatio = computed(() => {
  const r = report.value
  if (!r || !r.total_gpu_hours) return 0
  return Math.round(r.total_idle_gpu_hours / r.total_gpu_hours * 1000) / 10
})

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/cluster/utilization-report', { params: { hours: hours.value, tag: tag.value || undefined } })
    report.value = data
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '加载失败')
  } finally {
    loading.value = false
  }
}

async function loadTags() {
  try {
    const { data } = await api.get('/servers')
    allTags.value = [...new Set(data.flatMap(s => s.tags || []))].sort()
  } catch { /* ignore */ }
}

function exportCsv() {
  const rows = report.value?.servers || []
  if (!rows.length) return ElMessage.info('没有可导出的数据')
  const head = ['服务器', '标签', '覆盖小时', 'GPU平均利用率%', '平均功耗W', '空占卡时', '空占占比%', '采集成功率%']
  const lines = [csvRow(head)]
  for (const r of rows) {
    lines.push(csvRow([
      r.server_name, (r.tags || []).join('|'), r.hours_covered,
      r.gpu_util_avg, r.gpu_power_avg_w, r.idle_held_gpu_hours, r.idle_ratio_pct, r.success_rate
    ]))
  }
  const blob = new Blob(['\ufeff' + lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `gpu-utilization-${hours.value}h.csv`
  a.click()
  URL.revokeObjectURL(a.href)
}

onMounted(() => { load(); loadTags() })
</script>

<style scoped>
.report-toolbar { margin-bottom: 0; }
.report-tag-filter { width: 160px; }
.report-kpis { margin-top: 14px; margin-bottom: 14px; }
.report-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.report-card-head > span:last-child {
  color: var(--csub);
  font-size: 12px;
}
.report-server-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin: -2px 0 11px;
}
.report-util-block {
  margin-bottom: 12px;
  padding: 10px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--cprimary) 5%, var(--cpanel));
}
.report-util-block > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 7px;
}
.report-util-block span { color: var(--csub); font-size: 12px; }
.report-util-block b { font-variant-numeric: tabular-nums; }

@media (max-width: 768px) {
  .report-toolbar .el-radio-group { width: 100%; }
  .report-toolbar :deep(.el-radio-button) { flex: 1; }
  .report-toolbar :deep(.el-radio-button__inner) { width: 100%; }
  .report-tag-filter { width: 100%; }
  .report-toolbar > .el-button { flex: 1; margin-left: 0; }
  .report-kpis .el-col { margin-bottom: 10px; }
  .report-kpis { margin-bottom: 4px; }
  .report-kpi-card :deep(.el-card__body) { padding: 13px 8px; }
  .report-kpi-card .stat-value { font-size: 20px; }
  .report-kpi-card--ratio :deep(.el-card__body) {
    display: flex;
    align-items: baseline;
    justify-content: center;
    gap: 10px;
  }
  .report-card-head { align-items: flex-start; flex-direction: column; gap: 4px; }
  .report-data-card :deep(.el-card__body) { padding: 12px; }
}
</style>
