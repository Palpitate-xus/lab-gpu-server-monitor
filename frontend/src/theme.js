import { computed, ref, watchEffect } from 'vue'

/**
 * Global theme store: 'auto' (follow system) | 'light' | 'dark'.
 * Module-level singleton — state shared across all components.
 *
 * - resolved: what is actually rendered ('light' | 'dark')
 * - toggles `html.dark` for Element Plus dark css-vars + our cockpit palette
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
        tooltipBg: '#101a2e', tooltipBorder: '#1e2d47', tooltipText: '#dce7f5',
        label: '#7d90ad', axisLine: '#1e2d47', splitLine: 'rgba(30,45,71,.5)',
        cyan: '#22d3ee', purple: '#a78bfa', green: '#34d399', yellow: '#fbbf24', red: '#f87171',
      }
    : {
        tooltipBg: '#ffffff', tooltipBorder: '#d8e2ef', tooltipText: '#1f2d3d',
        label: '#64748b', axisLine: '#d8e2ef', splitLine: 'rgba(120,143,174,.22)',
        cyan: '#0891b2', purple: '#7c3aed', green: '#059669', yellow: '#d97706', red: '#dc2626',
      }
)

/** Menu/label colors for el-menu prop binding. */
export const uiTheme = computed(() =>
  resolved.value === 'dark'
    ? { menuText: '#7d90ad', menuActive: '#22d3ee' }
    : { menuText: '#64748b', menuActive: '#0891b2' }
)

export function useTheme() {
  return { mode, resolved, setMode }
}
