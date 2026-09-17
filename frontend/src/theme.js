import { computed, ref, watchEffect } from 'vue'
import { theme as antTheme } from 'ant-design-vue'

/**
 * Global theme store: 'auto' (follow system) | 'light' | 'dark'.
 * Module-level singleton — state shared across all components.
 *
 * - resolved: what is actually rendered ('light' | 'dark')
 * - toggles `html.dark` for application-level layout and chart styles
 * - persists the chosen mode in localStorage
 * - reacts live to OS theme changes while in auto mode
 */

const STORAGE_KEY = 'theme-mode'
const MODES = ['auto', 'light', 'dark']

function initialMode() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    return MODES.includes(saved) ? saved : 'auto'
  } catch {
    return 'auto'
  }
}

const mode = ref(initialMode())

const mql = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null
const systemDark = ref(mql ? mql.matches : false)

if (mql) {
  const onChange = (e) => { systemDark.value = e.matches }
  if (mql.addEventListener) mql.addEventListener('change', onChange)
  else if (mql.addListener) mql.addListener(onChange) // safari < 14
}

const resolved = computed(() => (mode.value === 'auto' ? (systemDark.value ? 'dark' : 'light') : mode.value))

watchEffect(() => {
  const el = document.documentElement
  el.classList.toggle('dark', resolved.value === 'dark')
  el.setAttribute('data-theme', resolved.value)
  try { localStorage.setItem(STORAGE_KEY, mode.value) } catch { /* ignore */ }
})

function setMode(m) {
  if (MODES.includes(m)) mode.value = m
}

/** Chart color tokens per theme (used inside ECharts options). */
export const chartTheme = computed(() =>
  resolved.value === 'dark'
    ? {
        tooltipBg: '#1f1f1f', tooltipBorder: '#424242', tooltipText: 'rgba(255,255,255,.85)',
        label: 'rgba(255,255,255,.65)', axisLine: '#424242', splitLine: 'rgba(255,255,255,.12)',
        cyan: '#13c2c2', purple: '#722ed1', green: '#52c41a', yellow: '#faad14', red: '#ff4d4f',
      }
    : {
        tooltipBg: '#ffffff', tooltipBorder: '#d9d9d9', tooltipText: 'rgba(0,0,0,.88)',
        label: 'rgba(0,0,0,.45)', axisLine: '#d9d9d9', splitLine: 'rgba(5,5,5,.06)',
        cyan: '#13c2c2', purple: '#722ed1', green: '#52c41a', yellow: '#faad14', red: '#ff4d4f',
      }
)

/** Ant Design's default theme algorithms, switched with the application mode. */
export const antThemeConfig = computed(() => ({
  algorithm: resolved.value === 'dark' ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
}))

/** Temporary menu bindings while the shell is migrated to Ant Design. */
export const uiTheme = computed(() =>
  resolved.value === 'dark'
    ? { menuText: 'rgba(255,255,255,.65)', menuActive: '#1677ff' }
    : { menuText: 'rgba(0,0,0,.65)', menuActive: '#1677ff' }
)

export function useTheme() {
  return { mode, resolved, setMode }
}
