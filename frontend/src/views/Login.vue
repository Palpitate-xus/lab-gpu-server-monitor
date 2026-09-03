<template>
  <div class="cockpit login-full">
    <div class="login-grid-glow"></div>
    <div class="login-shell">
      <section class="login-brand" aria-label="平台简介">
        <div class="login-eyebrow"><span class="live-dot"></span> GPU OBSERVABILITY</div>
        <h1>把集群状态，放在一个可信视图里。</h1>
        <p>服务器健康、GPU 利用率、告警与容量趋势集中呈现，让值班和排障少一次来回切换。</p>
        <div class="login-features">
          <div><b>实时</b><span>集群资源与健康状态</span></div>
          <div><b>清晰</b><span>从概览下钻到单卡</span></div>
          <div><b>安全</b><span>角色权限与管理员 MFA</span></div>
        </div>
        <div class="login-brand-foot">GPU Monitor · Internal Operations Console</div>
      </section>

      <div class="login-card">
        <div class="login-theme-toggle">
          <ThemeSwitch />
        </div>
        <div class="login-card-kicker">WELCOME BACK</div>
        <div class="login-heading">
          <span class="live-dot"></span>
          <div>
            <div class="login-title">GPU 集群监控平台</div>
            <div class="login-subtitle">登录后进入集群工作台</div>
          </div>
        </div>
        <el-form ref="formRef" :model="form" :rules="rules" size="large" @keyup.enter="submit">
          <el-form-item prop="username">
            <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" autofocus class="dark-input" />
          </el-form-item>
          <el-form-item prop="password">
            <el-input v-model="form.password" type="password" placeholder="密码" show-password :prefix-icon="Lock" class="dark-input" />
          </el-form-item>
          <div class="login-optional-label"><span>管理员验证</span><em>Viewer 可留空</em></div>
          <el-form-item prop="otp">
            <el-input v-model="form.otp" inputmode="numeric" maxlength="6" placeholder="6 位 MFA 动态码" class="dark-input" />
          </el-form-item>
          <el-form-item class="login-submit-item">
            <el-button type="primary" class="login-submit" :loading="loading" :disabled="lockSeconds > 0" @click="submit">
            {{ lockSeconds > 0 ? `已锁定 ${Math.floor(lockSeconds / 60)}:${String(lockSeconds % 60).padStart(2, '0')}` : '登 录' }}
            </el-button>
          </el-form-item>
        </el-form>
        <div class="login-footnote">管理员账户启用 MFA 后需填写动态码</div>
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
    if (data.user.role === 'admin' && !data.user.mfa_enrolled) {
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
  width: min(940px, 100%);
  min-height: 500px;
  display: grid;
  grid-template-columns: 1.08fr .92fr;
  position: relative;
  z-index: 1;
  overflow: hidden;
  border: 1px solid var(--cborder);
  border-radius: 18px;
  background: var(--cpanel);
  box-shadow: 0 28px 80px rgba(15, 23, 42, .18), 0 0 0 1px color-mix(in srgb, var(--cprimary) 6%, transparent);
}
.login-brand {
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 54px;
  position: relative;
  overflow: hidden;
  color: var(--ctext);
  background:
    radial-gradient(circle at 18% 16%, color-mix(in srgb, var(--cprimary) 20%, transparent), transparent 32%),
    linear-gradient(145deg, var(--cpanel2), color-mix(in srgb, var(--cpurple) 8%, var(--cpanel)));
  border-right: 1px solid var(--cborder);
}
.login-brand::after {
  content: "";
  width: 260px;
  height: 260px;
  position: absolute;
  right: -120px;
  bottom: -130px;
  border: 1px solid color-mix(in srgb, var(--cprimary) 35%, transparent);
  border-radius: 50%;
  box-shadow: 0 0 0 38px color-mix(in srgb, var(--cprimary) 4%, transparent), 0 0 0 78px color-mix(in srgb, var(--cpurple) 3%, transparent);
}
.login-eyebrow {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 20px;
  color: var(--cprimary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .14em;
}
.login-brand h1 {
  max-width: 390px;
  margin: 0;
  font-size: clamp(30px, 3vw, 43px);
  line-height: 1.24;
  letter-spacing: -.035em;
}
.login-brand p {
  max-width: 390px;
  margin: 22px 0 28px;
  color: var(--csub);
  font-size: 14px;
  line-height: 1.9;
}
.login-features {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.login-features div {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 11px 10px;
  border: 1px solid var(--cborder);
  border-radius: 9px;
  background: color-mix(in srgb, var(--cpanel) 74%, transparent);
}
.login-features b { color: var(--cprimary); font-size: 13px; }
.login-features span { color: var(--csub); font-size: 11px; line-height: 1.45; }
.login-brand-foot {
  position: absolute;
  left: 54px;
  bottom: 25px;
  color: var(--csub);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 10px;
  letter-spacing: .05em;
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
.login-card-kicker {
  margin-bottom: 13px;
  color: var(--cprimary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .15em;
}
.login-heading {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  margin-bottom: 30px;
}
.login-heading .live-dot { margin-top: 11px; flex: 0 0 auto; }
.login-title {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.035em;
  background: linear-gradient(180deg, var(--ctext), var(--cprimary));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.login-subtitle { margin-top: 5px; color: var(--csub); font-size: 12px; }
.login-optional-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 0 2px 7px;
  color: var(--csub);
  font-size: 11px;
}
.login-optional-label em { font-style: normal; opacity: .78; }
.login-submit-item { margin-top: 4px; margin-bottom: 0; }
.login-submit {
  width: 100%;
  height: 42px;
  font-size: 15px;
  letter-spacing: .2em;
}
.login-footnote {
  margin-top: 18px;
  text-align: center;
  color: var(--csub);
  font-size: 11px;
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
  .login-brand { display: none; }
  .login-card { padding: 50px 38px 30px; }
}
@media (max-width: 480px) {
  .login-full { padding: 16px; }
  .login-shell { width: 100%; }
  .login-card { padding: 46px 24px 26px; }
  .login-title { font-size: 20px; }
  .login-heading { margin-bottom: 25px; }
}
</style>
