import { createRouter, createWebHistory } from 'vue-router'
import { getSession } from './composables'

const routes = [
  { path: '/login', name: 'login', component: () => import('./views/Login.vue'), meta: { public: true } },
  { path: '/status', name: 'status', component: () => import('./views/StatusPage.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('./views/Layout.vue'),
    children: [
      { path: '', redirect: '/cockpit' },
      { path: 'cockpit', name: 'cockpit', component: () => import('./views/Cockpit.vue'), meta: { title: '驾驶舱' } },
      { path: 'dashboard', name: 'dashboard', component: () => import('./views/Dashboard.vue'), meta: { title: '总览' } },
      { path: 'servers', name: 'servers', component: () => import('./views/Servers.vue'), meta: { title: '服务器' } },
      { path: 'servers/:id', name: 'server-detail', component: () => import('./views/ServerDetail.vue'), meta: { title: '服务器详情' } },
      { path: 'alerts', name: 'alerts', component: () => import('./views/Alerts.vue'), meta: { title: '告警' } },
      { path: 'gpu-analysis', name: 'gpu-analysis', component: () => import('./views/GpuAnalysis.vue'), meta: { title: 'GPU 分析' } },
      { path: 'gpu-matrix', name: 'gpu-matrix', component: () => import('./views/GpuMatrix.vue'), meta: { title: 'GPU 矩阵' } },
      { path: 'reports', name: 'reports', component: () => import('./views/Reports.vue'), meta: { title: '利用率报表' } },
      { path: 'users', name: 'users', component: () => import('./views/Users.vue'), meta: { title: '用户管理', admin: true } },
      { path: 'settings', name: 'settings', component: () => import('./views/Settings.vue'), meta: { title: '系统设置', admin: true } }
    ]
  },
  { path: '/:pathMatch(.*)*', redirect: '/cockpit' }
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const token = getSession().token
  if (!to.meta.public && !token) return { name: 'login', query: { redirect: to.fullPath } }
  if (to.name === 'login' && token) return { name: 'cockpit' }
  if (to.meta.admin && getSession().user?.role !== 'admin') return { name: 'cockpit' }
  return true
})

export default router
