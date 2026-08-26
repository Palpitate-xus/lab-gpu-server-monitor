<template>
  <div class="cockpit">
    <div class="toolbar">
      <el-radio-group v-model="hours" size="small" @change="load">
        <el-radio-button :value="24">24小时</el-radio-button>
        <el-radio-button :value="72">3天</el-radio-button>
        <el-radio-button :value="168">7天</el-radio-button>
      </el-radio-group>
      <el-select v-model="tag" placeholder="按标签筛选" clearable size="small" style="width:160px" @change="load">
        <el-option v-for="t in allTags" :key="t" :value="t" :label="t" />
      </el-select>
      <el-button size="small" :icon="Refresh" @click="load">刷新</el-button>
      <el-button size="small" :icon="Download" @click="exportCsv">导出 CSV</el-button>
    </div>

    <el-row :gutter="14" style="margin-top:14px">
      <el-col :span="8"><el-card class="stat-card">
        <div class="stat-value">{{ report?.total_gpu_hours ?? 0 }}</div>
        <div class="stat-label">GPU 运行卡时（窗口内）</div>
      </el-card></el-col>
      <el-col :span="8"><el-card class="stat-card">
        <div class="stat-value" style="color:var(--cyellow)">{{ report?.total_idle_gpu_hours ?? 0 }}</div>
        <div class="stat-label">空占卡时（显存≥30% 且利用率≈0）</div>
      </el-card></el-col>
      <el-col :span="8"><el-card class="stat-card">
        <div class="stat-value">{{ idleRatio }}%</div>
        <div class="stat-label">空占占比</div>
      </el-card></el-col>
    </el-row>

    <el-card style="margin-top:14px">
      <template #header>
        <span>按服务器利用率（{{ hours }}h 窗口 · 每小时聚合数据）</span>
      </template>
      <el-table :data="report?.servers || []" v-loading="loading" size="small" max-height="560"
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
      <el-empty v-if="!loading && !(report?.servers?.length)" description="暂无聚合数据（小时级聚合在系统运行满 1 小时后开始产生）" :image-size="60" />
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, Refresh } from '@element-plus/icons-vue'
import api from '../api'

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
  const lines = [head.join(',')]
  for (const r of rows) {
    lines.push([
      r.server_name, `"${(r.tags || []).join('|')}"`, r.hours_covered,
      r.gpu_util_avg, r.gpu_power_avg_w, r.idle_held_gpu_hours, r.idle_ratio_pct, r.success_rate
    ].join(','))
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
