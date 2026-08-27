<template>
  <div class="cockpit login-full">
    <div class="login-grid-glow"></div>
    <div class="login-card">
      <div class="login-theme-toggle">
        <ThemeSwitch />
      </div>
      <div style="display:flex;align-items:center;gap:10px;justify-content:center;margin-bottom:6px">
        <span class="live-dot"></span>
        <div class="login-title">GPU 集群监控平台</div>
      </div>
      <el-form ref="formRef" :model="form" :rules="rules" size="large" @keyup.enter="submit">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" autofocus class="dark-input" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" placeholder="密码" show-password :prefix-icon="Lock" class="dark-input" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" style="width: 100%; height: 42px; font-size: 15px; letter-spacing: 0.2em" :loading="loading" :disabled="lockSeconds > 0" @click="submit">
          {{ lockSeconds > 0 ? `已锁定 ${Math.floor(lockSeconds / 60)}:${String(lockSeconds % 60).padStart(2, '0')}` : '登 录' }}
        </el-button>
        </el-form-item>
      </el-form>
      <div v-if="isDev" style="text-align:center;color:var(--csub);font-size:12px;margin-top:4px">默认账号 admin / admin123（首次登录后请修改）</div>
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
import ThemeSwitch from '../components/ThemeSwitch.vue'
import '../cockpit.css'

const router = useRouter()
const route = useRoute()
const formRef = ref()
const loading = ref(false)
const isDev = import.meta.env.DEV
const form = reactive({ username: '', password: '' })
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

function safeRedirect(r) {
  return typeof r === 'string' && r.startsWith('/') && !r.startsWith('//') ? r : '/cockpit'
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
    setSession(data.access_token, data.user)
    ElMessage.success(`欢迎，${data.user.display_name || data.user.username}`)
    // hard navigation guarantees the guard re-runs with the fresh session
    const target = safeRedirect(route.query.redirect)
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
@media (max-width: 480px) {
  .login-card { width: calc(100vw - 32px); padding: 28px 20px 22px; }
}
.login-full {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
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
.login-card {
  width: 400px;
  padding: 38px 36px 28px;
  background: var(--cpanel);
  border: 1px solid var(--cborder);
  border-radius: 12px;
  box-shadow: 0 18px 60px rgba(0, 0, 0, 0.25), 0 0 0 1px color-mix(in srgb, var(--cprimary) 6%, transparent);
  position: relative;
  z-index: 1;
}
.login-card::before {
  content: "";
  position: absolute;
  inset: 0 0 auto 0;
  height: 2px;
  border-radius: 12px 12px 0 0;
  background: linear-gradient(90deg, transparent, var(--cprimary), transparent);
}
.login-theme-toggle {
  position: absolute;
  top: 10px;
  right: 10px;
}
.login-title {
  margin-bottom: 20px;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.06em;
  background: linear-gradient(180deg, var(--ctext), var(--cprimary));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
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
</style>
