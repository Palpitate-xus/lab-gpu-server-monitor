<template>
  <div class="cockpit">
    <nav class="settings-jump-nav" aria-label="设置分区快捷导航">
      <button type="button" @click="scrollToSection('settings-collection')">采集与数据</button>
      <button type="button" @click="scrollToSection('settings-webhook')">告警通知</button>
      <button type="button" @click="scrollToSection('settings-thresholds')">检测阈值</button>
      <button type="button" @click="scrollToSection('settings-status-page')">公开状态页</button>
      <button type="button" @click="scrollToSection('settings-logs')">操作日志</button>
    </nav>

    <el-row :gutter="14" class="settings-grid">
      <el-col id="settings-collection" :span="12" :xs="{ span: 24 }" class="settings-section">
        <el-card class="page-card settings-card">
          <template #header>采集与数据</template>
          <el-form class="settings-form" label-width="130px">
            <el-form-item label="采集间隔 (秒)">
              <el-input-number v-model="pollInterval" :min="10" :max="3600" />
            </el-form-item>
            <el-form-item label="数据保留 (天)">
              <el-input-number v-model="retentionDays" :min="0" :max="3650" />
              <div class="settings-hint">0 = 永久保存全部历史数据</div>
            </el-form-item>
            <el-form-item label="电价 (¥/kWh)">
              <el-input-number v-model="energyPrice" :min="0" :max="100" :step="0.05" :precision="2" />
              <div class="settings-hint">电量费用估算，0 = 不计算</div>
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
      <el-col id="settings-webhook" :span="12" :xs="{ span: 24 }" class="settings-section">
        <el-card class="page-card settings-card">
          <template #header>告警通知 (Webhook)</template>
          <el-form class="settings-form webhook-form" label-width="120px">
            <el-form-item label="Webhook URL">
              <el-input v-model="webhookUrl" :placeholder="webhookConfigured ? '已加密保存；留空表示保持不变' : 'https://example.com/hook'" />
              <div v-if="webhookConfigured" class="settings-hint">已配置，出于安全原因不回显 URL/令牌。</div>
            </el-form-item>
            <el-form-item label="消息模板">
              <el-input v-model="webhookTemplate" type="textarea" :rows="4" class="mono"
                placeholder='{"text": "[{{level}}] {{server_name}}: {{metric}}={{value}} {{op}} {{threshold}}"}' />
              <div class="settings-hint settings-template-hint">
                变量: {{level}} {{server_name}} {{metric}} {{value}} {{op}} {{threshold}} {{rule_name}} {{time}}<br>
                默认发 JSON，可直接填企业微信/钉钉/飞书机器人兼容模板
              </div>
            </el-form-item>
            <el-form-item class="settings-form-actions">
              <el-button :loading="testing" @click="testWebhook">发送测试</el-button>
              <el-button type="primary" :loading="savingWebhook" @click="saveWebhook">保存</el-button>
              <el-button v-if="webhookConfigured" type="danger" plain @click="clearWebhook">清除</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>
    <el-row :gutter="14" class="settings-grid">
      <el-col id="settings-channels" :span="12" :xs="{ span: 24 }" class="settings-section">
        <el-card v-if="isAdmin" class="page-card settings-card">
          <template #header>
            <div class="settings-card-head">
              <span>通知通道 ({{ channels.length }})</span>
              <el-button size="small" type="primary" :icon="Plus" @click="openChannelDialog">新增通道</el-button>
            </div>
          </template>
          <el-table class="desktop-only" :data="channels" size="small" v-loading="loadingChannels" max-height="300">
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
          <div class="mobile-only" v-loading="loadingChannels">
            <div v-if="channels.length" class="mobile-card-list">
              <article v-for="row in channels" :key="row.id" class="mobile-data-card">
                <div class="mobile-data-card__head">
                  <div class="mobile-data-card__title">{{ row.name }}</div>
                  <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '已启用' : '已停用' }}</el-tag>
                </div>
                <div class="mobile-data-card__meta">
                  <span>Webhook URL</span><span class="settings-break-text">{{ row.url }}</span>
                  <span>最低严重度</span><span>{{ SEVERITY_LABELS[row.min_severity] || row.min_severity }}</span>
                </div>
                <div class="mobile-data-card__actions">
                  <el-popconfirm title="删除该通道？" @confirm="removeChannel(row)">
                    <template #reference><el-button size="small" type="danger" plain>删除通道</el-button></template>
                  </el-popconfirm>
                </div>
              </article>
            </div>
            <el-empty v-else-if="!loadingChannels" description="暂无通知通道" :image-size="72" />
          </div>
        </el-card>
      </el-col>
      <el-col id="settings-thresholds" :span="12" :xs="{ span: 24 }" class="settings-section">
        <el-card class="page-card settings-card">
          <template #header>检测阈值</template>
          <el-form class="settings-form" label-width="150px" v-loading="loadingThresholds">
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

    <div id="settings-status-page" class="settings-section">
      <StatusPageConfig />
    </div>

    <el-card id="settings-logs" class="page-card settings-section settings-log-card">
      <template #header>
        <div class="settings-card-head">
          <span>操作日志</span>
          <span class="settings-card-meta">最近 {{ logs.length }} 条</span>
        </div>
      </template>
      <el-table class="desktop-only" :data="logs" size="small" v-loading="loadingLogs" max-height="420">
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ fmtTime(row.ts) }}</template>
        </el-table-column>
        <el-table-column prop="username" label="用户" width="100" />
        <el-table-column prop="action" label="操作" width="140" />
        <el-table-column prop="detail" label="详情" min-width="240" show-overflow-tooltip />
      </el-table>
      <div class="mobile-only" v-loading="loadingLogs">
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
        <el-empty v-else-if="!loadingLogs" description="暂无操作日志" :image-size="72" />
      </div>
    </el-card>

    <el-dialog v-model="channelDlg" class="responsive-dialog" title="新增通知通道" width="480px">
      <el-form ref="channelFormRef" class="responsive-form" :model="channelForm" :rules="channelRules" label-width="100px">
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
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import api from '../api'
import StatusPageConfig from '../components/StatusPageConfig.vue'
import { isAdminSession } from '../composables'
import { fmtTime } from '../format'

const isAdmin = computed(() => isAdminSession())

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
const SEVERITY_TYPES = { info: 'info', warning: 'warning', critical: 'danger' }

const thresholds = reactive({
  gpu_idle_vram_pct: 30, gpu_idle_minutes: 30,
  health_cpu_pct: 90, health_mem_pct: 92, health_disk_pct: 90
})
const loadingThresholds = ref(false)
const savingThresholds = ref(false)

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
    await api.put('/settings', { poll_interval: pollInterval.value, retention_days: retentionDays.value, energy_price: energyPrice.value })
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
    const payload = { webhook_template: webhookTemplate.value }
    if (webhookUrl.value.trim()) payload.webhook_url = webhookUrl.value.trim()
    await api.put('/settings', payload)
    if (payload.webhook_url) {
      webhookConfigured.value = true
      webhookUrl.value = ''
    }
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '保存失败')
  } finally {
    savingWebhook.value = false
  }
}

async function testWebhook() {
  if (!webhookUrl.value.trim() && !webhookConfigured.value) return ElMessage.warning('请先填写 Webhook URL')
  testing.value = true
  try {
    await api.post('/alerts/test-webhook', { url: webhookUrl.value.trim(), template: webhookTemplate.value })
    ElMessage.success('测试消息已发送，请查收')
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '发送失败')
  } finally {
    testing.value = false
  }
}

async function clearWebhook() {
  try {
    await ElMessageBox.confirm('确认清除已保存的 Webhook URL？', '清除 Webhook', { type: 'warning' })
    await api.put('/settings', { webhook_url: '' })
    webhookUrl.value = ''
    webhookConfigured.value = false
    ElMessage.success('Webhook 已清除')
  } catch (e) {
    if (e !== 'cancel' && e !== 'close' && e?.friendlyMessage) ElMessage.error(e.friendlyMessage)
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
  border-radius: 10px;
  background: color-mix(in srgb, var(--cpanel) 94%, transparent);
  box-shadow: 0 8px 24px -22px rgba(15, 23, 42, .8);
  backdrop-filter: blur(10px);
  scrollbar-width: thin;
}
.settings-jump-nav button {
  min-width: max-content;
  padding: 7px 11px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--csub);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.settings-jump-nav button:hover,
.settings-jump-nav button:focus-visible {
  outline: none;
  background: color-mix(in srgb, var(--cprimary) 10%, transparent);
  color: var(--cprimary);
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
.settings-form-actions :deep(.el-form-item__content) {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.settings-form-actions :deep(.el-button + .el-button) { margin-left: 0; }
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
  .settings-grid > .el-col { max-width: 100%; }
  .settings-card { height: auto; }
  .settings-card :deep(.el-card__body),
  .settings-log-card :deep(.el-card__body) { padding: 14px 12px; }
  .settings-form :deep(.el-form-item) { display: block; }
  .settings-form :deep(.el-form-item__label) {
    width: auto !important;
    height: auto;
    padding: 0 0 6px;
    line-height: 1.4;
  }
  .settings-form :deep(.el-form-item__content) { margin-left: 0 !important; }
  .settings-form :deep(.el-input-number) { width: 100%; }
  .settings-form-actions :deep(.el-button) { min-width: calc(50% - 4px); flex: 1; }
  .settings-card-head { flex-wrap: wrap; }
  .settings-log-item .mobile-data-card__head { align-items: flex-start; }
}
</style>
