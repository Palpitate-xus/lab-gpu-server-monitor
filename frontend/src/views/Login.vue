<template>
  <div class="login-bg">
    <div class="login-card">
      <div class="login-title">🖥️ GPU 服务器监控</div>
      <div class="login-sub">GPU / CPU / 内存 / 磁盘 一站式监控平台</div>
      <el-form ref="formRef" :model="form" :rules="rules" size="large" @keyup.enter="submit">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" autofocus />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" placeholder="密码" show-password :prefix-icon="Lock" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" style="width: 100%" :loading="loading" @click="submit">登 录</el-button>
        </el-form-item>
      </el-form>
      <div style="text-align:center;color:#c0c4cc;font-size:12px">默认账号 admin / admin123（首次登录后请修改）</div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import api from '../api'

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
    router.push(route.query.redirect || '/dashboard')
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>
