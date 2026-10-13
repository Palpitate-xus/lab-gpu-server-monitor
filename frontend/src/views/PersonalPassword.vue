<template>
  <a-card title="修改我的密码" class="password-card">
    <a-alert type="info" show-icon message="修改后其它登录会话将失效，当前会话保持登录。" style="margin-bottom:20px" />
    <a-form ref="formRef" :model="form" :rules="rules" :disabled="saving" layout="vertical" @finish="submit">
      <a-form-item label="当前密码" name="old_password">
        <a-input-password v-model:value="form.old_password" autocomplete="current-password" :maxlength="128" />
      </a-form-item>
      <a-form-item label="新密码" name="new_password">
        <a-input-password v-model:value="form.new_password" autocomplete="new-password" placeholder="15～72 位" :maxlength="72" />
      </a-form-item>
      <a-form-item label="确认新密码" name="confirm" :dependencies="['new_password']">
        <a-input-password v-model:value="form.confirm" autocomplete="new-password" :maxlength="72" />
      </a-form-item>
      <a-button type="primary" html-type="submit" :loading="saving">修改密码</a-button>
    </a-form>
  </a-card>
</template>

<script setup>
import { onUnmounted, reactive, ref } from 'vue'
import { App as AntApp } from 'ant-design-vue'
import api from '../api'

const { message } = AntApp.useApp()
const formRef = ref()
const saving = ref(false)
const form = reactive({ old_password: '', new_password: '', confirm: '' })
const rules = {
  old_password: [{ required: true, message: '请输入当前密码' }],
  new_password: [
    { required: true, message: '请输入新密码' },
    { min: 15, max: 72, message: '新密码需要 15～72 位' },
  ],
  confirm: [{ required: true, message: '请确认新密码' }, {
    validator: async (_rule, value) => {
      if (value !== form.new_password) throw new Error('两次新密码不一致')
    },
  }],
}

function clearPasswords() {
  Object.assign(form, { old_password: '', new_password: '', confirm: '' })
}

async function submit() {
  if (saving.value) return
  saving.value = true
  try {
    await api.post('/users/change-password', {
      old_password: form.old_password, new_password: form.new_password,
    })
    clearPasswords()
    formRef.value?.clearValidate()
    message.success('密码已修改，其它会话已失效')
  } catch (error) {
    message.error(error?.friendlyMessage || '密码修改失败，请重试')
  } finally {
    saving.value = false
  }
}

onUnmounted(clearPasswords)
</script>

<style scoped>
.password-card { width: 100%; max-width: 560px; margin-inline: auto; }
@media (max-width: 768px) {
  .password-card :deep(.ant-card-body) { padding: 16px; }
  .password-card :deep(.ant-form .ant-btn) { width: 100%; }
}
</style>
