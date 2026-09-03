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
        <el-menu-item index="/gpu-matrix"><el-icon><Grid /></el-icon>GPU 矩阵</el-menu-item>
        <el-menu-item index="/reports"><el-icon><TrendCharts /></el-icon>利用率报表</el-menu-item>
        <el-menu-item index="/alerts">
          <el-icon><Bell /></el-icon>告警
          <span v-if="openAlerts > 0" class="menu-badge">{{ openAlerts > 99 ? '99+' : openAlerts }}</span>
        </el-menu-item>
        <el-menu-item index="/help"><el-icon><QuestionFilled /></el-icon>帮助 / MCP</el-menu-item>
        <el-menu-item v-if="isAdmin" index="/users"><el-icon><UserFilled /></el-icon>用户管理</el-menu-item>
        <el-menu-item v-if="isAdmin" index="/settings"><el-icon><Setting /></el-icon>系统设置</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header height="60px" class="dark-header">
        <div class="header-left">
          <el-button class="mobile-menu-btn" text :icon="Menu" aria-label="打开主导航" @click="drawer = true" />
          <div class="page-title" :title="pageTitle">{{ pageTitle }}</div>
        </div>
        <div class="header-actions">
          <ThemeSwitch />
          <el-dropdown @command="onCommand">
            <span class="user-trigger" role="button" tabindex="0" :aria-label="`当前用户：${user?.display_name || user?.username}`">
              <el-avatar :size="30" style="background:linear-gradient(135deg,var(--cprimary),var(--cpurple))">{{ avatarChar }}</el-avatar>
              <span class="user-name">{{ user?.display_name || user?.username }}</span>
              <el-icon class="user-arrow"><ArrowDown /></el-icon>
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
        <router-view :key="route.fullPath" />
      </el-main>
    </el-container>

    <el-drawer v-model="drawer" direction="ltr" size="min(280px, 82vw)" :with-header="false" class="mobile-nav-drawer">
      <div class="drawer-brand">
        <div class="drawer-brand-name"><span class="live-dot"></span>GPU Monitor</div>
        <el-button text circle :icon="Close" aria-label="关闭主导航" @click="drawer = false" />
      </div>
      <el-menu :default-active="active" router class="dark-menu drawer-menu" @select="drawer = false">
        <el-menu-item index="/cockpit"><el-icon><DataBoard /></el-icon>驾驶舱</el-menu-item>
        <el-menu-item index="/dashboard"><el-icon><Odometer /></el-icon>总览</el-menu-item>
        <el-menu-item index="/servers"><el-icon><Monitor /></el-icon>服务器</el-menu-item>
        <el-menu-item index="/gpu-analysis">
          <el-icon><Cpu /></el-icon>GPU 分析
          <span v-if="idleHeldCount > 0" class="menu-badge menu-badge-warn">{{ idleHeldCount > 99 ? '99+' : idleHeldCount }}</span>
        </el-menu-item>
        <el-menu-item index="/gpu-matrix"><el-icon><Grid /></el-icon>GPU 矩阵</el-menu-item>
        <el-menu-item index="/reports"><el-icon><TrendCharts /></el-icon>利用率报表</el-menu-item>
        <el-menu-item index="/alerts">
          <el-icon><Bell /></el-icon>告警
          <span v-if="openAlerts > 0" class="menu-badge">{{ openAlerts > 99 ? '99+' : openAlerts }}</span>
        </el-menu-item>
        <el-menu-item index="/help"><el-icon><QuestionFilled /></el-icon>帮助 / MCP</el-menu-item>
        <el-menu-item v-if="isAdmin" index="/users"><el-icon><UserFilled /></el-icon>用户管理</el-menu-item>
        <el-menu-item v-if="isAdmin" index="/settings"><el-icon><Setting /></el-icon>系统设置</el-menu-item>
      </el-menu>
      <div class="drawer-user">
        <el-avatar :size="34" style="background:linear-gradient(135deg,var(--cprimary),var(--cpurple))">{{ avatarChar }}</el-avatar>
        <div><b>{{ user?.display_name || user?.username }}</b><span>{{ isAdmin ? '管理员' : '查看者' }}</span></div>
      </div>
    </el-drawer>
  </el-container>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  Bell,
  Close,
  Cpu,
  DataBoard,
  Grid,
  Menu,
  Monitor,
  Odometer,
  QuestionFilled,
  Setting,
  TrendCharts,
  UserFilled,
} from '@element-plus/icons-vue'
import api from '../api'
import ThemeSwitch from '../components/ThemeSwitch.vue'
import { clearSession, getSession, isAdminSession } from '../composables'
import { uiTheme } from '../theme'
import '../cockpit.css'

const route = useRoute()
const router = useRouter()
const user = computed(() => getSession().user)
const isAdmin = computed(() => isAdminSession())
const active = computed(() => route.path.startsWith('/servers') ? '/servers' : route.path)
const pageTitle = computed(() => route.meta.title || '')
const avatarChar = computed(() => (user.value?.username || '?').charAt(0).toUpperCase())
const openAlerts = ref(0)
const idleHeldCount = ref(0)
const drawer = ref(false)
let alertTimer = null

async function loadOpenAlerts() {
  if (document.hidden) return
  try {
    const [events, analysis] = await Promise.allSettled([
      api.get('/alerts/events?open_only=true&limit=100'),
      api.get('/cluster/gpu-analysis'),
    ])
    openAlerts.value = events.status === 'fulfilled' ? events.value.data.length : 0
    if (analysis.status === 'fulfilled') idleHeldCount.value = analysis.value.data.idle_held_count || 0
  } catch {
    openAlerts.value = 0
  }
}

function onCommand(cmd) {
  if (cmd === 'logout') {
    ElMessageBox.confirm('确定要退出登录吗？', '提示', { type: 'warning' })
      .then(async () => {
        await api.post('/auth/logout')
        clearSession()
        router.push('/login')
      })
      .catch((e) => {
        if (e && e.friendlyMessage) ElMessageBox.alert(e.friendlyMessage, '退出失败')
      })
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
  overflow-y: auto;
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
.header-left {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 12px;
}
.page-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
  letter-spacing: 0.04em;
}
.header-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 14px;
}
.user-trigger {
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ctext);
  outline: none;
}
.user-trigger:focus-visible {
  border-radius: 8px;
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--cprimary) 35%, transparent);
}
.dark-main {
  min-width: 0;
  padding: 16px;
  overflow-y: auto;
}
.mobile-menu-btn {
  display: none !important;
}
@media (max-width: 768px) {
  .dark-header {
    padding: 0 10px;
  }
  .header-left {
    flex: 1 1 auto;
    gap: 4px;
  }
  .page-title {
    font-size: 15px;
    letter-spacing: 0.02em;
  }
  .header-actions {
    gap: 5px;
  }
  .user-name,
  .user-arrow {
    display: none;
  }
  .mobile-menu-btn {
    display: inline-flex !important;
    flex: 0 0 auto;
  }
  .drawer-brand {
    height: 64px;
    padding: 0 14px 0 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid var(--cborder);
  }
  .drawer-brand-name {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--cprimary);
    font-weight: 700;
    letter-spacing: .04em;
  }
  .drawer-menu {
    padding: 8px 0;
  }
  .drawer-user {
    position: absolute;
    left: 18px;
    right: 18px;
    bottom: 18px;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px;
    border: 1px solid var(--cborder);
    border-radius: 10px;
    background: var(--cpanel2);
  }
  .drawer-user div {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .drawer-user b {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .drawer-user span {
    color: var(--csub);
    font-size: 12px;
  }
}
</style>
