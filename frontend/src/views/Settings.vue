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
              <el-button type="primary" :loading="saving" @click="saveSettings">保存</el-button>
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
              <el-button type="primary" :loading="saving" @click="saveWebhook">保存</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>
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
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'
import { fmtTime } from '../format'

const pollInterval = ref(60)
const retentionDays = ref(0)
const webhookUrl = ref('')
const webhookTemplate = ref('')
const saving = ref(false)
const testing = ref(false)
const status = ref({})
const logs = ref([])
const loadingLogs = ref(false)

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
  saving.value = true
  try {
    await api.put('/settings', { poll_interval: pollInterval.value, retention_days: retentionDays.value })
    ElMessage.success('已保存，下一轮采集生效')
    load()
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '保存失败')
  } finally {
    saving.value = false
  }
}

async function saveWebhook() {
  saving.value = true
  try {
    await api.put('/settings', { webhook_url: webhookUrl.value, webhook_template: webhookTemplate.value })
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '保存失败')
  } finally {
    saving.value = false
  }
}

async function testWebhook() {
  if (!webhookUrl.value) return ElMessage.warning('请先填写 Webhook URL')
  testing.value = true
  try {
    await api.post('/alerts/test-webhook', {})
    ElMessage.success('测试消息已发送，请查收')
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '发送失败')
  } finally {
    testing.value = false
  }
}

onMounted(() => { load(); loadLogs() })
</script>
