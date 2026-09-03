<template>
  <div class="page-wrap mfa-page">
    <el-card class="page-card mfa-card">
      <template #header>
        <div class="mfa-card-head">
          <div><b>保护管理员账户</b><span>绑定基于时间的一次性动态码（TOTP）</span></div>
          <el-tag type="warning" effect="plain">必须完成</el-tag>
        </div>
      </template>
      <el-skeleton v-if="loading" :rows="4" animated />
      <el-alert v-else-if="setupError" type="error" :closable="false" show-icon title="MFA 初始化失败">
        <template #default>
          <span>{{ setupError }}</span>
          <el-button text type="primary" @click="setup">重新加载</el-button>
        </template>
      </el-alert>
      <div v-else class="mfa-layout">
        <aside class="mfa-steps" aria-label="绑定步骤">
          <div class="mfa-step active"><span>1</span><div><b>打开认证器</b><p>使用支持 TOTP 的密码管理器或认证器应用。</p></div></div>
          <div class="mfa-step"><span>2</span><div><b>录入账户</b><p>选择“手动输入密钥”，粘贴右侧账户密钥。</p></div></div>
          <div class="mfa-step"><span>3</span><div><b>完成验证</b><p>输入认证器显示的 6 位动态码。</p></div></div>
        </aside>

        <div class="mfa-form-wrap">
          <el-alert
            type="warning"
            :closable="false"
            show-icon
            title="绑定完成前，管理员写操作会被拒绝。"
            class="mfa-warning"
          />
          <el-form label-position="top" class="mfa-form">
            <el-form-item label="账户密钥">
              <el-input :model-value="secret" readonly class="mono">
                <template #append><el-button aria-label="复制账户密钥" @click="copy(secret)">复制</el-button></template>
              </el-input>
              <div class="mfa-field-help">密钥只用于本次绑定，请勿发送给其他人。</div>
            </el-form-item>
            <el-form-item label="配置 URI（高级）">
              <el-input :model-value="uri" readonly class="mono">
                <template #append><el-button aria-label="复制配置 URI" @click="copy(uri)">复制</el-button></template>
              </el-input>
            </el-form-item>
            <el-form-item label="6 位动态码">
              <el-input v-model="code" maxlength="6" inputmode="numeric" autocomplete="one-time-code" placeholder="认证器当前显示的验证码" class="mfa-code" />
            </el-form-item>
            <el-button type="primary" class="mfa-submit" :loading="saving" :disabled="!/^[0-9]{6}$/.test(code)" @click="confirm">
              验证并启用 MFA
            </el-button>
          </el-form>
        </div>
      </div>
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
const setupError = ref('')
const secret = ref('')
const uri = ref('')
const code = ref('')

async function setup() {
  loading.value = true
  setupError.value = ''
  try {
    const { data } = await api.post('/auth/mfa/setup')
    secret.value = data.secret
    uri.value = data.uri
  } catch (e) {
    setupError.value = e.friendlyMessage || '暂时无法生成绑定信息，请稍后重试。'
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

<style scoped>
.mfa-page { max-width: 940px; margin: 18px auto 0; }
.mfa-card { overflow: hidden; }
.mfa-card-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.mfa-card-head > div { display: flex; flex-direction: column; gap: 4px; }
.mfa-card-head b { font-size: 17px; }
.mfa-card-head span { color: var(--csub); font-size: 12px; }
.mfa-layout { display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: 34px; }
.mfa-steps {
  padding: 20px;
  border: 1px solid var(--cborder);
  border-radius: 12px;
  background: var(--cpanel2);
}
.mfa-step { display: grid; grid-template-columns: 30px 1fr; gap: 11px; position: relative; padding-bottom: 25px; }
.mfa-step:last-child { padding-bottom: 0; }
.mfa-step::after { content: ""; position: absolute; top: 31px; bottom: 4px; left: 14px; width: 1px; background: var(--cborder); }
.mfa-step:last-child::after { display: none; }
.mfa-step > span {
  width: 30px; height: 30px; display: inline-flex; align-items: center; justify-content: center;
  border: 1px solid var(--cborder); border-radius: 50%; background: var(--cpanel); color: var(--csub); font: 700 12px ui-monospace, monospace;
}
.mfa-step.active > span { border-color: var(--cprimary); color: var(--cprimary); box-shadow: 0 0 0 4px color-mix(in srgb, var(--cprimary) 9%, transparent); }
.mfa-step b { font-size: 13px; }
.mfa-step p { margin: 5px 0 0; color: var(--csub); font-size: 12px; line-height: 1.65; }
.mfa-form-wrap { min-width: 0; padding: 4px 0; }
.mfa-warning { margin-bottom: 20px; }
.mfa-form :deep(.el-form-item__label) { padding-bottom: 7px; font-weight: 600; }
.mfa-field-help { width: 100%; margin-top: 6px; color: var(--csub); font-size: 11px; }
.mfa-code { max-width: 260px; }
.mfa-code :deep(.el-input__inner) { font-size: 17px; letter-spacing: .18em; font-variant-numeric: tabular-nums; }
.mfa-submit { min-width: 180px; }
@media (max-width: 760px) {
  .mfa-page { margin-top: 8px; }
  .mfa-layout { grid-template-columns: 1fr; gap: 22px; }
  .mfa-steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; padding: 12px; }
  .mfa-step { display: flex; flex-direction: column; gap: 7px; padding: 0; }
  .mfa-step::after, .mfa-step p { display: none; }
  .mfa-step b { font-size: 11px; }
  .mfa-code, .mfa-submit { max-width: none; width: 100%; }
}
@media (max-width: 480px) {
  .mfa-card-head b { font-size: 15px; }
  .mfa-card-head > div > span { display: none; }
  .mfa-card :deep(.el-card__body) { padding: 16px; }
  .mfa-steps { gap: 5px; }
  .mfa-step > span { width: 27px; height: 27px; }
}
</style>
