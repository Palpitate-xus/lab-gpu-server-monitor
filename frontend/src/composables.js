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
