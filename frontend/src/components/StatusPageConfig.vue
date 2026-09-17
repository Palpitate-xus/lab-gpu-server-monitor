<template>
  <a-card class="page-card status-config-card">
    <template #title>
      <div class="status-config-head">
        <div>
          <span>公开状态页</span>
          <small>面向访客的精简服务状态视图</small>
        </div>
        <div class="status-config-head__actions">
          <a-tag v-if="cfg.published" color="green">已发布</a-tag>
          <a-tag v-else>未发布</a-tag>
          <a-button type="link" size="small" href="/status" target="_blank">访问 /status ↗</a-button>
        </div>
      </div>
    </template>

    <a-form class="status-config-form" :label-col="{ style: { width: '116px' } }">
      <a-form-item label="发布状态">
        <a-switch v-model:checked="cfg.published" checked-children="对外可见" un-checked-children="仅管理员" />
        <div class="sp-hint">关闭时访问者会看到「未发布」提示，不暴露任何服务器数据</div>
      </a-form-item>

      <a-form-item label="页面标题">
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

      <a-form-item label="历史天数">
        <div class="history-days-control">
          <a-slider v-model:value="cfg.show_history_days" :min="7" :max="90" :step="1" />
          <a-input-number v-model:value="cfg.show_history_days" :min="7" :max="90" :step="1" />
        </div>
        <div class="sp-hint">每台服务器下方可用率条形图的时间窗口（7-90 天）</div>
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
        <a-button type="primary" :loading="saving" @click="save">保存配置</a-button>
        <a-button :loading="previewing" @click="openPreview">预览状态页</a-button>
      </a-form-item>
    </a-form>
  </a-card>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { App as AntApp } from 'ant-design-vue'
import api from '../api'

const { message } = AntApp.useApp()

const cfg = ref({
  title: '服务状态', description: '', server_ids: [], show_history_days: 45,
  show_latency: true, show_gpu: true, theme: 'auto', footer: '', published: false,
})
const available = ref([])
const saving = ref(false)
const previewing = ref(false)

async function load() {
  try {
    const { data } = await api.get('/status-page/config')
    cfg.value = { ...cfg.value, ...data.config }
    available.value = data.available_servers || []
  } catch (e) {
    message.error(e.friendlyMessage || '加载失败')
  }
}

async function save() {
  saving.value = true
  try {
    await api.put('/status-page/config', cfg.value)
    message.success('已保存')
  } catch (e) {
    message.error(e.friendlyMessage || '保存失败')
  } finally {
    saving.value = false
  }
}

async function openPreview() {
  previewing.value = true
  try {
    await save()
  } finally {
    previewing.value = false
  }
  // preview mode renders regardless of the publish toggle (admin-only endpoint)
  window.open('/status?preview=1', '_blank')
}

onMounted(load)
</script>

<style scoped>
.sp-hint { font-size: 12px; color: var(--csub); line-height: 1.6; margin-top: 2px; }
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
.status-config-actions :deep(.ant-btn + .ant-btn) { margin-left: 0; }

@media (max-width: 768px) {
  .status-config-card :deep(.ant-card-body) { padding: 14px 12px; }
  .status-config-head { align-items: flex-start; flex-direction: column; gap: 10px; }
  .status-config-head__actions { width: 100%; justify-content: space-between; }
  .status-config-form :deep(.ant-form-item) { display: block; }
  .status-config-form :deep(.ant-form-item-label) {
    width: auto !important;
    height: auto;
    padding: 0 0 6px;
    line-height: 1.4;
  }
  .status-config-form :deep(.ant-form-item-control) { margin-left: 0 !important; }
  .status-config-form :deep(.ant-radio-group) { display: flex; flex-wrap: wrap; row-gap: 5px; }
  .history-days-control { max-width: 100%; }
  .sp-inline-hint { width: 100%; margin: 5px 0 0; }
  .status-config-actions :deep(.ant-btn) { min-width: calc(50% - 4px); flex: 1; }
}
</style>
