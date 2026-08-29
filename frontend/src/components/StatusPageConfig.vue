<template>
  <el-card class="page-card">
    <template #header>
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span>公开状态页（Uptime Kuma 风格）</span>
        <div style="display:flex;gap:10px;align-items:center">
          <el-tag v-if="cfg.published" type="success" size="small">已发布</el-tag>
          <el-tag v-else type="info" size="small">未发布</el-tag>
          <el-link type="primary" href="/status" target="_blank">访问 /status ↗</el-link>
        </div>
      </div>
    </template>

    <el-form label-width="110px" style="max-width:720px">
      <el-form-item label="发布状态">
        <el-switch v-model="cfg.published" active-text="对外可见" inactive-text="仅管理员" />
        <div class="sp-hint">关闭时访问者会看到「未发布」提示，不暴露任何服务器数据</div>
      </el-form-item>

      <el-form-item label="页面标题">
        <el-input v-model="cfg.title" maxlength="120" placeholder="如：实验室 GPU 集群状态" />
      </el-form-item>

      <el-form-item label="描述">
        <el-input v-model="cfg.description" maxlength="500" type="textarea" :rows="2"
          placeholder="显示在标题下方的一句话说明" />
      </el-form-item>

      <el-form-item label="展示服务器">
        <el-select v-model="cfg.server_ids" multiple placeholder="不选 = 全部启用的服务器" style="width:100%">
          <el-option v-for="s in available" :key="s.id" :value="s.id"
            :label="s.name + (s.server_type === 'cpu' ? ' (CPU)' : ' (GPU)')" :disabled="!s.enabled" />
        </el-select>
        <div class="sp-hint">只勾选适合对外展示的机器；未启用的服务器不可选</div>
      </el-form-item>

      <el-form-item label="历史天数">
        <el-slider v-model="cfg.show_history_days" :min="7" :max="90" :step="1"
          show-input :show-input-controls="false" style="width:100%;max-width:420px" />
        <div class="sp-hint">每台服务器下方可用率条形图的时间窗口（7-90 天）</div>
      </el-form-item>

      <el-form-item label="显示延迟">
        <el-switch v-model="cfg.show_latency" />
        <span class="sp-hint" style="margin-left:10px">SSH 探测延迟（毫秒）</span>
      </el-form-item>

      <el-form-item label="显示 GPU">
        <el-switch v-model="cfg.show_gpu" />
        <span class="sp-hint" style="margin-left:10px">每张 GPU 的实时利用率与显存占用（GPU 服务器）</span>
      </el-form-item>

      <el-form-item label="页面主题">
        <el-radio-group v-model="cfg.theme">
          <el-radio value="auto">跟随访客</el-radio>
          <el-radio value="light">强制浅色</el-radio>
          <el-radio value="dark">强制深色</el-radio>
        </el-radio-group>
      </el-form-item>

      <el-form-item label="页脚文字">
        <el-input v-model="cfg.footer" maxlength="300" placeholder="如：Powered by lab-gpu-server-monitor" />
      </el-form-item>

      <el-form-item>
        <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
        <el-button :loading="previewing" @click="openPreview">预览状态页</el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

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
    ElMessage.error(e.friendlyMessage || '加载失败')
  }
}

async function save() {
  saving.value = true
  try {
    await api.put('/status-page/config', cfg.value)
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '保存失败')
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
</style>
