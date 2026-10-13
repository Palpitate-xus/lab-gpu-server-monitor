<template>
  <a-card class="page-card status-config-card" :loading="loading">
    <template #title>
      <div class="status-config-head">
        <div>
          <span>公开状态页</span>
          <small>面向访客的精简服务状态视图</small>
        </div>
        <div class="status-config-head__actions">
          <a-tag v-if="savedPublished" color="green">已发布</a-tag>
          <a-tag v-else>未发布</a-tag>
          <a-tag v-if="hasDraft" color="orange">有未保存修改</a-tag>
          <a-button type="link" size="small" href="/status" target="_blank" rel="noopener noreferrer">访问 /status ↗</a-button>
        </div>
      </div>
    </template>

    <a-alert v-if="loadError" type="error" show-icon :message="loadError" class="config-error">
      <template #action><a-button size="small" @click="load">重试</a-button></template>
    </a-alert>
    <a-form ref="formRef" :model="cfg" :rules="rules" class="status-config-form" :label-col="{ style: { width: '116px' } }">
      <a-form-item label="发布状态">
        <a-switch v-model:checked="cfg.published" checked-children="对外可见" un-checked-children="仅管理员" />
        <div class="sp-hint">关闭时访问者会看到「未发布」提示，不暴露任何服务器数据</div>
      </a-form-item>

      <a-form-item label="页面标题" name="title">
        <a-input v-model:value="cfg.title" maxlength="120" placeholder="如：实验室 GPU 集群状态" />
      </a-form-item>

      <a-form-item label="描述">
        <a-textarea v-model:value="cfg.description" maxlength="500" :rows="2"
          placeholder="显示在标题下方的一句话说明" />
      </a-form-item>

      <a-form-item label="展示服务器">
        <a-select v-model:value="cfg.server_ids" mode="multiple" placeholder="不选 = 全部启用的服务器" style="width:100%">
          <a-select-option v-for="s in available" :key="s.id" :value="s.id" :disabled="!s.enabled">
            {{ s.name + (s.server_type === 'cpu' ? ' (CPU)' : ' (GPU)') }}
          </a-select-option>
        </a-select>
        <div class="sp-hint">只勾选适合对外展示的机器；未启用的服务器不可选</div>
      </a-form-item>

      <a-form-item label="历史天数" name="show_history_days">
        <div class="history-days-control">
          <a-slider v-model:value="cfg.show_history_days" :min="1" :max="365" :step="1" />
          <a-input-number v-model:value="cfg.show_history_days" :min="1" :max="365" :step="1" :precision="0" />
        </div>
        <div class="sp-hint">每台服务器下方可用率条形图的时间窗口（1–365 天）</div>
      </a-form-item>

      <a-form-item label="显示延迟">
        <a-switch v-model:checked="cfg.show_latency" />
        <span class="sp-hint sp-inline-hint">SSH 探测延迟（毫秒）</span>
      </a-form-item>

      <a-form-item label="显示 GPU">
        <a-switch v-model:checked="cfg.show_gpu" />
        <span class="sp-hint sp-inline-hint">每张 GPU 的实时利用率与显存占用（GPU 服务器）</span>
      </a-form-item>

      <a-form-item label="页面主题">
        <a-radio-group v-model:value="cfg.theme">
          <a-radio value="auto">跟随访客</a-radio>
          <a-radio value="light">强制浅色</a-radio>
          <a-radio value="dark">强制深色</a-radio>
        </a-radio-group>
      </a-form-item>

      <a-form-item label="页脚文字">
        <a-input v-model:value="cfg.footer" maxlength="300" placeholder="如：Powered by lab-gpu-server-monitor" />
      </a-form-item>

      <a-form-item class="status-config-actions">
        <a-button type="primary" :loading="saving" :disabled="!ready || previewing" @click="save">保存配置</a-button>
        <a-button :loading="previewing" :disabled="!ready || saving" @click="openPreview">预览草稿</a-button>
      </a-form-item>
      <div class="sp-hint">预览不会保存或发布配置；只有点击「保存配置」才会改变线上状态页。</div>
    </a-form>
  </a-card>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { App as AntApp } from 'ant-design-vue'
import api from '../api'
import { openStatusPreview } from '../status-preview'

const { message } = AntApp.useApp()

const cfg = ref({
  title: '服务状态', description: '', server_ids: [], show_history_days: 45,
  show_latency: true, show_gpu: true, theme: 'auto', footer: '', published: false,
})
const available = ref([])
const saving = ref(false)
const previewing = ref(false)
const formRef = ref()
const loading = ref(false)
const ready = ref(false)
const loadError = ref('')
const savedConfig = ref('')
const savedPublished = ref(false)
const hasDraft = computed(() => ready.value && JSON.stringify(cfg.value) !== savedConfig.value)
const rules = {
  title: [{ max: 120, message: '标题最多 120 个字符', trigger: 'blur' }],
  show_history_days: [{ validator: (_, value) => Number.isInteger(value) && value >= 1 && value <= 365
    ? Promise.resolve() : Promise.reject(new Error('历史天数须为 1–365 的整数')), trigger: 'change' }],
}

function markSaved() {
  savedConfig.value = JSON.stringify(cfg.value)
  savedPublished.value = cfg.value.published
}

async function load() {
  if (loading.value) return
  loading.value = true
  loadError.value = ''
  try {
    const { data } = await api.get('/status-page/config')
    cfg.value = { ...cfg.value, ...data.config }
    available.value = data.available_servers || []
    markSaved()
    ready.value = true
  } catch (e) {
    ready.value = false
    loadError.value = e.friendlyMessage || '配置加载失败，请重试后再编辑'
  } finally {
    loading.value = false
  }
}

async function save() {
  if (saving.value || previewing.value || !ready.value) return false
  saving.value = true
  try {
    await formRef.value.validate()
    const submitted = JSON.parse(JSON.stringify(cfg.value))
    await api.put('/status-page/config', submitted)
    savedConfig.value = JSON.stringify(submitted)
    savedPublished.value = submitted.published
    message.success('已保存')
    return true
  } catch (e) {
    if (!e.errorFields) message.error(e.friendlyMessage || '保存失败')
    return false
  } finally {
    saving.value = false
  }
}

function openPreview() {
  if (previewing.value || saving.value || !ready.value) return
  if (!Number.isInteger(cfg.value.show_history_days) || cfg.value.show_history_days < 1 || cfg.value.show_history_days > 365) {
    message.warning('历史天数须为 1–365 的整数')
    return
  }
  previewing.value = true
  try {
    openStatusPreview(cfg.value)
  } catch (e) {
    message.error(e.message || '打开预览失败')
  } finally {
    previewing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.sp-hint { font-size: 12px; color: var(--csub); line-height: 1.6; margin-top: 2px; }
.config-error { margin-bottom: 16px; }
.sp-inline-hint { margin-left: 10px; }
.status-config-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.status-config-head > div:first-child {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  white-space: normal;
}
.status-config-head small {
  color: var(--csub);
  font-size: 11px;
  font-weight: 400;
}
.status-config-head__actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.status-config-form { max-width: 760px; }
.history-days-control {
  width: 100%;
  max-width: 460px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 80px;
  gap: 12px;
}
.status-config-actions :deep(.ant-form-item-control-input-content) {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.status-config-actions :deep(.ant-form-item-control) { margin-inline-start: 116px; }
.status-config-actions :deep(.ant-btn + .ant-btn) { margin-left: 0; }

@media (max-width: 768px) {
  .status-config-card :deep(.ant-card-body) { padding: 14px 12px; }
  .status-config-head { align-items: flex-start; flex-direction: column; gap: 10px; }
  .status-config-head__actions { width: 100%; justify-content: space-between; }
  .status-config-form :deep(.ant-form-item) { display: block; }
  .status-config-form :deep(.ant-form-item-row) { display: block; }
  .status-config-form :deep(.ant-form-item-label) {
    width: auto !important;
    height: auto;
    padding: 0 0 6px;
    line-height: 1.4;
    text-align: left;
  }
  .status-config-form :deep(.ant-form-item-control) { margin-left: 0 !important; }
  .status-config-actions :deep(.ant-form-item-control) { margin-inline-start: 0 !important; }
  .status-config-form :deep(.ant-radio-group) { display: flex; flex-wrap: wrap; row-gap: 5px; }
  .history-days-control { max-width: 100%; }
  .sp-inline-hint { width: 100%; margin: 5px 0 0; }
  .status-config-actions :deep(.ant-btn) { min-width: calc(50% - 4px); flex: 1; }
}
</style>
