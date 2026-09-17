<template>
  <div class="cockpit">
    <div class="toolbar alerts-toolbar">
      <a-button v-if="isAdmin" type="primary" @click="openCreate"><template #icon><PlusOutlined /></template>新建规则</a-button>
      <a-button @click="loadAll()"><template #icon><ReloadOutlined /></template>刷新</a-button>
      <span class="alerts-toolbar__spacer"></span>
      <a-radio-group v-model:value="eventFilter" size="small" @change="onFilterChange">
        <a-radio-button :value="false">全部事件</a-radio-button>
        <a-radio-button :value="true">未恢复</a-radio-button>
      </a-radio-group>
    </div>

    <a-alert v-if="pollError" type="error" show-icon class="poll-alert"
      :message="`刷新失败：${pollError}（30 秒后自动重试）`" />

    <a-row :gutter="14" class="alerts-grid">
      <a-col :span="24">
        <a-card class="page-card" :title="`告警规则 (${rules.length})`">
          <a-table class="desktop-only" :data-source="rules" size="small" :loading="loadingRules" :pagination="false" :scroll="{ x: 720, y: 300 }" row-key="id">
            <a-table-column data-index="name" title="名称" :width="150" ellipsis />
            <a-table-column title="条件" :width="230">
              <template #default="{ record: row }">
                {{ metricLabel(row.metric) }} {{ row.op }} {{ row.threshold }}{{ unit(row.metric) }}
                <div v-if="row.duration_minutes" style="font-size:11px;color:var(--csub)">持续 {{ row.duration_minutes }} 分钟</div>
              </template>
            </a-table-column>
            <a-table-column title="范围" :width="120">
              <template #default="{ record: row }">{{ row.server_id ? serverName(row.server_id) : '全部' }}</template>
            </a-table-column>
            <a-table-column title="启用" :width="80">
              <template #default="{ record: row }">
                <a-switch v-model:checked="row.enabled" size="small" :disabled="!isAdmin" @change="toggleRule(row)" />
              </template>
            </a-table-column>
            <a-table-column v-if="isAdmin" title="操作" :width="150">
              <template #default="{ record: row }">
                <div class="table-actions">
                  <a-button size="small" @click="openEdit(row)">编辑</a-button>
                  <a-popconfirm title="删除该规则？" ok-text="删除" cancel-text="取消" @confirm="removeRule(row)">
                    <a-button size="small" danger>删除</a-button>
                  </a-popconfirm>
                </div>
              </template>
            </a-table-column>
          </a-table>

          <a-spin class="mobile-only" :spinning="loadingRules">
            <div v-if="rules.length" class="mobile-card-list">
              <article v-for="row in rules" :key="row.id" class="mobile-data-card">
                <div class="mobile-data-card__head">
                  <div class="mobile-data-card__title">{{ row.name }}</div>
                  <a-switch v-model:checked="row.enabled" size="small" :disabled="!isAdmin" @change="toggleRule(row)" />
                </div>
                <div class="mobile-data-card__meta">
                  <span>触发条件</span>
                  <span>{{ metricLabel(row.metric) }} {{ row.op }} {{ row.threshold }}{{ unit(row.metric) }}</span>
                  <span>持续时间</span>
                  <span>{{ row.duration_minutes ? `${row.duration_minutes} 分钟` : '立即触发' }}</span>
                  <span>作用范围</span>
                  <span>{{ row.server_id ? serverName(row.server_id) : '全部服务器' }}</span>
                </div>
                <div v-if="isAdmin" class="mobile-data-card__actions">
                  <a-button size="small" @click="openEdit(row)">编辑规则</a-button>
                  <a-popconfirm title="删除该规则？" ok-text="删除" cancel-text="取消" @confirm="removeRule(row)">
                    <a-button size="small" danger>删除</a-button>
                  </a-popconfirm>
                </div>
              </article>
            </div>
            <a-empty v-else-if="!loadingRules" description="暂无告警规则" />
          </a-spin>
        </a-card>
      </a-col>
      <a-col :span="24">
        <a-card class="page-card" title="告警事件">
          <a-table class="desktop-only" :data-source="events" size="small" :loading="loadingEvents" :pagination="false" :row-class-name="eventRowClass" :scroll="{ x: 1080, y: 520 }" row-key="id">
            <a-table-column title="状态" :width="130">
              <template #default="{ record: row }">
                <a-tag v-if="row.recovered_at" color="green">已恢复</a-tag>
                <a-tag v-else-if="row.acked_at" color="orange">已确认({{ row.acked_by || '—' }})</a-tag>
                <a-tag v-else color="red">未恢复</a-tag>
                <div v-if="row.assignee" style="font-size:11px;color:var(--csub);margin-top:2px">认领：{{ row.assignee }}</div>
              </template>
            </a-table-column>
            <a-table-column data-index="server_name" title="服务器" :width="140" ellipsis />
            <a-table-column title="来源" :width="110">
              <template #default="{ record: row }">
                <a-tag v-if="!row.rule_id" color="orange">内置检测</a-tag>
                <a-tag v-else>自定义规则</a-tag>
              </template>
            </a-table-column>
            <a-table-column title="内容" :width="280" ellipsis>
              <template #default="{ record: row }">{{ row.message }}</template>
            </a-table-column>
            <a-table-column title="触发时间" :width="170">
              <template #default="{ record: row }">{{ fmtTime(row.triggered_at) }}</template>
            </a-table-column>
            <a-table-column title="恢复时间" :width="170">
              <template #default="{ record: row }">{{ row.recovered_at ? fmtTime(row.recovered_at) : '—' }}</template>
            </a-table-column>
            <a-table-column title="操作" :width="210" fixed="right">
              <template #default="{ record: row }">
                <template v-if="!row.recovered_at">
                  <div class="table-actions">
                    <a-button v-if="isAdmin" size="small" :disabled="!!row.acked_at" :loading="ackingId === row.id" @click="ack(row)">确认</a-button>
                    <a-popconfirm v-if="isAdmin" title="确定关闭该未恢复告警？" ok-text="关闭" cancel-text="取消" @confirm="resolveEvent(row)">
                      <a-button size="small" danger :loading="resolvingId === row.id">关闭</a-button>
                    </a-popconfirm>
                    <a-button size="small" :disabled="!!row.assignee" :loading="assigningId === row.id" @click="assign(row)">认领</a-button>
                  </div>
                </template>
                <span v-else style="color:var(--csub)">—</span>
              </template>
            </a-table-column>
          </a-table>

          <a-spin class="mobile-only" :spinning="loadingEvents">
            <div v-if="events.length" class="mobile-card-list">
              <article
                v-for="row in events"
                :key="row.id"
                class="mobile-data-card alert-event-card"
                :class="{ 'alert-event-card--open': !row.recovered_at }"
              >
                <div class="mobile-data-card__head">
                  <div class="mobile-data-card__title">{{ row.server_name || '未知服务器' }}</div>
                  <a-tag v-if="row.recovered_at" color="green">已恢复</a-tag>
                  <a-tag v-else-if="row.acked_at" color="orange">已确认</a-tag>
                  <a-tag v-else color="red">未恢复</a-tag>
                </div>
                <p class="alert-event-card__message">{{ row.message }}</p>
                <div class="mobile-data-card__meta">
                  <span>来源</span>
                  <span>{{ row.rule_id ? '自定义规则' : '内置检测' }}</span>
                  <span>触发时间</span>
                  <span>{{ fmtTime(row.triggered_at) }}</span>
                  <span>恢复时间</span>
                  <span>{{ row.recovered_at ? fmtTime(row.recovered_at) : '—' }}</span>
                  <template v-if="row.acked_at">
                    <span>确认人</span>
                    <span>{{ row.acked_by || '—' }}</span>
                  </template>
                  <template v-if="row.assignee">
                    <span>认领人</span>
                    <span>{{ row.assignee }}</span>
                  </template>
                </div>
                <div v-if="!row.recovered_at" class="mobile-data-card__actions">
                  <a-button v-if="isAdmin" size="small" :disabled="!!row.acked_at" :loading="ackingId === row.id" @click="ack(row)">确认</a-button>
                  <a-button size="small" :disabled="!!row.assignee" :loading="assigningId === row.id" @click="assign(row)">认领</a-button>
                  <a-popconfirm v-if="isAdmin" title="确定关闭该未恢复告警？" ok-text="关闭" cancel-text="取消" @confirm="resolveEvent(row)">
                    <a-button size="small" danger :loading="resolvingId === row.id">关闭事件</a-button>
                  </a-popconfirm>
                </div>
              </article>
            </div>
            <a-empty v-else-if="!loadingEvents" description="当前筛选下暂无告警事件" />
          </a-spin>
          <a-pagination
            class="alerts-pagination"
            v-model:current="page"
            :page-size="PAGE_SIZE"
            :total="paginationTotal"
            :show-size-changer="false"
            show-quick-jumper
            @change="onPageChange"
          />
        </a-card>
      </a-col>
    </a-row>

    <a-modal v-model:open="dlg" class="responsive-dialog" :title="editId ? '编辑规则' : '新建规则'" :width="520">
      <a-form ref="formRef" class="responsive-form" :model="form" :rules="rules2" :label-col="{ style: { width: '104px' } }">
        <a-form-item label="名称" name="name">
          <a-input v-model:value="form.name" placeholder="如 GPU 温度过高" />
        </a-form-item>
        <a-form-item label="指标" name="metric">
          <a-select v-model:value="form.metric" style="width:100%">
            <a-select-option v-for="(label, key) in METRICS" :key="key" :value="key">{{ label }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="条件">
          <div class="rule-condition-fields">
          <a-select v-model:value="form.op" class="rule-condition-op">
            <a-select-option value=">">&gt;</a-select-option><a-select-option value=">=">&gt;=</a-select-option>
            <a-select-option value="<">&lt;</a-select-option><a-select-option value="<=">&lt;=</a-select-option>
          </a-select>
          <a-input-number v-model:value="form.threshold" :min="0" :max="100000" class="rule-condition-value" />
          <span class="rule-condition-unit">{{ unit(form.metric) }}</span>
          </div>
        </a-form-item>
        <a-form-item label="持续时间">
          <div class="rule-duration-fields">
            <a-input-number v-model:value="form.duration_minutes" :min="0" :max="1440" />
            <span>分钟（0 = 立即触发）</span>
          </div>
        </a-form-item>
        <a-form-item label="作用范围">
          <a-select v-model:value="form.server_id" allow-clear placeholder="全部服务器" style="width:100%">
            <a-select-option v-for="s in servers" :key="s.id" :value="s.id">{{ s.name }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="启用">
          <a-switch v-model:checked="form.enabled" />
        </a-form-item>
      </a-form>
      <template #footer>
        <a-button @click="dlg = false">取消</a-button>
        <a-button type="primary" :loading="saving" @click="save">保存</a-button>
      </template>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { App as AntApp } from 'ant-design-vue'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import api from '../api'
import { isAdminSession } from '../composables'
import { fmtTime } from '../format'

const isAdmin = computed(() => isAdminSession())
const { message } = AntApp.useApp()

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
const paginationTotal = computed(() => hasMore.value
  ? page.value * PAGE_SIZE + 1
  : (page.value - 1) * PAGE_SIZE + events.value.length)
const pollError = ref(null)
const dlg = ref(false)
const editId = ref(null)
const saving = ref(false)
const formRef = ref()
const ackingId = ref(null)
const resolvingId = ref(null)
const assigningId = ref(null)

const blank = () => ({ name: '', metric: 'gpu_temp', op: '>', threshold: 80, duration_minutes: 0, server_id: null, enabled: true })
const form = reactive(blank())
const rules2 = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  metric: [{ required: true, message: '请选择指标', trigger: 'change' }]
}

const serverName = (id) => servers.value.find(s => s.id === id)?.name || `#${id}`

function eventRowClass(row) {
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
    else message.error(err.friendlyMessage || '加载失败')
  } finally {
    loadingEvents.value = false
  }
}

async function loadAll(opts = {}) {
  const silent = !!opts.silent
  loadingRules.value = true
  try {
    const [r, s] = await Promise.allSettled([api.get('/alerts/rules'), api.get('/servers')])
    if (r.status === 'fulfilled') rules.value = r.value.data
    if (s.status === 'fulfilled') servers.value = s.value.data
  } catch (err) {
    if (silent) pollError.value = err.friendlyMessage || '加载失败'
    else message.error(err.friendlyMessage || '加载失败')
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
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  saving.value = true
  try {
    const payload = { ...form, server_id: form.server_id || null }
    if (editId.value) await api.put(`/alerts/rules/${editId.value}`, payload)
    else await api.post('/alerts/rules', payload)
    message.success('已保存')
    dlg.value = false
    loadAll()
  } catch (e) {
    message.error(e.friendlyMessage || '保存失败')
  } finally {
    saving.value = false
  }
}

async function toggleRule(row) {
  try {
    await api.put(`/alerts/rules/${row.id}`, { enabled: row.enabled })
    message.success(row.enabled ? '已启用' : '已停用')
  } catch (e) {
    row.enabled = !row.enabled
    message.error(e.friendlyMessage || '操作失败')
  }
}

async function removeRule(row) {
  try {
    await api.delete(`/alerts/rules/${row.id}`)
    message.success('已删除')
    loadAll()
  } catch (e) {
    message.error(e.friendlyMessage || '删除失败')
  }
}

async function ack(row) {
  ackingId.value = row.id
  try {
    await api.post(`/alerts/events/${row.id}/ack`)
    message.success('已确认')
    loadEvents()
  } catch (e) {
    message.error(e.friendlyMessage || '操作失败')
  } finally {
    ackingId.value = null
  }
}

async function resolveEvent(row) {
  resolvingId.value = row.id
  try {
    await api.post(`/alerts/events/${row.id}/resolve`)
    message.success('已关闭')
    loadEvents()
  } catch (e) {
    message.error(e.friendlyMessage || '操作失败')
  } finally {
    resolvingId.value = null
  }
}

async function assign(row) {
  assigningId.value = row.id
  try {
    await api.post(`/alerts/events/${row.id}/assign`, {})
    message.success('已认领')
    loadEvents()
  } catch (e) {
    message.error(e.friendlyMessage || '操作失败')
  } finally {
    assigningId.value = null
  }
}

onMounted(() => {
  loadAll()
  // keep event stream live without manual refresh
  pollTimer = setInterval(() => {
    if (document.hidden) return
    loadAll({ silent: true })
  }, 30000)
})
onUnmounted(() => clearInterval(pollTimer))

defineExpose({ eventFilter, loadAll })
</script>

<style>
.ant-table .alert-row {
  background: color-mix(in srgb, var(--cred) 10%, transparent) !important;
}

.alerts-toolbar__spacer { flex: 1; }
.poll-alert { margin-bottom: 12px; }
.table-actions { display: flex; gap: 8px; }
.alerts-pagination {
  margin-top: 10px;
  justify-content: flex-end;
}
.alert-event-card--open {
  border-left: 3px solid var(--cred);
}
.alert-event-card__message {
  margin: 0 0 12px;
  padding: 10px;
  border-radius: 7px;
  background: color-mix(in srgb, var(--cred) 7%, var(--cpanel));
  color: var(--ctext);
  font-size: 13px;
  line-height: 1.55;
  overflow-wrap: anywhere;
}
.rule-condition-fields,
.rule-duration-fields {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}
.rule-condition-op { width: 90px; }
.rule-condition-value { width: 150px; }
.rule-condition-unit,
.rule-duration-fields span {
  color: var(--csub);
  font-size: 12px;
}

@media (max-width: 768px) {
  .alerts-toolbar > .ant-btn { flex: 1; }
  .alerts-toolbar__spacer { display: none; }
  .alerts-toolbar .ant-radio-group { width: 100%; display: flex; }
  .alerts-toolbar .ant-radio-button-wrapper { flex: 1; text-align: center; }
  .alerts-grid > .ant-col { max-width: 100%; }
  .alerts-grid .ant-card-body { padding: 12px; }
  .alerts-pagination {
    justify-content: center;
    overflow-x: auto;
    padding-bottom: 2px;
  }
  .mobile-data-card__actions .ant-btn + .ant-btn { margin-left: 0; }
  .rule-condition-fields { align-items: stretch; }
  .rule-condition-op { width: 82px; }
  .rule-condition-value { min-width: 0; flex: 1; }
  .rule-condition-unit { align-self: center; }
  .rule-duration-fields { align-items: flex-start; flex-direction: column; }
}
</style>
