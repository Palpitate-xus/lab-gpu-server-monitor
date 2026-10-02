<template>
  <a-layout class="layout">
    <a-layout-sider :width="208" class="app-sider">
      <div class="menu-title">
        <a-badge status="processing" />
        <span>GPU Monitor</span>
      </div>
      <a-menu mode="inline" :selected-keys="[active]" class="app-menu" @click="onNavigate">
        <a-menu-item v-for="item in menuEntries" :key="item.path">
          <component :is="item.icon" />
          <span>{{ item.label }}</span>
          <a-badge
            v-if="item.count > 0"
            :count="item.count"
            :overflow-count="99"
            :number-style="item.warning ? { backgroundColor: '#faad14' } : undefined"
            class="menu-count"
          />
        </a-menu-item>
      </a-menu>
    </a-layout-sider>

    <a-layout>
      <a-layout-header class="app-header">
        <div class="header-left">
          <a-button
            class="mobile-menu-btn"
            type="text"
            shape="circle"
            aria-label="打开主导航"
            @click="drawer = true"
          >
            <MenuOutlined />
          </a-button>
          <div class="page-title" :title="pageTitle">{{ pageTitle }}</div>
        </div>
        <div class="header-actions">
          <ThemeSwitch />
          <a-dropdown :trigger="['click']">
            <a-button
              type="text"
              class="user-trigger"
              :aria-label="`当前用户：${user?.display_name || user?.username}`"
            >
              <a-avatar :size="30" class="user-avatar">{{ avatarChar }}</a-avatar>
              <span class="user-name">{{ user?.display_name || user?.username }}</span>
              <DownOutlined class="user-arrow" />
            </a-button>
            <template #overlay>
              <a-menu @click="onUserMenuClick">
                <a-menu-item key="password">修改我的密码</a-menu-item>
                <a-menu-item key="logout">退出登录</a-menu-item>
              </a-menu>
            </template>
          </a-dropdown>
        </div>
      </a-layout-header>
      <a-layout-content class="app-content">
        <router-view :key="route.fullPath" />
      </a-layout-content>
    </a-layout>

    <a-drawer
      v-model:open="drawer"
      placement="left"
      :width="280"
      :closable="false"
      :body-style="drawerBodyStyle"
      class="mobile-nav-drawer"
    >
      <div class="drawer-brand">
        <div class="drawer-brand-name">
          <a-badge status="processing" />
          <span>GPU Monitor</span>
        </div>
        <a-button type="text" shape="circle" aria-label="关闭主导航" @click="drawer = false">
          <CloseOutlined />
        </a-button>
      </div>
      <a-menu mode="inline" :selected-keys="[active]" class="drawer-menu" @click="onNavigate">
        <a-menu-item v-for="item in menuEntries" :key="item.path">
          <component :is="item.icon" />
          <span>{{ item.label }}</span>
          <a-badge
            v-if="item.count > 0"
            :count="item.count"
            :overflow-count="99"
            :number-style="item.warning ? { backgroundColor: '#faad14' } : undefined"
            class="menu-count"
          />
        </a-menu-item>
      </a-menu>
      <div class="drawer-user">
        <a-avatar :size="36" class="user-avatar">{{ avatarChar }}</a-avatar>
        <div>
          <b>{{ user?.display_name || user?.username }}</b>
          <span>{{ isAdmin ? '管理员' : '查看者' }}</span>
        </div>
      </div>
    </a-drawer>
  </a-layout>
  <a-modal
    v-model:open="logoutOpen"
    title="确定要退出登录吗？"
    ok-text="退出登录"
    cancel-text="取消"
    ok-type="danger"
    :confirm-loading="logoutSaving"
    :cancel-button-props="{ disabled: logoutSaving }"
    :mask-closable="!logoutSaving"
    :keyboard="!logoutSaving"
    @ok="logout"
  >
    <p>退出后需要重新登录才能继续访问监控控制台。</p>
  </a-modal>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { App as AntApp } from 'ant-design-vue'
import {
  AppstoreOutlined,
  BarChartOutlined,
  BellOutlined,
  CloseOutlined,
  DashboardOutlined,
  DesktopOutlined,
  DownOutlined,
  FundProjectionScreenOutlined,
  LineChartOutlined,
  MenuOutlined,
  QuestionCircleOutlined,
  SettingOutlined,
  TeamOutlined,
} from '@ant-design/icons-vue'
import api from '../api'
import ThemeSwitch from '../components/ThemeSwitch.vue'
import { clearSession, getSession, isAdminSession } from '../composables'

const route = useRoute()
const router = useRouter()
const { message } = AntApp.useApp()
const user = computed(() => getSession().user)
const isAdmin = computed(() => isAdminSession())
const active = computed(() => route.path.startsWith('/servers') ? '/servers' : route.path)
const pageTitle = computed(() => route.meta.title || '')
const avatarChar = computed(() => (user.value?.username || '?').charAt(0).toUpperCase())
const openAlerts = ref(0)
const idleHeldCount = ref(0)
const drawer = ref(false)
const logoutOpen = ref(false)
const logoutSaving = ref(false)
const drawerBodyStyle = { padding: 0, position: 'relative' }
let alertTimer = null

const menuEntries = computed(() => [
  { path: '/cockpit', label: '驾驶舱', icon: FundProjectionScreenOutlined, count: 0 },
  { path: '/dashboard', label: '总览', icon: DashboardOutlined, count: 0 },
  { path: '/servers', label: '服务器', icon: DesktopOutlined, count: 0 },
  { path: '/gpu-analysis', label: 'GPU 分析', icon: LineChartOutlined, count: idleHeldCount.value, warning: true },
  { path: '/gpu-matrix', label: 'GPU 矩阵', icon: AppstoreOutlined, count: 0 },
  { path: '/reports', label: '利用率报表', icon: BarChartOutlined, count: 0 },
  { path: '/alerts', label: '告警', icon: BellOutlined, count: openAlerts.value },
  { path: '/help', label: '帮助 / MCP', icon: QuestionCircleOutlined, count: 0 },
  ...(isAdmin.value
    ? [
        { path: '/users', label: '用户管理', icon: TeamOutlined, count: 0 },
        { path: '/settings', label: '系统设置', icon: SettingOutlined, count: 0 },
      ]
    : []),
])

async function loadOpenAlerts() {
  if (document.hidden) return
  try {
    const { data } = await api.get('/cluster/nav-summary')
    openAlerts.value = data.open_alerts || 0
    idleHeldCount.value = data.idle_held_count || 0
  } catch {
    // Preserve the last successful badge; a failed request is not zero alerts.
  }
}

function onNavigate({ key }) {
  drawer.value = false
  if (key !== active.value) router.push(key)
}

function onUserMenuClick({ key }) {
  if (key === 'password') {
    router.push('/account/password')
    return
  }
  if (key !== 'logout') return
  logoutOpen.value = true
}

async function logout() {
  if (logoutSaving.value) return
  logoutSaving.value = true
  try {
    try {
      await api.post('/auth/logout')
    } catch (e) {
      // Only a 401 proves the session is already gone. Other failures cannot
      // confirm server-side revocation, so leave the modal open for a retry.
      if (e?.response?.status !== 401) {
        message.error(e?.friendlyMessage || '退出失败，请重试')
        return
      }
    }
    clearSession()
    logoutOpen.value = false
    await router.push('/login')
  } finally {
    logoutSaving.value = false
  }
}

onMounted(() => {
  loadOpenAlerts()
  alertTimer = setInterval(loadOpenAlerts, 30000)
})
onUnmounted(() => clearInterval(alertTimer))
</script>

<style scoped>
.app-sider {
  overflow-y: auto;
  border-right: 1px solid var(--cborder);
  background: var(--cpanel);
}
.menu-title {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  font-size: 16px;
  font-weight: 600;
  color: var(--ctext);
  border-bottom: 1px solid var(--cborder);
}
.app-menu {
  padding-top: 8px;
  border-inline-end: 0;
}
.menu-count { margin-left: auto; }
.app-header {
  height: 64px;
  padding: 0 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--cpanel);
  border-bottom: 1px solid var(--cborder);
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
  font-size: 16px;
  font-weight: 600;
}
.header-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
}
.user-trigger {
  height: 40px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.user-avatar {
  flex: 0 0 auto;
  background: #1677ff;
}
.app-content {
  min-width: 0;
  padding: 16px;
  overflow-y: auto;
}
.mobile-menu-btn { display: none; }
.drawer-brand {
  height: 64px;
  padding: 0 12px 0 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--cborder);
}
.drawer-brand-name {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
  font-weight: 600;
}
.drawer-menu {
  padding-top: 8px;
  border-inline-end: 0;
}
.drawer-user {
  position: absolute;
  left: 16px;
  right: 16px;
  bottom: 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--cborder);
  border-radius: 8px;
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

@media (max-width: 768px) {
  .app-sider { display: none; }
  .app-header { padding: 0 8px; }
  .header-left { flex: 1 1 auto; gap: 4px; }
  .page-title { font-size: 15px; }
  .header-actions { gap: 2px; }
  .user-name,
  .user-arrow { display: none; }
  .mobile-menu-btn { display: inline-flex; }
  .app-content { padding: 10px; }
}
</style>
