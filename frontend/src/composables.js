import { onMounted, onUnmounted, ref } from 'vue'
import axios from 'axios'

/**
 * Auto-refreshing async loader.
 * - skips overlapping polls (previous request still in flight)
 * - pauses entirely while the tab is hidden (no background SSH storms)
 * - exposes error so views can show a failure banner
 */
export function usePoll(fetcher, intervalMs = 30000) {
  const data = ref(null)
  const loading = ref(false)
  const error = ref(null)
  const lastUpdated = ref(null)
  let timer = null
  let busy = false

  async function load() {
    if (busy || document.hidden) return
    busy = true
    loading.value = true
    try {
      data.value = await fetcher()
      error.value = null
      lastUpdated.value = new Date()
    } catch (e) {
      error.value = e?.friendlyMessage || String(e)
    } finally {
      busy = false
      loading.value = false
    }
  }

  onMounted(() => {
    load()
    if (intervalMs > 0) timer = setInterval(load, intervalMs)
  })
  onUnmounted(() => timer && clearInterval(timer))

  return { data, loading, error, lastUpdated, reload: load }
}

/**
 * Response-race guard: when several requests overlap (fast tab/range switching),
 * only the latest call may write its result. Usage:
 *   const applyLatest = useLatestOnly()
 *   applyLatest(api.get(...), (resp) => { history.value = resp.data }).catch(...)
 */
export function useLatestOnly() {
  let seq = 0
  return async function applyLatest(promise, apply) {
    const my = ++seq
    const value = await promise
    if (my !== seq) return undefined // stale response: drop silently
    return apply ? apply(value) : value
  }
}

/**
 * Session state holder.
 *
 * Authentication lives in a Secure HttpOnly cookie and is therefore not
 * readable by JavaScript. Only the non-secret user display object is cached;
 * bootstrapSession() always re-fetches /auth/me before the app mounts.
 */
function storedUser() {
  try {
    const value = JSON.parse(localStorage.getItem('user') || 'null')
    return value && typeof value === 'object' ? value : null
  } catch {
    localStorage.removeItem('user')
    return null
  }
}

const _session = {
  user: storedUser(),
}

export function getSession() { return _session }
export function setSession(user) {
  _session.user = user
  localStorage.setItem('user', JSON.stringify(user))
  localStorage.removeItem('token')
}
export function clearSession() {
  _session.user = null
  localStorage.removeItem('token')
  localStorage.removeItem('user')
  localStorage.removeItem('role')
}
export function isAdminSession() { return _session.user?.role === 'admin' }

/**
 * Re-authorize from the server on page load: refreshes role/display name and
 * drops the session when the token is dead/expired.
 */
export async function bootstrapSession() {
  try {
    const res = await axios.get('/api/auth/me', {
      withCredentials: true,
      timeout: 8000,
    })
    setSession(res.data)
  } catch {
    clearSession()
  }
}
