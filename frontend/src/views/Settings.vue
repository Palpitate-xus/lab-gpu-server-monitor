<template>
  <div class="cockpit">
    <nav class="settings-jump-nav" aria-label="设置分区快捷导航">
      <a-button type="text" size="small" @click="scrollToSection('settings-collection')">采集与数据</a-button>
      <a-button type="text" size="small" @click="scrollToSection('settings-webhook')">告警通知</a-button>
      <a-button type="text" size="small" @click="scrollToSection('settings-thresholds')">检测阈值</a-button>
      <a-button type="text" size="small" @click="scrollToSection('settings-status-page')">公开状态页</a-button>
      <a-button type="text" size="small" @click="scrollToSection('settings-logs')">操作日志</a-button>
    </nav>

    <a-row :gutter="14" class="settings-grid">
      <a-col id="settings-collection" :span="12" :xs="24" class="settings-section">
        <a-card class="page-card settings-card" title="采集与数据">
          <a-form class="settings-form" :label-col="{ style: { width: '136px' } }">
            <a-form-item label="采集间隔 (秒)">
              <a-input-number v-model:value="pollInterval" :min="10" :max="3600" />
            </a-form-item>
            <a-form-item label="数据保留 (天)">
              <a-input-number v-model:value="retentionDays" :min="0" :max="3650" />
              <div class="settings-hint">0 = 永久保存全部历史数据</div>
            </a-form-item>
            <a-form-item label="电价 (¥/kWh)">
              <a-input-number v-model:value="energyPrice" :min="0" :max="100" :step="0.05" :precision="2" />
              <div class="settings-hint">电量费用估算，0 = 不计算</div>
            </a-form-item>
            <a-form-item>
              <a-button type="primary" :loading="savingSettings" @click="saveSettings">保存</a-button>
            </a-form-item>
          </a-form>
          <a-descriptions :column="1" border style="max-width:560px">
            <a-descriptions-item label="调度器状态">
              <a-tag :color="status.running ? 'green' : 'red'">{{ status.running ? '运行中' : '停止' }}</a-tag>
            </a-descriptions-item>
            <a-descriptions-item label="当前间隔">{{ status.interval }} 秒</a-descriptions-item>
            <a-descriptions-item label="上次采集">{{ fmtTime(status.last_run) }}（耗时 {{ status.last_duration }}s）</a-descriptions-item>
          </a-descriptions>
        </a-card>
      </a-col>
      <a-col id="settings-webhook" :span="12" :xs="24" class="settings-section">
        <a-card class="page-card settings-card" title="告警通知 (Webhook)">
          <a-form class="settings-form webhook-form" :label-col="{ style: { width: '126px' } }">
            <a-form-item label="Webhook URL">
              <a-input v-model:value="webhookUrl" :placeholder="webhookConfigured ? '已加密保存；留空表示保持不变' : 'https://example.com/hook'" />
              <div v-if="webhookConfigured" class="settings-hint">已配置，出于安全原因不回显 URL/令牌。</div>
            </a-form-item>
            <a-form-item label="消息模板">
              <a-textarea v-model:value="webhookTemplate" :rows="4" class="mono"
                placeholder='{"text": "[{{level}}] {{server_name}}: {{metric}}={{value}} {{op}} {{threshold}}"}' />
              <div class="settings-hint settings-template-hint">
                <span v-pre>变量: {{level}} {{server_name}} {{metric}} {{value}} {{op}} {{threshold}} {{rule_name}} {{time}}</span><br>
                默认发 JSON，可直接填企业微信/钉钉/飞书机器人兼容模板
              </div>
            </a-form-item>
            <a-form-item class="settings-form-actions">
              <a-button :loading="testing" @click="testWebhook">发送测试</a-button>
              <a-button type="primary" :loading="savingWebhook" @click="saveWebhook">保存</a-button>
              <a-button v-if="webhookConfigured" danger @click="clearWebhook">清除</a-button>
            </a-form-item>
          </a-form>
        </a-card>
      </a-col>
    </a-row>
    <a-row :gutter="14" class="settings-grid">
      <a-col id="settings-channels" :span="12" :xs="24" class="settings-section">
        <a-card v-if="isAdmin" class="page-card settings-card">
          <template #title>
            <div class="settings-card-head">
              <span>通知通道 ({{ channels.length }})</span>
              <a-button size="small" type="primary" @click="openChannelDialog"><template #icon><PlusOutlined /></template>新增通道</a-button>
            </div>
          </template>
          <a-table class="desktop-only" :data-source="channels" size="small" :loading="loadingChannels" :pagination="false" :scroll="{ x: 620, y: 300 }" row-key="id">
            <a-table-column data-index="name" title="名称" :width="130" ellipsis />
            <a-table-column data-index="url" title="URL" :width="220" ellipsis />
            <a-table-column title="最低严重度" :width="120">
              <template #default="{ record: row }">
                <a-tag :color="SEVERITY_COLORS[row.min_severity]">
                  {{ SEVERITY_LABELS[row.min_severity] || row.min_severity }}
                </a-tag>
              </template>
            </a-table-column>
            <a-table-column title="启用" :width="80">
              <template #default="{ record: row }">
                <a-tag :color="row.enabled ? 'green' : undefined">{{ row.enabled ? '是' : '否' }}</a-tag>
              </template>
            </a-table-column>
            <a-table-column title="操作" :width="90">
              <template #default="{ record: row }">
                <a-popconfirm title="删除该通道？" ok-text="删除" cancel-text="取消" @confirm="removeChannel(row)">
                  <a-button size="small" danger>删除</a-button>
                </a-popconfirm>
              </template>
            </a-table-column>
          </a-table>
          <a-spin class="mobile-only" :spinning="loadingChannels">
            <div v-if="channels.length" class="mobile-card-list">
              <article v-for="row in channels" :key="row.id" class="mobile-data-card">
                <div class="mobile-data-card__head">
                  <div class="mobile-data-card__title">{{ row.name }}</div>
                  <a-tag :color="row.enabled ? 'green' : undefined">{{ row.enabled ? '已启用' : '已停用' }}</a-tag>
                </div>
                <div class="mobile-data-card__meta">
                  <span>Webhook URL</span><span class="settings-break-text">{{ row.url }}</span>
                  <span>最低严重度</span><span>{{ SEVERITY_LABELS[row.min_severity] || row.min_severity }}</span>
                </div>
                <div class="mobile-data-card__actions">
                  <a-popconfirm title="删除该通道？" ok-text="删除" cancel-text="取消" @confirm="removeChannel(row)">
                    <a-button size="small" danger>删除通道</a-button>
                  </a-popconfirm>
                </div>
              </article>
            </div>
            <a-empty v-else-if="!loadingChannels" description="暂无通知通道" />
          </a-spin>
        </a-card>
      </a-col>
      <a-col id="settings-thresholds" :span="12" :xs="24" class="settings-section">
        <a-card class="page-card settings-card" title="检测阈值">
          <a-spin :spinning="loadingThresholds">
          <a-form class="settings-form" :label-col="{ style: { width: '156px' } }">
            <a-form-item label="空占显存阈值 (%)">
              <a-input-number v-model:value="thresholds.gpu_idle_vram_pct" :min="1" :max="95" />
            </a-form-item>
            <a-form-item label="空占持续 (分钟)">
              <a-input-number v-model:value="thresholds.gpu_idle_minutes" :min="5" :max="1440" />
            </a-form-item>
            <a-form-item label="CPU 健康阈值 (%)">
              <a-input-number v-model:value="thresholds.health_cpu_pct" :min="50" :max="100" />
            </a-form-item>
            <a-form-item label="内存健康阈值 (%)">
              <a-input-number v-model:value="thresholds.health_mem_pct" :min="50" :max="100" />
            </a-form-item>
            <a-form-item label="磁盘健康阈值 (%)">
              <a-input-number v-model:value="thresholds.health_disk_pct" :min="50" :max="100" />
            </a-form-item>
            <a-form-item>
              <a-button type="primary" :loading="savingThresholds" @click="saveThresholds">保存</a-button>
            </a-form-item>
          </a-form>
          </a-spin>
        </a-card>
      </a-col>
    </a-row>

    <div id="settings-status-page" class="settings-section">
      <StatusPageConfig />
    </div>

    <a-card id="settings-logs" class="page-card settings-section settings-log-card">
      <template #title>
        <div class="settings-card-head">
          <span>操作日志</span>
          <span class="settings-card-meta">最近 {{ logs.length }} 条</span>
        </div>
      </template>
      <a-table class="desktop-only" :data-source="logs" size="small" :loading="loadingLogs" :pagination="false" :scroll="{ x: 720, y: 420 }" :row-key="logRowKey">
        <a-table-column title="时间" :width="180">
          <template #default="{ record: row }">{{ fmtTime(row.ts) }}</template>
        </a-table-column>
        <a-table-column data-index="username" title="用户" :width="120" />
        <a-table-column data-index="action" title="操作" :width="160" />
        <a-table-column data-index="detail" title="详情" ellipsis />
      </a-table>
      <a-spin class="mobile-only" :spinning="loadingLogs">
        <div v-if="logs.length" class="mobile-card-list">
          <article v-for="(row, index) in logs" :key="`${row.ts}-${index}`" class="mobile-data-card settings-log-item">
            <div class="mobile-data-card__head">
              <div class="mobile-data-card__title">{{ row.action }}</div>
              <span>{{ fmtTime(row.ts) }}</span>
            </div>
            <div class="mobile-data-card__meta">
              <span>用户</span><span>{{ row.username || '—' }}</span>
              <span>详情</span><span class="settings-break-text">{{ row.detail || '—' }}</span>
            </div>
          </article>
        </div>
        <a-empty v-else-if="!loadingLogs" description="暂无操作日志" />
      </a-spin>
    </a-card>

    <a-modal v-model:open="channelDlg" class="responsive-dialog" title="新增通知通道" :width="500">
      <a-form ref="channelFormRef" class="responsive-form" :model="channelForm" :rules="channelRules" :label-col="{ style: { width: '106px' } }">
        <a-form-item label="名称" name="name">
          <a-input v-model:value="channelForm.name" placeholder="如 运维群机器人" />
        </a-form-item>
        <a-form-item label="URL" name="url">
          <a-input v-model:value="channelForm.url" placeholder="https://example.com/hook" />
        </a-form-item>
        <a-form-item label="消息模板">
          <a-textarea v-model:value="channelForm.template" :rows="3" class="mono"
            placeholder="留空则使用全局默认模板" />
        </a-form-item>
        <a-form-item label="最低严重度">
          <a-select v-model:value="channelForm.min_severity" style="width:100%">
            <a-select-option v-for="s in SEVERITIES" :key="s.value" :value="s.value">{{ s.label }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="启用">
          <a-switch v-model:checked="channelForm.enabled" />
        </a-form-item>
      </a-form>
      <template #footer>
        <a-button @click="channelDlg = false">取消</a-button>
        <a-button type="primary" :loading="savingChannel" @click="saveChannel">保存</a-button>
      </template>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { App as AntApp } from 'ant-design-vue'
import { PlusOutlined } from '@ant-design/icons-vue'
import api from '../api'
import StatusPageConfig from '../components/StatusPageConfig.vue'
import { isAdminSession } from '../composables'
import { fmtTime } from '../format'

const isAdmin = computed(() => isAdminSession())
const { message, modal } = AntApp.useApp()

const pollInterval = ref(60)
const retentionDays = ref(0)
const energyPrice = ref(0)
const webhookUrl = ref('')
const webhookConfigured = ref(false)
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
const SEVERITY_COLORS = { info: undefined, warning: 'orange', critical: 'red' }

const thresholds = reactive({
  gpu_idle_vram_pct: 30, gpu_idle_minutes: 30,
  health_cpu_pct: 90, health_mem_pct: 92, health_disk_pct: 90
})
const loadingThresholds = ref(false)
const savingThresholds = ref(false)
const logRowKey = (row, index) => `${row.ts}-${index}`

function scrollToSection(id) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function load() {
  try {
    const { data } = await api.get('/settings')
    pollInterval.value = data.poll_interval
    retentionDays.value = data.retention_days
    energyPrice.value = data.energy_price ?? 0
    webhookUrl.value = data.webhook_url || ''
    webhookConfigured.value = Boolean(data.webhook_url_configured)
    webhookTemplate.value = data.webhook_template || ''
    status.value = data.scheduler || {}
  } catch (e) {
    message.error(e.friendlyMessage || '加载失败')
  }
}

async function loadLogs() {
  loadingLogs.value = true
  try {
    const { data } = await api.get('/audit-logs?limit=200')
    logs.value = data
  } catch (e) {
    message.error(e.friendlyMessage || '加载失败')
  } finally {
    loadingLogs.value = false
  }
}

async function saveSettings() {
  savingSettings.value = true
  try {
    await api.put('/settings', { poll_interval: pollInterval.value, retention_days: retentionDays.value, energy_price: energyPrice.value })
    message.success('已保存，下一轮采集生效')
    load()
  } catch (e) {
    message.error(e.friendlyMessage || '保存失败')
  } finally {
    savingSettings.value = false
  }
}

async function saveWebhook() {
  savingWebhook.value = true
  try {
    const payload = { webhook_template: webhookTemplate.value }
    if (webhookUrl.value.trim()) payload.webhook_url = webhookUrl.value.trim()
    await api.put('/settings', payload)
    if (payload.webhook_url) {
      webhookConfigured.value = true
      webhookUrl.value = ''
    }
    message.success('已保存')
  } catch (e) {
    message.error(e.friendlyMessage || '保存失败')
  } finally {
    savingWebhook.value = false
  }
}

async function testWebhook() {
  if (!webhookUrl.value.trim() && !webhookConfigured.value) return message.warning('请先填写 Webhook URL')
  testing.value = true
  try {
    await api.post('/alerts/test-webhook', { url: webhookUrl.value.trim(), template: webhookTemplate.value })
    message.success('测试消息已发送，请查收')
  } catch (e) {
    message.error(e.friendlyMessage || '发送失败')
  } finally {
    testing.value = false
  }
}

function clearWebhook() {
  modal.confirm({
    title: '清除 Webhook',
    content: '确认清除已保存的 Webhook URL？',
    okText: '确认清除',
    cancelText: '取消',
    okType: 'danger',
    async onOk() {
      await runClearWebhook()
    },
  })
}

async function runClearWebhook() {
  try {
    await api.put('/settings', { webhook_url: '' })
    webhookUrl.value = ''
    webhookConfigured.value = false
    message.success('Webhook 已清除')
  } catch (e) {
    message.error(e.friendlyMessage || '清除失败')
    throw e
  }
}

async function loadChannels() {
  loadingChannels.value = true
  try {
    const { data } = await api.get('/alerts/channels')
    channels.value = data
  } catch (e) {
    message.error(e.friendlyMessage || '加载失败')
  } finally {
    loadingChannels.value = false
  }
}

function openChannelDialog() {
  Object.assign(channelForm, { name: '', url: '', template: '', min_severity: 'info', enabled: true })
  channelDlg.value = true
}

async function saveChannel() {
  try {
    await channelFormRef.value.validate()
  } catch {
    return
  }
  savingChannel.value = true
  try {
    await api.post('/alerts/channels', { ...channelForm })
    message.success('已添加')
    channelDlg.value = false
    loadChannels()
  } catch (e) {
    message.error(e.friendlyMessage || '保存失败')
  } finally {
    savingChannel.value = false
  }
}

async function removeChannel(row) {
  try {
    await api.delete(`/alerts/channels/${row.id}`)
    message.success('已删除')
    loadChannels()
  } catch (e) {
    message.error(e.friendlyMessage || '删除失败')
  }
}

async function loadThresholds() {
  loadingThresholds.value = true
  try {
    const { data } = await api.get('/settings/thresholds')
    Object.assign(thresholds, data)
  } catch (e) {
    message.error(e.friendlyMessage || '加载失败')
  } finally {
    loadingThresholds.value = false
  }
}

async function saveThresholds() {
  savingThresholds.value = true
  try {
    await api.put('/settings/thresholds', { ...thresholds })
    message.success('已保存')
  } catch (e) {
    message.error(e.friendlyMessage || '保存失败')
  } finally {
    savingThresholds.value = false
  }
}

onMounted(() => { load(); loadLogs(); loadChannels(); loadThresholds() })
</script>

<style scoped>
.settings-jump-nav {
  position: sticky;
  top: 0;
  z-index: 6;
  display: flex;
  gap: 6px;
  margin: -2px 0 14px;
  padding: 7px;
  overflow-x: auto;
  border: 1px solid var(--cborder);
  border-radius: 8px;
  background: var(--cpanel);
  scrollbar-width: thin;
}
.settings-jump-nav .ant-btn {
  min-width: max-content;
}
.settings-section { scroll-margin-top: 62px; }
.settings-card { height: calc(100% - 16px); }
.settings-form { max-width: 560px; }
.settings-hint {
  width: 100%;
  margin-top: 2px;
  color: var(--csub);
  font-size: 12px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.settings-template-hint { margin-top: 7px; }
.settings-form-actions :deep(.ant-form-item-control-input-content) {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.settings-form-actions :deep(.ant-btn + .ant-btn) { margin-left: 0; }
.settings-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.settings-card-meta {
  color: var(--csub);
  font-size: 12px;
}
.settings-break-text { overflow-wrap: anywhere; }
.settings-log-item .mobile-data-card__head > span {
  flex: 0 0 auto;
  color: var(--csub);
  font-size: 11px;
}

@media (max-width: 768px) {
  .settings-jump-nav { margin-inline: 0; }
  .settings-grid > .ant-col { max-width: 100%; }
  .settings-card { height: auto; }
  .settings-card :deep(.ant-card-body),
  .settings-log-card :deep(.ant-card-body) { padding: 14px 12px; }
  .settings-form :deep(.ant-form-item) { display: block; }
  .settings-form :deep(.ant-form-item-label) {
    width: auto !important;
    height: auto;
    padding: 0 0 6px;
    line-height: 1.4;
  }
  .settings-form :deep(.ant-form-item-control) { margin-left: 0 !important; }
  .settings-form :deep(.ant-input-number) { width: 100%; }
  .settings-form-actions :deep(.ant-btn) { min-width: calc(50% - 4px); flex: 1; }
  .settings-card-head { flex-wrap: wrap; }
  .settings-log-item .mobile-data-card__head { align-items: flex-start; }
}
</style>
