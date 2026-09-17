<template>
  <main class="login-page">
    <a-card class="login-card">
      <div class="login-theme-toggle">
        <ThemeSwitch />
      </div>
      <div class="login-heading">
        <a-badge status="success" />
        <h1>GPU 集群监控</h1>
      </div>
      <p class="login-hint">登录后查看服务器和 GPU 的实时状态、历史趋势与告警。</p>

      <a-form :model="form" :rules="rules" layout="vertical" @finish="submit">
        <a-form-item label="用户名" name="username">
          <a-input v-model:value="form.username" size="large" placeholder="请输入用户名" autofocus>
            <template #prefix><UserOutlined /></template>
          </a-input>
        </a-form-item>
        <a-form-item label="密码" name="password">
          <a-input-password v-model:value="form.password" size="large" placeholder="请输入密码">
            <template #prefix><LockOutlined /></template>
          </a-input-password>
        </a-form-item>
        <a-form-item label="MFA 动态码（可选）" name="otp">
          <a-input
            v-model:value="form.otp"
            size="large"
            inputmode="numeric"
            maxlength="6"
            placeholder="绑定过 MFA 时填写 6 位动态码"
          >
            <template #prefix><SafetyCertificateOutlined /></template>
          </a-input>
        </a-form-item>
        <a-button
          type="primary"
          html-type="submit"
          size="large"
          block
          :loading="loading"
          :disabled="lockSeconds > 0"
        >
          {{ lockSeconds > 0 ? `已锁定 ${Math.floor(lockSeconds / 60)}:${String(lockSeconds % 60).padStart(2, '0')}` : '登录' }}
        </a-button>
      </a-form>
    </a-card>
  </main>
</template>

<script setup>
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { App as AntApp } from 'ant-design-vue'
import { LockOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons-vue'
import api from '../api'
import { setSession } from '../composables'
import { safeLocalRedirect } from '../navigation'
import ThemeSwitch from '../components/ThemeSwitch.vue'

const router = useRouter()
const route = useRoute()
const { message } = AntApp.useApp()
const loading = ref(false)
const form = reactive({ username: '', password: '', otp: '' })
const lockSeconds = ref(0)
let lockTimer = null

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

function startLockCountdown() {
  clearInterval(lockTimer)
  lockTimer = setInterval(() => {
    lockSeconds.value--
    if (lockSeconds.value <= 0) {
      clearInterval(lockTimer)
      lockTimer = null
    }
  }, 1000)
}

async function submit() {
  if (loading.value || lockSeconds.value > 0) return
  loading.value = true
  try {
    const { data } = await api.post('/auth/login', new URLSearchParams(form))
    setSession(data.user)
    message.success(`欢迎，${data.user.display_name || data.user.username}`)
    if (data.user.mfa_required && !data.user.mfa_enrolled) {
      await router.push({ name: 'mfa-setup' })
      return
    }
    const target = safeLocalRedirect(route.query.redirect, location.origin)
    router.push(target).catch(() => { location.href = target })
  } catch (e) {
    const msg = e.friendlyMessage || '登录失败'
    message.error(msg)
    const match = msg.match(/(\d+)\s*分\s*(\d+)\s*秒/)
    if (e.response?.status === 429 || match) {
      lockSeconds.value = match ? (+match[1] * 60 + +match[2]) : 600
      startLockCountdown()
    }
  } finally {
    loading.value = false
  }
}

onUnmounted(() => clearInterval(lockTimer))
onMounted(() => {
  if (route.query.reason === 'expired') message.warning('登录已过期，请重新登录')
})
</script>

<style scoped>
.login-page {
  min-height: 100%;
  display: grid;
  place-items: center;
  padding: 24px;
  background: var(--cbg);
}
.login-card {
  width: min(420px, 100%);
  position: relative;
}
.login-theme-toggle {
  position: absolute;
  top: 12px;
  right: 12px;
}
.login-heading {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-right: 40px;
}
.login-heading h1 {
  margin: 0;
  font-size: 24px;
  line-height: 1.4;
}
.login-hint {
  margin: 8px 0 24px;
  color: var(--csub);
  line-height: 1.7;
}

@media (max-width: 480px) {
  .login-page { padding: 16px; }
  .login-heading h1 { font-size: 21px; }
}
</style>
