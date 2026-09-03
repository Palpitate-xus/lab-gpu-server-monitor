import axios from 'axios'
import { ElMessage } from 'element-plus'
import { clearSession } from './composables'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  withCredentials: true,
  xsrfCookieName: 'gpumon_csrf',
  xsrfHeaderName: 'X-CSRF-Token',
})

let redirecting = false

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401 && !redirecting) {
      redirecting = true
      clearSession()
      if (!location.pathname.startsWith('/login')) {
        ElMessage.warning('登录已过期，请重新登录')
        // dynamic import: a static router import here would be circular
        // (router.js loads view modules which import api.js) and evaluate
        // to undefined during module init, crashing the whole SPA
        import('./router').then(({ default: router }) =>
          router
            .push({ name: 'login', query: { redirect: location.pathname + location.search } })
            .finally(() => { redirecting = false })
        )
      } else {
        redirecting = false
      }
    }
    const msg = err.response?.data?.detail || err.message || '请求失败'
    err.friendlyMessage = typeof msg === 'string' ? msg : JSON.stringify(msg)
    return Promise.reject(err)
  }
)

export default api
