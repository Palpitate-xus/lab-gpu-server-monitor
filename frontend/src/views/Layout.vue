<template>
  <el-container class="layout cockpit">
    <el-aside width="200px" class="dark-aside">
      <div class="menu-title">
        <span class="live-dot"></span>
        <span>GPU Monitor</span>
      </div>
      <el-menu :default-active="active" router class="dark-menu" background-color="transparent" :text-color="uiTheme.menuText" :active-text-color="uiTheme.menuActive">
        <el-menu-item index="/cockpit"><el-icon><DataBoard /></el-icon>驾驶舱</el-menu-item>
        <el-menu-item index="/dashboard"><el-icon><Odometer /></el-icon>总览</el-menu-item>
        <el-menu-item index="/servers"><el-icon><Monitor /></el-icon>服务器</el-menu-item>
        <el-menu-item index="/gpu-analysis">
          <el-icon><Cpu /></el-icon>GPU 分析
          <span v-if="idleHeldCount > 0" class="menu-badge menu-badge-warn">{{ idleHeldCount > 99 ? '99+' : idleHeldCount }}</span>
        </el-menu-item>
        <el-menu-item index="/alerts">
          <el-icon><Bell /></el-icon>告警
          <span v-if="openAlerts > 0" class="menu-badge">{{ openAlerts > 99 ? '99+' : openAlerts }}</span>
        </el-menu-item>
        <el-menu-item v-if="isAdmin" index="/users"><el-icon><UserFilled /></el-icon>用户管理</el-menu-item>
        <el-menu-item v-if="isAdmin" index="/settings"><el-icon><Setting /></el-icon>系统设置</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header height="60px" class="dark-header">
        <div style="font-weight:600;letter-spacing:0.04em">{{ pageTitle }}</div>
        <div style="display:flex;align-items:center;gap:14px">
          <ThemeSwitch />
          <el-dropdown @command="onCommand">
            <span style="cursor:pointer;display:flex;align-items:center;gap:6px;color:var(--ctext)">
              <el-avatar :size="30" style="background:linear-gradient(135deg,var(--cprimary),var(--cpurple))">{{ avatarChar }}</el-avatar>
              <span>{{ user?.display_name || user?.username }}</span>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main class="dark-main">
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
import ThemeSwitch from '../components/ThemeSwitch.vue'
import { clearSession, getSession, isAdminSession } from '../composables'
import { uiTheme } from '../theme'
import '../cockpit.css'

const route = useRoute()
const router = useRouter()
const user = computed(() => getSession().user)
const isAdmin = computed(() => isAdminSession())
const active = computed(() => route.path)
const pageTitle = computed(() => route.meta.title || '')
const avatarChar = computed(() => (user.value?.username || '?').charAt(0).toUpperCase())
const openAlerts = ref(0)
const idleHeldCount = ref(0)
let alertTimer = null

async function loadOpenAlerts() {
  try {
    const [events, analysis] = await Promise.all([
      api.get('/alerts/events?open_only=true&limit=100'),
      api.get('/cluster/gpu-analysis').catch(() => null),
    ])
    openAlerts.value = events.data.length
    if (analysis) idleHeldCount.value = analysis.data.idle_held_count || 0
  } catch {
    openAlerts.value = 0
  }
}

function onCommand(cmd) {
  if (cmd === 'logout') {
    ElMessageBox.confirm('确定要退出登录吗？', '提示', { type: 'warning' })
      .then(() => {
        clearSession()
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

<style scoped>
.dark-aside {
  background: var(--cpanel2) !important;
  border-right: 1px solid var(--cborder) !important;
}
.menu-title {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-weight: 700;
  font-size: 15px;
  letter-spacing: 0.05em;
  color: var(--cprimary);
  border-bottom: 1px solid var(--cborder);
}
.dark-menu {
  border-right: none !important;
}
.menu-badge {
  margin-left: 8px;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--cred);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  line-height: 18px;
  text-align: center;
  display: inline-block;
  vertical-align: middle;
  align-self: center;
  box-shadow: 0 0 0 2px var(--cpanel2);
}
.menu-badge-warn {
  background: var(--cyellow);
}
.dark-menu :deep(.el-menu-item.is-active) {
  background: var(--ctable-hover) !important;
  border-right: 2px solid var(--cprimary);
}
.dark-menu :deep(.el-menu-item:hover) {
  background: var(--ctable-hover);
}
.dark-header {
  background: var(--cpanel) !important;
  border-bottom: 1px solid var(--cborder) !important;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
}
.dark-main {
  padding: 16px;
  overflow-y: auto;
}
</style>
