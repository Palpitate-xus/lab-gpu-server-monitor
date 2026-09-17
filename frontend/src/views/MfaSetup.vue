<template>
  <div class="mfa-page">
    <a-card class="mfa-card">
      <template #title>
        <div class="mfa-card-head">
          <div>
            <b>绑定 MFA 动态码</b>
            <span>用认证器 App 录入账户，登录时增加一道校验</span>
          </div>
          <a-tag v-if="mfaRequired" color="orange">管理员必须完成</a-tag>
          <a-tag v-else>可选</a-tag>
        </div>
      </template>

      <a-skeleton v-if="loading" active :paragraph="{ rows: 4 }" />
      <a-alert
        v-else-if="setupError"
        type="error"
        show-icon
        message="MFA 初始化失败"
        :description="setupError"
      >
        <template #action>
          <a-button size="small" danger @click="setup">重新加载</a-button>
        </template>
      </a-alert>

      <div v-else class="mfa-layout">
        <aside class="mfa-steps" aria-label="绑定步骤">
          <a-steps direction="vertical" :current="2" :items="stepItems" />
        </aside>

        <div class="mfa-form-wrap">
          <a-alert
            type="warning"
            show-icon
            message="绑定完成前，管理员写操作会被拒绝。"
            class="mfa-warning"
          />
          <a-form layout="vertical" class="mfa-form">
            <a-form-item label="账户密钥">
              <a-input :value="secret" readonly class="mono">
                <template #addonAfter>
                  <a-button type="link" size="small" aria-label="复制账户密钥" @click="copy(secret)">复制</a-button>
                </template>
              </a-input>
              <div class="mfa-field-help">密钥只用于本次绑定，请勿发送给其他人。</div>
            </a-form-item>
            <a-form-item label="配置 URI（高级）">
              <a-input :value="uri" readonly class="mono">
                <template #addonAfter>
                  <a-button type="link" size="small" aria-label="复制配置 URI" @click="copy(uri)">复制</a-button>
                </template>
              </a-input>
            </a-form-item>
            <a-form-item label="6 位动态码">
              <a-input
                v-model:value="code"
                maxlength="6"
                inputmode="numeric"
                autocomplete="one-time-code"
                placeholder="认证器当前显示的验证码"
                class="mfa-code"
              />
            </a-form-item>
            <a-button
              type="primary"
              class="mfa-submit"
              :loading="saving"
              :disabled="!/^[0-9]{6}$/.test(code)"
              @click="confirm"
            >
              验证并启用 MFA
            </a-button>
          </a-form>
        </div>
      </div>
    </a-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { App as AntApp } from 'ant-design-vue'
import api from '../api'
import { getSession, setSession } from '../composables'

const router = useRouter()
const { message } = AntApp.useApp()
const mfaRequired = computed(() => getSession().user?.mfa_required)
const loading = ref(true)
const saving = ref(false)
const setupError = ref('')
const secret = ref('')
const uri = ref('')
const code = ref('')
const stepItems = [
  { title: '打开认证器', description: '使用支持 TOTP 的密码管理器或认证器应用。' },
  { title: '录入账户', description: '选择手动输入密钥，粘贴右侧账户密钥。' },
  { title: '完成验证', description: '输入认证器显示的 6 位动态码。' },
]

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
  try {
    if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable')
    await navigator.clipboard.writeText(value)
    message.success('已复制')
  } catch {
    try {
      const textarea = document.createElement('textarea')
      textarea.value = value
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      textarea.remove()
      message.success('已复制')
    } catch {
      message.warning('复制失败，请手动选择文本复制')
    }
  }
}

async function confirm() {
  saving.value = true
  try {
    const { data } = await api.post('/auth/mfa/confirm', { code: code.value })
    setSession(data.user)
    message.success('管理员 MFA 已启用')
    router.push('/cockpit')
  } catch (e) {
    message.error(e.friendlyMessage || '动态码验证失败')
  } finally {
    saving.value = false
  }
}

onMounted(setup)
</script>

<style scoped>
.mfa-page {
  max-width: 960px;
  margin: 18px auto 0;
}
.mfa-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.mfa-card-head > div {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.mfa-card-head b { font-size: 17px; }
.mfa-card-head span {
  color: var(--csub);
  font-size: 12px;
  font-weight: 400;
}
.mfa-layout {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 32px;
}
.mfa-steps {
  padding: 20px;
  border: 1px solid var(--cborder);
  border-radius: 8px;
  background: var(--cpanel2);
}
.mfa-form-wrap { min-width: 0; }
.mfa-warning { margin-bottom: 20px; }
.mfa-field-help {
  margin-top: 6px;
  color: var(--csub);
  font-size: 12px;
}
.mfa-code { max-width: 260px; }
.mfa-code :deep(input) {
  font-size: 17px;
  letter-spacing: .18em;
  font-variant-numeric: tabular-nums;
}
.mfa-submit { min-width: 180px; }

@media (max-width: 760px) {
  .mfa-page { margin-top: 8px; }
  .mfa-layout { grid-template-columns: 1fr; gap: 20px; }
  .mfa-steps { padding: 16px; }
  .mfa-code,
  .mfa-submit { max-width: none; width: 100%; }
}

@media (max-width: 480px) {
  .mfa-card-head b { font-size: 15px; }
  .mfa-card-head > div > span { display: none; }
}
</style>
