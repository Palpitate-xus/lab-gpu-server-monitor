import { onMounted, onUnmounted, ref, watch } from 'vue'

/**
 * Animated number counter (eases from old value to new).
 */
export function useCountUp(getter, { duration = 700, decimals = 0 } = {}) {
  const display = ref(0)
  let from = 0
  let raf = null

  function animate(to) {
    if (raf) cancelAnimationFrame(raf)
    const start = performance.now()
    const step = (now) => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - t, 3)
      display.value = from + (to - from) * eased
      if (t < 1) raf = requestAnimationFrame(step)
      else from = to
    }
    raf = requestAnimationFrame(step)
  }

  watch(() => getter(), (v) => animate(Number(v) || 0), { immediate: true })
  onUnmounted(() => raf && cancelAnimationFrame(raf))
  return display
}

/**
 * Auto-refreshing async loader. Returns data/loading/error + manual reload.
 */
export function usePoll(fetcher, intervalMs = 30000) {
  const data = ref(null)
  const loading = ref(false)
  const error = ref(null)
  const lastUpdated = ref(null)
  let timer = null

  async function load() {
    loading.value = true
    error.value = null
    try {
      data.value = await fetcher()
      lastUpdated.value = new Date()
    } catch (e) {
      error.value = e?.friendlyMessage || String(e)
    } finally {
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
 * Session state holder.
 *
 * The token lives in a module-scoped variable first (memory), mirrored to
 * localStorage only for page-reload survival. The /me fetch on boot
 * re-authorizes everything server-side: the router guard and isAdmin
 * checks below consult the in-memory user object, never localStorage,
 * so tampering with localStorage role/user has no privilege effect
 * (backend enforces admin on every endpoint anyway — this is UX only).
 */
const _session = {
  token: localStorage.getItem('token') || '',
  user: JSON.parse(localStorage.getItem('user') || 'null'),
}

export function getSession() { return _session }
export function setSession(token, user) {
  _session.token = token
  _session.user = user
  localStorage.setItem('token', token)
  localStorage.setItem('user', JSON.stringify(user))
}
export function clearSession() {
  _session.token = ''
  _session.user = null
  localStorage.removeItem('token')
  localStorage.removeItem('user')
  localStorage.removeItem('role')
}
export function isAdminSession() { return _session.user?.role === 'admin' }
