<template>
  <div class="cockpit login-full">
    <div class="login-grid-glow"></div>
    <div class="login-card">
      <div style="display:flex;align-items:center;gap:10px;justify-content:center;margin-bottom:6px">
        <span class="live-dot"></span>
        <div class="login-title">GPU 集群监控平台</div>
      </div>
      <div class="login-sub">LAB GPU-SERVER MONITOR · COCKPIT</div>
      <el-form ref="formRef" :model="form" :rules="rules" size="large" @keyup.enter="submit">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" autofocus class="dark-input" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" placeholder="密码" show-password :prefix-icon="Lock" class="dark-input" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" style="width: 100%; height: 42px; font-size: 15px; letter-spacing: 0.2em" :loading="loading" @click="submit">登 录</el-button>
        </el-form-item>
      </el-form>
      <div style="text-align:center;color:#5b6b85;font-size:12px;margin-top:4px">默认账号 admin / admin123（首次登录后请修改）</div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import api from '../api'
import '../cockpit.css'

const router = useRouter()
const route = useRoute()
const formRef = ref()
const loading = ref(false)
const form = reactive({ username: '', password: '' })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

async function submit() {
  await formRef.value.validate().catch(() => Promise.reject())
  loading.value = true
  try {
    const { data } = await api.post('/auth/login', new URLSearchParams(form))
    localStorage.setItem('token', data.access_token)
    localStorage.setItem('user', JSON.stringify(data.user))
    localStorage.setItem('role', data.user.role)
    ElMessage.success(`欢迎，${data.user.display_name || data.user.username}`)
    router.push(route.query.redirect || '/cockpit')
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '登录失败')
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
}
.login-grid-glow {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(34, 211, 238, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(34, 211, 238, 0.05) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: radial-gradient(ellipse 70% 60% at 50% 40%, #000 30%, transparent 75%);
  -webkit-mask-image: radial-gradient(ellipse 70% 60% at 50% 40%, #000 30%, transparent 75%);
}
.login-card {
  width: 400px;
  padding: 38px 36px 28px;
  background: linear-gradient(180deg, rgba(19, 30, 51, 0.92), rgba(13, 21, 38, 0.95));
  border: 1px solid #1e2d47;
  border-radius: 12px;
  box-shadow: 0 18px 60px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(34, 211, 238, 0.06);
  position: relative;
  z-index: 1;
}
.login-card::before {
  content: "";
  position: absolute;
  inset: 0 0 auto 0;
  height: 2px;
  border-radius: 12px 12px 0 0;
  background: linear-gradient(90deg, transparent, rgba(34, 211, 238, 0.7), transparent);
}
.login-title {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.06em;
  background: linear-gradient(180deg, #fff, #9fd8e8);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.login-sub {
  text-align: center;
  color: #5b6b85;
  font-size: 11px;
  letter-spacing: 0.25em;
  margin-bottom: 26px;
}
.dark-input :deep(.el-input__wrapper) {
  background: rgba(11, 18, 32, 0.8);
  border: 1px solid #1e2d47;
  box-shadow: none;
}
.dark-input :deep(.el-input__inner) {
  color: #dce7f5;
}
.dark-input :deep(.el-input__prefix .el-icon) {
  color: #7d90ad;
}
</style>
