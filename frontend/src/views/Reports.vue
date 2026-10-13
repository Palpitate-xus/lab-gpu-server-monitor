<template>
  <div class="cockpit">
    <div class="toolbar report-toolbar">
      <a-radio-group v-model:value="hours" @change="load">
        <a-radio-button :value="24">24小时</a-radio-button>
        <a-radio-button :value="72">3天</a-radio-button>
        <a-radio-button :value="168">7天</a-radio-button>
      </a-radio-group>
      <a-select v-model:value="tag" class="report-tag-filter" placeholder="按标签筛选" allow-clear aria-label="按服务器标签筛选" @change="load">
        <a-select-option v-for="t in allTags" :key="t" :value="t">{{ t }}</a-select-option>
      </a-select>
      <a-button @click="load"><template #icon><ReloadOutlined /></template>刷新</a-button>
      <a-button :disabled="loading || !report || !!loadError" @click="exportCsv"><template #icon><DownloadOutlined /></template>导出 CSV</a-button>
    </div>

    <a-alert v-if="loadError" type="error" show-icon class="load-alert" :message="`数据加载失败：${loadError}`">
      <template #action><a-button size="small" danger @click="load">重试</a-button></template>
    </a-alert>
    <a-alert v-if="report && report.card_time_complete === false" type="warning" show-icon class="load-alert"
      message="部分历史聚合缺少运行卡时：运行卡时和空占占比显示为 —，空占卡时保留历史值；可重建的数据会由后台补齐。" />
    <a-alert v-else-if="report?.card_time_estimated" type="info" show-icon class="load-alert"
      message="部分旧采样未记录采样周期，卡时为估算值；新采样使用实际记录的周期计算。" />

    <a-row :gutter="[16, 16]" class="report-kpis kpi-row">
      <a-col :xs="12" :md="8"><a-card class="report-kpi-card">
        <a-statistic title="GPU 运行卡时" :value="report?.total_gpu_hours ?? '—'" />
      </a-card></a-col>
      <a-col :xs="12" :md="8"><a-card class="report-kpi-card">
        <a-statistic title="空占卡时" :value="report?.total_idle_gpu_hours ?? '—'" />
      </a-card></a-col>
      <a-col :xs="24" :md="8"><a-card class="report-kpi-card report-kpi-card--ratio">
        <a-statistic title="空占占比" :value="idleRatio ?? '—'" :suffix="idleRatio == null ? '' : '%'" />
      </a-card></a-col>
    </a-row>

    <a-card class="page-card report-data-card">
      <template #title>
        <div class="report-card-head">
          <span>按服务器利用率</span>
          <span>{{ loadedQuery?.hours ?? hours }}h 窗口{{ loadedQuery?.tag ? ` · ${loadedQuery.tag}` : '' }} · 每小时聚合数据</span>
        </div>
      </template>
      <a-table class="desktop-only" :data-source="report?.servers || []" :loading="loading" :pagination="false" size="small" :scroll="{ x: 1000, y: 560 }" row-key="server_id">
        <a-table-column title="服务器" :width="180" ellipsis>
          <template #default="{ record: row }">
            <a-button type="link" size="small" class="table-link" :title="row.server_name" @click="$router.push(`/servers/${row.server_id}`)">{{ row.server_name }}</a-button>
          </template>
        </a-table-column>
        <a-table-column title="标签" :width="150">
          <template #default="{ record: row }">
            <a-tag v-for="t in row.tags" :key="t">{{ t }}</a-tag>
          </template>
        </a-table-column>
        <a-table-column data-index="hours_covered" title="覆盖小时" :width="110" :sorter="numberSorter('hours_covered')" />
        <a-table-column title="GPU 平均利用率" :width="170" data-index="gpu_util_avg" :sorter="numberSorter('gpu_util_avg')">
          <template #default="{ record: row }">
            <a-progress :percent="Math.min(100, row.gpu_util_avg)" :stroke-width="10" :stroke-color="utilColor(row.gpu_util_avg)" />
          </template>
        </a-table-column>
        <a-table-column data-index="gpu_power_avg_w" title="平均功耗 W" :width="120" :sorter="numberSorter('gpu_power_avg_w')" />
        <a-table-column data-index="idle_held_gpu_hours" title="空占卡时" :width="120" :sorter="numberSorter('idle_held_gpu_hours')" default-sort-order="descend" />
        <a-table-column data-index="idle_ratio_pct" title="空占占比 %" :width="130" :sorter="numberSorter('idle_ratio_pct')">
          <template #default="{ record: row }">
            <span :style="row.idle_ratio_pct > 30 ? 'color:var(--cred);font-weight:600' : ''">{{ row.idle_ratio_pct == null ? '—' : `${row.idle_ratio_pct}%` }}</span>
          </template>
        </a-table-column>
        <a-table-column data-index="success_rate" title="采集成功率 %" :width="130" :sorter="numberSorter('success_rate')" />
      </a-table>

      <a-spin wrapper-class-name="mobile-only" :spinning="loading">
        <div v-if="report?.servers?.length" class="mobile-card-list">
          <article v-for="row in report.servers" :key="row.server_id" class="mobile-data-card report-server-card">
            <div class="mobile-data-card__head">
              <div class="mobile-data-card__title">
                <a-button type="link" size="small" class="table-link" @click="$router.push(`/servers/${row.server_id}`)">{{ row.server_name }}</a-button>
              </div>
              <a-tag :color="idleRatioColor(row.idle_ratio_pct)">
                空占 {{ row.idle_ratio_pct == null ? '—' : `${row.idle_ratio_pct}%` }}
              </a-tag>
            </div>
            <div v-if="row.tags?.length" class="report-server-tags">
              <a-tag v-for="t in row.tags" :key="t">{{ t }}</a-tag>
            </div>
            <div class="report-util-block">
              <div><span>GPU 平均利用率</span><b>{{ row.gpu_util_avg }}%</b></div>
              <a-progress
                :percent="Math.min(100, row.gpu_util_avg)"
                :stroke-width="8"
                :show-info="false"
                :stroke-color="utilColor(row.gpu_util_avg)"
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
      </a-spin>
      <a-empty v-if="!loading && !loadError && !(report?.servers?.length)" description="暂无聚合数据（小时级聚合在系统运行满 1 小时后开始产生）" />
    </a-card>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { App as AntApp } from 'ant-design-vue'
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import api from '../api'
import { csvRow } from '../csv'
import { createRequestScope } from '../requestState'

const hours = ref(24)
const { message } = AntApp.useApp()
const tag = ref('')
const loading = ref(false)
const loadError = ref('')
const report = ref(null)
const allTags = ref([])
const loadedQuery = ref(null)
const reportRequests = createRequestScope()

const idleRatio = computed(() => {
  const r = report.value
  return r?.idle_ratio_pct ?? null
})

const numberSorter = key => (a, b) => (Number(a[key]) || 0) - (Number(b[key]) || 0)

function idleRatioColor(value) {
  if (value == null) return undefined
  return value > 30 ? 'red' : value > 10 ? 'orange' : 'green'
}

function utilColor(value) {
  if (value >= 60) return 'var(--cgreen)'
  if (value >= 30) return 'var(--cyellow)'
  return 'var(--cred)'
}

async function load() {
  const request = reportRequests.begin()
  const query = { hours: hours.value, tag: tag.value || undefined }
  loading.value = true
  loadError.value = ''
  try {
    const { data } = await api.get('/cluster/utilization-report', { params: query, signal: request.signal })
    if (!request.current()) return
    report.value = data
    loadedQuery.value = query
  } catch (e) {
    if (!request.current()) return
    loadError.value = e.friendlyMessage || '加载失败'
  } finally {
    if (request.current()) loading.value = false
  }
}

async function loadTags() {
  try {
    const { data } = await api.get('/servers')
    allTags.value = [...new Set(data.flatMap(s => s.tags || []))].sort()
  } catch { /* ignore */ }
}

function exportCsv() {
  if (loading.value || loadError.value) return
  const rows = report.value?.servers || []
  if (!rows.length) return message.info('没有可导出的数据')
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
  a.download = `gpu-utilization-${loadedQuery.value.hours}h.csv`
  a.click()
  URL.revokeObjectURL(a.href)
}

onMounted(() => { load(); loadTags() })
onUnmounted(() => reportRequests.dispose())
</script>

<style scoped>
.load-alert { margin-top: 12px; }
.table-link { height: auto; padding: 0; }
.report-tag-filter { width: 160px; }
.report-kpis { margin-bottom: 16px; }
.report-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.report-card-head > span { white-space: normal; overflow-wrap: anywhere; }
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
  .report-toolbar .ant-radio-group { width: 100%; display: flex; }
  .report-toolbar :deep(.ant-radio-button-wrapper) { flex: 1; text-align: center; }
  .report-tag-filter { width: 100%; }
  .report-toolbar > .ant-btn { flex: 1; margin-left: 0; }
  .report-kpi-card :deep(.ant-card-body) { padding: 13px 8px; }
  .report-kpi-card :deep(.ant-statistic-title) { font-size: 12px; }
  .report-kpi-card :deep(.ant-statistic-content) { font-size: 20px; }
  .report-card-head { align-items: flex-start; flex-direction: column; gap: 4px; }
  .report-data-card :deep(.ant-card-body) { padding: 12px; }
}
</style>
