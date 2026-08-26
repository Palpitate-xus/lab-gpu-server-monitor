<template>
  <div class="cockpit">
    <div class="toolbar">
      <el-button v-if="isAdmin" type="primary" :icon="Plus" @click="openCreate">新建规则</el-button>
      <el-button :icon="Refresh" @click="loadAll()">刷新</el-button>
      <span style="flex:1"></span>
      <el-radio-group v-model="eventFilter" size="small" @change="onFilterChange">
        <el-radio-button :value="false">全部事件</el-radio-button>
        <el-radio-button :value="true">未恢复</el-radio-button>
      </el-radio-group>
    </div>

    <el-alert v-if="pollError" type="error" show-icon :closable="false" style="margin-bottom:12px"
      :title="`刷新失败：${pollError}（30 秒后自动重试）`" />

    <el-row :gutter="14">
      <el-col :span="10">
        <el-card class="page-card">
          <template #header>告警规则 ({{ rules.length }})</template>
          <el-table :data="rules" size="small" v-loading="loadingRules" max-height="300">
            <el-table-column prop="name" label="名称" min-width="110" show-overflow-tooltip />
            <el-table-column label="条件" min-width="150">
              <template #default="{ row }">
                {{ metricLabel(row.metric) }} {{ row.op }} {{ row.threshold }}{{ unit(row.metric) }}
                <div v-if="row.duration_minutes" style="font-size:11px;color:var(--csub)">持续 {{ row.duration_minutes }} 分钟</div>
              </template>
            </el-table-column>
            <el-table-column label="范围" width="90">
              <template #default="{ row }">{{ row.server_id ? serverName(row.server_id) : '全部' }}</template>
            </el-table-column>
            <el-table-column label="启用" width="60">
              <template #default="{ row }">
                <el-switch v-model="row.enabled" size="small" :disabled="!isAdmin" @change="toggleRule(row)" />
              </template>
            </el-table-column>
            <el-table-column v-if="isAdmin" label="操作" width="110">
              <template #default="{ row }">
                <el-button size="small" @click="openEdit(row)">编辑</el-button>
                <el-popconfirm title="删除该规则？" @confirm="removeRule(row)">
                  <template #reference><el-button size="small" type="danger">删</el-button></template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="14">
        <el-card class="page-card">
          <template #header>告警事件</template>
          <el-table :data="events" size="small" v-loading="loadingEvents" :row-class-name="eventRowClass" max-height="520">
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag v-if="row.recovered_at" type="success" size="small">已恢复</el-tag>
                <el-tag v-else-if="row.acked_at" type="warning" size="small">已确认({{ row.acked_by || '—' }})</el-tag>
                <el-tag v-else type="danger" size="small">未恢复</el-tag>
                <div v-if="row.assignee" style="font-size:11px;color:var(--csub);margin-top:2px">认领：{{ row.assignee }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="server_name" label="服务器" width="120" show-overflow-tooltip />
            <el-table-column label="来源" width="100">
              <template #default="{ row }">
                <el-tag v-if="!row.rule_id" size="small" type="warning" effect="plain">内置检测</el-tag>
                <el-tag v-else size="small" type="info" effect="plain">自定义规则</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="内容" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">{{ row.message }}</template>
            </el-table-column>
            <el-table-column label="触发时间" width="150">
              <template #default="{ row }">{{ fmtTime(row.triggered_at) }}</template>
            </el-table-column>
            <el-table-column label="恢复时间" width="150">
              <template #default="{ row }">{{ row.recovered_at ? fmtTime(row.recovered_at) : '—' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="185">
              <template #default="{ row }">
                <template v-if="!row.recovered_at">
                  <el-button v-if="isAdmin" size="small" :disabled="!!row.acked_at" @click="ack(row)">确认</el-button>
                  <el-button v-if="isAdmin" size="small" type="danger" @click="resolveEvent(row)">关闭</el-button>
                  <el-button size="small" :disabled="!!row.assignee" @click="assign(row)">认领</el-button>
                </template>
                <span v-else style="color:var(--csub)">—</span>
              </template>
            </el-table-column>
          </el-table>
          <el-pagination
            background
            layout="prev, pager, next, jumper"
            :current-page="page"
            :page-size="PAGE_SIZE"
            :page-count="hasMore ? page + 1 : page"
            style="margin-top:10px;justify-content:flex-end"
            @current-change="onPageChange"
          />
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="dlg" :title="editId ? '编辑规则' : '新建规则'" width="480px">
      <el-form ref="formRef" :model="form" :rules="rules2" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="如 GPU 温度过高" />
        </el-form-item>
        <el-form-item label="指标" prop="metric">
          <el-select v-model="form.metric" style="width:100%">
            <el-option v-for="(label, key) in METRICS" :key="key" :value="key" :label="label" />
          </el-select>
        </el-form-item>
        <el-form-item label="条件">
          <el-select v-model="form.op" style="width:90px">
            <el-option value=">" label=">" /><el-option value=">=" label=">=" />
            <el-option value="<" label="<" /><el-option value="<=" label="<=" />
          </el-select>
          <el-input-number v-model="form.threshold" :min="0" :max="100000" style="width:150px;margin-left:8px" />
          <span style="margin-left:6px;color:var(--csub)">{{ unit(form.metric) }}</span>
        </el-form-item>
        <el-form-item label="持续时间">
          <el-input-number v-model="form.duration_minutes" :min="0" :max="1440" />
          <span style="margin-left:8px;color:var(--csub);font-size:12px">分钟（0 = 立即触发）</span>
        </el-form-item>
        <el-form-item label="作用范围">
          <el-select v-model="form.server_id" clearable placeholder="全部服务器" style="width:100%">
            <el-option v-for="s in servers" :key="s.id" :value="s.id" :label="s.name" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import api from '../api'
import { isAdminSession } from '../composables'
import { fmtTime } from '../format'

const isAdmin = computed(() => isAdminSession())

const METRICS = {
  cpu_percent: 'CPU 使用率',
  mem_percent: '内存使用率',
  swap_percent: 'Swap 使用率',
  disk_percent: '磁盘使用率(最大分区)',
  load_per_core: '每核负载',
  gpu_util: 'GPU 利用率(平均)',
  gpu_temp: 'GPU 温度(最高)',
  gpu_mem_percent: 'GPU 显存(最高)',
  gpu_power: 'GPU 功耗(最高)'
}
const UNITS = { gpu_temp: '°C', gpu_power: 'W', load_per_core: '' }
const unit = (m) => UNITS[m] ?? '%'
const metricLabel = (m) => METRICS[m] || m

const loadingRules = ref(false)
const loadingEvents = ref(false)
const rules = ref([])
const events = ref([])
let pollTimer = null
const servers = ref([])
const eventFilter = ref(false)
const PAGE_SIZE = 50
const page = ref(1)
const hasMore = ref(false)
const pollError = ref(null)
const dlg = ref(false)
const editId = ref(null)
const saving = ref(false)
const formRef = ref()

const blank = () => ({ name: '', metric: 'gpu_temp', op: '>', threshold: 80, duration_minutes: 0, server_id: null, enabled: true })
const form = reactive(blank())
const rules2 = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  metric: [{ required: true, message: '请选择指标', trigger: 'change' }]
}

const serverName = (id) => servers.value.find(s => s.id === id)?.name || `#${id}`

function eventRowClass({ row }) {
  return row.recovered_at ? '' : 'alert-row'
}

function onFilterChange() {
  page.value = 1
  loadAll()
}

function onPageChange(p) {
  page.value = p
  loadEvents()
}

async function loadEvents(silent = false) {
  loadingEvents.value = true
  try {
    const offset = (page.value - 1) * PAGE_SIZE
    const { data } = await api.get(`/alerts/events?open_only=${eventFilter.value}&limit=${PAGE_SIZE + 1}&offset=${offset}`)
    hasMore.value = data.length > PAGE_SIZE
    events.value = data.slice(0, PAGE_SIZE)
    pollError.value = null
  } catch (err) {
    if (silent) pollError.value = err.friendlyMessage || '加载失败'
    else ElMessage.error(err.friendlyMessage || '加载失败')
  } finally {
    loadingEvents.value = false
  }
}

async function loadAll(opts = {}) {
  const silent = !!opts.silent
  loadingRules.value = true
  try {
    const [r, s] = await Promise.all([api.get('/alerts/rules'), api.get('/servers')])
    rules.value = r.data
    servers.value = s.data
  } catch (err) {
    if (silent) pollError.value = err.friendlyMessage || '加载失败'
    else ElMessage.error(err.friendlyMessage || '加载失败')
  } finally {
    loadingRules.value = false
  }
  await loadEvents(silent)
}

function openCreate() {
  editId.value = null
  Object.assign(form, blank())
  dlg.value = true
}

function openEdit(row) {
  editId.value = row.id
  Object.assign(form, blank(), {
    name: row.name, metric: row.metric, op: row.op, threshold: row.threshold,
    duration_minutes: row.duration_minutes, server_id: row.server_id, enabled: row.enabled
  })
  dlg.value = true
}

async function save() {
  await formRef.value.validate().catch(() => Promise.reject())
  saving.value = true
  try {
    const payload = { ...form, server_id: form.server_id || null }
    if (editId.value) await api.put(`/alerts/rules/${editId.value}`, payload)
    else await api.post('/alerts/rules', payload)
    ElMessage.success('已保存')
    dlg.value = false
    loadAll()
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '保存失败')
  } finally {
    saving.value = false
  }
}

async function toggleRule(row) {
  try {
    await api.put(`/alerts/rules/${row.id}`, { enabled: row.enabled })
    ElMessage.success(row.enabled ? '已启用' : '已停用')
  } catch (e) {
    row.enabled = !row.enabled
    ElMessage.error(e.friendlyMessage || '操作失败')
  }
}

async function removeRule(row) {
  try {
    await api.delete(`/alerts/rules/${row.id}`)
    ElMessage.success('已删除')
    loadAll()
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '删除失败')
  }
}

async function ack(row) {
  try {
    await api.post(`/alerts/events/${row.id}/ack`)
    ElMessage.success('已确认')
    loadEvents()
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '操作失败')
  }
}

async function resolveEvent(row) {
  try {
    await api.post(`/alerts/events/${row.id}/resolve`)
    ElMessage.success('已关闭')
    loadEvents()
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '操作失败')
  }
}

async function assign(row) {
  try {
    await api.post(`/alerts/events/${row.id}/assign`, {})
    ElMessage.success('已认领')
    loadEvents()
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '操作失败')
  }
}

onMounted(() => {
  loadAll()
  pollTimer = setInterval(() => loadAll({ silent: true }), 30000)  // keep event stream live without manual refresh
})
onUnmounted(() => clearInterval(pollTimer))

defineExpose({ eventFilter, loadAll })
</script>

<style>
.el-table .alert-row {
  background: color-mix(in srgb, var(--cred) 10%, transparent) !important;
}
</style>
