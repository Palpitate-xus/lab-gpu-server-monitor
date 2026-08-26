<template>
  <el-container class="layout">
    <el-aside width="200px">
      <div class="menu-title">GPU Monitor</div>
      <el-menu :default-active="active" router>
        <el-menu-item index="/cockpit"><el-icon><DataBoard /></el-icon>驾驶舱</el-menu-item>
        <el-menu-item index="/dashboard"><el-icon><Odometer /></el-icon>总览</el-menu-item>
        <el-menu-item index="/servers"><el-icon><Monitor /></el-icon>服务器</el-menu-item>
        <el-menu-item index="/alerts">
          <el-icon><Bell /></el-icon>告警
          <el-badge v-if="openAlerts > 0" :value="openAlerts" :max="99" style="margin-left:6px" />
        </el-menu-item>
        <el-menu-item v-if="isAdmin" index="/users"><el-icon><UserFilled /></el-icon>用户管理</el-menu-item>
        <el-menu-item v-if="isAdmin" index="/settings"><el-icon><Setting /></el-icon>系统设置</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header height="60px">
        <div style="font-weight:600">{{ pageTitle }}</div>
        <el-dropdown @command="onCommand">
          <span style="cursor:pointer;display:flex;align-items:center;gap:6px">
            <el-avatar :size="30" style="background:#409eff">{{ avatarChar }}</el-avatar>
            <span>{{ user?.display_name || user?.username }}</span>
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import api from '../api'

const route = useRoute()
const router = useRouter()
const user = computed(() => JSON.parse(localStorage.getItem('user') || 'null'))
const isAdmin = computed(() => localStorage.getItem('role') === 'admin')
const active = computed(() => route.path)
const pageTitle = computed(() => route.meta.title || '')
const avatarChar = computed(() => (user.value?.username || '?').charAt(0).toUpperCase())
const openAlerts = ref(0)
let alertTimer = null

async function loadOpenAlerts() {
  try {
    const { data } = await api.get('/alerts/events?open_only=true&limit=100')
    openAlerts.value = data.length
  } catch {
    openAlerts.value = 0
  }
}

function onCommand(cmd) {
  if (cmd === 'logout') {
    ElMessageBox.confirm('确定要退出登录吗？', '提示', { type: 'warning' })
      .then(() => {
        localStorage.clear()
        router.push('/login')
      })
      .catch(() => {})
  }
}

onMounted(() => {
  loadOpenAlerts()
  alertTimer = setInterval(loadOpenAlerts, 30000)
})
onUnmounted(() => clearInterval(alertTimer))
</script>
