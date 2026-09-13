<template>
  <div class="cockpit login-full">
    <div class="login-grid-glow"></div>
    <div class="login-shell">
      <div class="login-card">
        <div class="login-theme-toggle">
          <ThemeSwitch />
        </div>
        <h1 class="login-title">GPU 集群监控</h1>
        <p class="login-hint">登录后查看服务器和 GPU 的实时状态、历史趋势与告警。</p>
        <el-form ref="formRef" :model="form" :rules="rules" size="large" @keyup.enter="submit">
          <el-form-item prop="username">
            <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" autofocus class="dark-input" />
          </el-form-item>
          <el-form-item prop="password">
            <el-input v-model="form.password" type="password" placeholder="密码" show-password :prefix-icon="Lock" class="dark-input" />
          </el-form-item>
          <el-form-item prop="otp">
            <el-input v-model="form.otp" inputmode="numeric" maxlength="6" placeholder="动态码（绑定过 MFA 才需要填）" class="dark-input" />
          </el-form-item>
          <el-form-item class="login-submit-item">
            <el-button type="primary" class="login-submit" :loading="loading" :disabled="lockSeconds > 0" @click="submit">
            {{ lockSeconds > 0 ? `已锁定 ${Math.floor(lockSeconds / 60)}:${String(lockSeconds % 60).padStart(2, '0')}` : '登 录' }}
            </el-button>
          </el-form-item>
        </el-form>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import api from '../api'
import { setSession } from '../composables'
import { safeLocalRedirect } from '../navigation'
import ThemeSwitch from '../components/ThemeSwitch.vue'
import '../cockpit.css'

const router = useRouter()
const route = useRoute()
const formRef = ref()
const loading = ref(false)
const form = reactive({ username: '', password: '', otp: '' })
const lockSeconds = ref(0)
let lockTimer = null
function startLockCountdown() {
  clearInterval(lockTimer)
  lockTimer = setInterval(() => {
    lockSeconds.value--
    if (lockSeconds.value <= 0) { clearInterval(lockTimer); lockTimer = null }
  }, 1000)
}
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

async function submit() {
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  loading.value = true
  try {
    const { data } = await api.post('/auth/login', new URLSearchParams(form))
    setSession(data.user)
    ElMessage.success(`欢迎，${data.user.display_name || data.user.username}`)
    if (data.user.mfa_required && !data.user.mfa_enrolled) {
      await router.push({ name: 'mfa-setup' })
      return
    }
    // hard navigation guarantees the guard re-runs with the fresh session
    const target = safeLocalRedirect(route.query.redirect, location.origin)
    if (router) router.push(target).catch(() => { location.href = target })
    else location.href = target
  } catch (e) {
    const msg = e.friendlyMessage || '登录失败'
    ElMessage.error(msg)
    // 429 lockout: show a countdown so users stop hammering the button
    const m = msg.match(/(\d+)\s*分\s*(\d+)\s*秒/)
    if (e.response?.status === 429 || m) {
      lockSeconds.value = m ? (+m[1] * 60 + +m[2]) : 600
      startLockCountdown()
    }
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-full {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  padding: 28px;
}
.login-grid-glow {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(color-mix(in srgb, var(--cprimary) 6%, transparent) 1px, transparent 1px),
    linear-gradient(90deg, color-mix(in srgb, var(--cprimary) 6%, transparent) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: radial-gradient(ellipse 70% 60% at 50% 40%, #000 30%, transparent 75%);
  -webkit-mask-image: radial-gradient(ellipse 70% 60% at 50% 40%, #000 30%, transparent 75%);
}
.login-shell {
  width: min(430px, 100%);
  position: relative;
  z-index: 1;
  overflow: hidden;
  border: 1px solid var(--cborder);
  border-radius: 18px;
  background: var(--cpanel);
  box-shadow: 0 28px 80px rgba(15, 23, 42, .18), 0 0 0 1px color-mix(in srgb, var(--cprimary) 6%, transparent);
}
.login-card {
  width: 100%;
  padding: 55px 44px 34px;
  background: var(--cpanel);
  position: relative;
}
.login-theme-toggle {
  position: absolute;
  top: 10px;
  right: 10px;
}
.login-title {
  margin: 0;
  color: var(--ctext);
  font-size: 22px;
  font-weight: 700;
}
.login-hint {
  margin: 8px 0 26px;
  color: var(--csub);
  font-size: 13px;
  line-height: 1.7;
}
.login-submit-item { margin-top: 4px; margin-bottom: 0; }
.login-submit {
  width: 100%;
  height: 42px;
  font-size: 15px;
  letter-spacing: .2em;
}
.dark-input :deep(.el-input__wrapper) {
  background: var(--cinput-bg);
  border: 1px solid var(--cinput-border);
  box-shadow: none;
}
.dark-input :deep(.el-input__inner) {
  color: var(--ctext);
}
.dark-input :deep(.el-input__prefix .el-icon) {
  color: var(--csub);
}
@media (max-width: 820px) {
  .login-shell { width: min(430px, 100%); min-height: 0; grid-template-columns: 1fr; border-radius: 14px; }
    .login-card { padding: 50px 38px 30px; }
}
@media (max-width: 480px) {
  .login-full { padding: 16px; }
  .login-shell { width: 100%; }
  .login-card { padding: 46px 24px 26px; }
  .login-title { font-size: 20px; }
  }
</style>
