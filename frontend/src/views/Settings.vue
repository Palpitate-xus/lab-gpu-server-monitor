<template>
  <div class="cockpit">
    <el-row :gutter="14">
      <el-col :span="12">
        <el-card class="page-card">
          <template #header>采集与数据</template>
          <el-form label-width="130px" style="max-width:480px">
            <el-form-item label="采集间隔 (秒)">
              <el-input-number v-model="pollInterval" :min="10" :max="3600" />
            </el-form-item>
            <el-form-item label="数据保留 (天)">
              <el-input-number v-model="retentionDays" :min="0" :max="3650" />
              <div style="font-size:12px;color:var(--csub)">0 = 永久保存全部历史数据</div>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingSettings" @click="saveSettings">保存</el-button>
            </el-form-item>
          </el-form>
          <el-descriptions :column="1" border style="max-width:560px">
            <el-descriptions-item label="调度器状态">
              <el-tag :type="status.running ? 'success' : 'danger'" size="small">{{ status.running ? '运行中' : '停止' }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="当前间隔">{{ status.interval }} 秒</el-descriptions-item>
            <el-descriptions-item label="上次采集">{{ fmtTime(status.last_run) }}（耗时 {{ status.last_duration }}s）</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card class="page-card">
          <template #header>告警通知 (Webhook)</template>
          <el-form label-width="120px">
            <el-form-item label="Webhook URL">
              <el-input v-model="webhookUrl" placeholder="https://example.com/hook（留空禁用）" />
            </el-form-item>
            <el-form-item label="消息模板">
              <el-input v-model="webhookTemplate" type="textarea" :rows="4" class="mono"
                placeholder='{"text": "[{{level}}] {{server_name}}: {{metric}}={{value}} {{op}} {{threshold}}"}' />
              <div style="font-size:12px;color:var(--csub);line-height:1.6">
                变量: {{level}} {{server_name}} {{metric}} {{value}} {{op}} {{threshold}} {{rule_name}} {{time}}<br>
                默认发 JSON，可直接填企业微信/钉钉/飞书机器人兼容模板
              </div>
            </el-form-item>
            <el-form-item>
              <el-button :loading="testing" @click="testWebhook">发送测试</el-button>
              <el-button type="primary" :loading="savingWebhook" @click="saveWebhook">保存</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>
    <el-row :gutter="14">
      <el-col :span="12">
        <el-card v-if="isAdmin" class="page-card">
          <template #header>
            <div style="display:flex;align-items:center;justify-content:space-between">
              <span>通知通道 ({{ channels.length }})</span>
              <el-button size="small" type="primary" :icon="Plus" @click="openChannelDialog">新增通道</el-button>
            </div>
          </template>
          <el-table :data="channels" size="small" v-loading="loadingChannels" max-height="300">
            <el-table-column prop="name" label="名称" min-width="100" show-overflow-tooltip />
            <el-table-column prop="url" label="URL" min-width="160" show-overflow-tooltip />
            <el-table-column label="最低严重度" width="100">
              <template #default="{ row }">
                <el-tag :type="SEVERITY_TYPES[row.min_severity] || 'info'" size="small">
                  {{ SEVERITY_LABELS[row.min_severity] || row.min_severity }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="60">
              <template #default="{ row }">
                <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '是' : '否' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="70">
              <template #default="{ row }">
                <el-popconfirm title="删除该通道？" @confirm="removeChannel(row)">
                  <template #reference><el-button size="small" type="danger">删</el-button></template>
                </el-popconfirm>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card class="page-card">
          <template #header>检测阈值</template>
          <el-form label-width="150px" style="max-width:480px" v-loading="loadingThresholds">
            <el-form-item label="空占显存阈值 (%)">
              <el-input-number v-model="thresholds.gpu_idle_vram_pct" :min="1" :max="95" />
            </el-form-item>
            <el-form-item label="空占持续 (分钟)">
              <el-input-number v-model="thresholds.gpu_idle_minutes" :min="5" :max="1440" />
            </el-form-item>
            <el-form-item label="CPU 健康阈值 (%)">
              <el-input-number v-model="thresholds.health_cpu_pct" :min="50" :max="100" />
            </el-form-item>
            <el-form-item label="内存健康阈值 (%)">
              <el-input-number v-model="thresholds.health_mem_pct" :min="50" :max="100" />
            </el-form-item>
            <el-form-item label="磁盘健康阈值 (%)">
              <el-input-number v-model="thresholds.health_disk_pct" :min="50" :max="100" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingThresholds" @click="saveThresholds">保存</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>

    <StatusPageConfig />

    <el-card class="page-card">
      <template #header>操作日志</template>
      <el-table :data="logs" size="small" v-loading="loadingLogs" max-height="420">
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ fmtTime(row.ts) }}</template>
        </el-table-column>
        <el-table-column prop="username" label="用户" width="100" />
        <el-table-column prop="action" label="操作" width="140" />
        <el-table-column prop="detail" label="详情" min-width="240" show-overflow-tooltip />
      </el-table>
    </el-card>

    <el-dialog v-model="channelDlg" title="新增通知通道" width="480px">
      <el-form ref="channelFormRef" :model="channelForm" :rules="channelRules" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="channelForm.name" placeholder="如 运维群机器人" />
        </el-form-item>
        <el-form-item label="URL" prop="url">
          <el-input v-model="channelForm.url" placeholder="https://example.com/hook" />
        </el-form-item>
        <el-form-item label="消息模板">
          <el-input v-model="channelForm.template" type="textarea" :rows="3" class="mono"
            placeholder="留空则使用全局默认模板" />
        </el-form-item>
        <el-form-item label="最低严重度">
          <el-select v-model="channelForm.min_severity" style="width:100%">
            <el-option v-for="s in SEVERITIES" :key="s.value" :value="s.value" :label="s.label" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="channelForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="channelDlg = false">取消</el-button>
        <el-button type="primary" :loading="savingChannel" @click="saveChannel">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import api from '../api'
import StatusPageConfig from '../components/StatusPageConfig.vue'
import { isAdminSession } from '../composables'
import { fmtTime } from '../format'

const isAdmin = computed(() => isAdminSession())

const pollInterval = ref(60)
const retentionDays = ref(0)
const webhookUrl = ref('')
const webhookTemplate = ref('')
const savingSettings = ref(false)
const savingWebhook = ref(false)
const testing = ref(false)
const status = ref({})
const logs = ref([])
const loadingLogs = ref(false)

const channels = ref([])
const loadingChannels = ref(false)
const channelDlg = ref(false)
const savingChannel = ref(false)
const channelFormRef = ref()
const channelForm = reactive({ name: '', url: '', template: '', min_severity: 'info', enabled: true })
const channelRules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  url: [{ required: true, message: '请输入 URL', trigger: 'blur' }]
}
const SEVERITIES = [
  { value: 'info', label: '信息 (info)' },
  { value: 'warning', label: '警告 (warning)' },
  { value: 'critical', label: '严重 (critical)' }
]
const SEVERITY_LABELS = { info: '信息', warning: '警告', critical: '严重' }
const SEVERITY_TYPES = { info: 'info', warning: 'warning', critical: 'danger' }

const thresholds = reactive({
  gpu_idle_vram_pct: 30, gpu_idle_minutes: 30,
  health_cpu_pct: 90, health_mem_pct: 92, health_disk_pct: 90
})
const loadingThresholds = ref(false)
const savingThresholds = ref(false)

async function load() {
  try {
    const { data } = await api.get('/settings')
    pollInterval.value = data.poll_interval
    retentionDays.value = data.retention_days
    webhookUrl.value = data.webhook_url || ''
    webhookTemplate.value = data.webhook_template || ''
    status.value = data.scheduler || {}
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '加载失败')
  }
}

async function loadLogs() {
  loadingLogs.value = true
  try {
    const { data } = await api.get('/audit-logs?limit=200')
    logs.value = data
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '加载失败')
  } finally {
    loadingLogs.value = false
  }
}

async function saveSettings() {
  savingSettings.value = true
  try {
    await api.put('/settings', { poll_interval: pollInterval.value, retention_days: retentionDays.value })
    ElMessage.success('已保存，下一轮采集生效')
    load()
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '保存失败')
  } finally {
    savingSettings.value = false
  }
}

async function saveWebhook() {
  savingWebhook.value = true
  try {
    await api.put('/settings', { webhook_url: webhookUrl.value, webhook_template: webhookTemplate.value })
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '保存失败')
  } finally {
    savingWebhook.value = false
  }
}

async function testWebhook() {
  if (!webhookUrl.value) return ElMessage.warning('请先填写 Webhook URL')
  testing.value = true
  try {
    await api.post('/alerts/test-webhook', { url: webhookUrl.value, template: webhookTemplate.value })
    ElMessage.success('测试消息已发送，请查收')
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '发送失败')
  } finally {
    testing.value = false
  }
}

async function loadChannels() {
  loadingChannels.value = true
  try {
    const { data } = await api.get('/alerts/channels')
    channels.value = data
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '加载失败')
  } finally {
    loadingChannels.value = false
  }
}

function openChannelDialog() {
  Object.assign(channelForm, { name: '', url: '', template: '', min_severity: 'info', enabled: true })
  channelDlg.value = true
}

async function saveChannel() {
  await channelFormRef.value.validate().catch(() => Promise.reject())
  savingChannel.value = true
  try {
    await api.post('/alerts/channels', { ...channelForm })
    ElMessage.success('已添加')
    channelDlg.value = false
    loadChannels()
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '保存失败')
  } finally {
    savingChannel.value = false
  }
}

async function removeChannel(row) {
  try {
    await api.delete(`/alerts/channels/${row.id}`)
    ElMessage.success('已删除')
    loadChannels()
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '删除失败')
  }
}

async function loadThresholds() {
  loadingThresholds.value = true
  try {
    const { data } = await api.get('/settings/thresholds')
    Object.assign(thresholds, data)
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '加载失败')
  } finally {
    loadingThresholds.value = false
  }
}

async function saveThresholds() {
  savingThresholds.value = true
  try {
    await api.put('/settings/thresholds', { ...thresholds })
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '保存失败')
  } finally {
    savingThresholds.value = false
  }
}

onMounted(() => { load(); loadLogs(); loadChannels(); loadThresholds() })
</script>
