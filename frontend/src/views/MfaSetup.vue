<template>
  <div class="page-wrap" style="max-width:760px;margin:0 auto">
    <el-card class="page-card">
      <template #header><b>管理员多因素认证（必须完成）</b></template>
      <el-alert
        type="warning"
        :closable="false"
        title="绑定完成前，所有管理员写操作都会被拒绝。请把密钥加入支持 TOTP 的认证器。"
        style="margin-bottom:18px"
      />
      <el-skeleton v-if="loading" :rows="4" animated />
      <template v-else>
        <el-form label-width="110px">
          <el-form-item label="账户密钥">
            <el-input :model-value="secret" readonly class="mono">
              <template #append><el-button @click="copy(secret)">复制</el-button></template>
            </el-input>
          </el-form-item>
          <el-form-item label="配置 URI">
            <el-input :model-value="uri" readonly class="mono">
              <template #append><el-button @click="copy(uri)">复制</el-button></template>
            </el-input>
          </el-form-item>
          <el-form-item label="6 位动态码">
            <el-input v-model="code" maxlength="6" inputmode="numeric" placeholder="认证器当前显示的验证码" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="saving" :disabled="!/^[0-9]{6}$/.test(code)" @click="confirm">
              验证并启用 MFA
            </el-button>
          </el-form-item>
        </el-form>
      </template>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import api from '../api'
import { setSession } from '../composables'

const router = useRouter()
const loading = ref(true)
const saving = ref(false)
const secret = ref('')
const uri = ref('')
const code = ref('')

async function setup() {
  loading.value = true
  try {
    const { data } = await api.post('/auth/mfa/setup')
    secret.value = data.secret
    uri.value = data.uri
  } catch (e) {
    ElMessage.error(e.friendlyMessage || 'MFA 初始化失败')
  } finally {
    loading.value = false
  }
}

async function copy(value) {
  await navigator.clipboard.writeText(value)
  ElMessage.success('已复制')
}

async function confirm() {
  saving.value = true
  try {
    const { data } = await api.post('/auth/mfa/confirm', { code: code.value })
    setSession(data.user)
    ElMessage.success('管理员 MFA 已启用')
    router.push('/cockpit')
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '动态码验证失败')
  } finally {
    saving.value = false
  }
}

onMounted(setup)
</script>
