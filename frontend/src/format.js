// -------- rate formatting with user preference --------
// preference stored in localStorage: 'auto' | 'bps' | 'kbps' | 'mbps' (network)
//                            'auto' | 'bs' | 'kbs' | 'mbs' (disk)
// auto = human-readable binary units (KB/s, MB/s ...)

const NET_PREF_KEY = 'rate-unit-net'
const DISK_PREF_KEY = 'rate-unit-disk'

export const NET_UNIT_OPTIONS = [
  { value: 'auto', label: '自动' },
  { value: 'bps', label: 'B/s' },
  { value: 'kbps', label: 'KB/s' },
  { value: 'mbps', label: 'MB/s' },
  { value: 'gbps', label: 'GB/s' },
  { value: 'mbit', label: 'Mbps（网速习惯）' },
  { value: 'gbit', label: 'Gbps（网速习惯）' },
]

export const DISK_UNIT_OPTIONS = [
  { value: 'auto', label: '自动' },
  { value: 'bs', label: 'B/s' },
  { value: 'kbs', label: 'KB/s' },
  { value: 'mbs', label: 'MB/s' },
  { value: 'gbs', label: 'GB/s' },
]

export function getNetUnit() {
  try { return localStorage.getItem(NET_PREF_KEY) || 'auto' } catch { return 'auto' }
}
export function setNetUnit(u) {
  try { localStorage.setItem(NET_PREF_KEY, u) } catch { /* ignore */ }
}
export function getDiskUnit() {
  try { return localStorage.getItem(DISK_PREF_KEY) || 'auto' } catch { return 'auto' }
}
export function setDiskUnit(u) {
  try { localStorage.setItem(DISK_PREF_KEY, u) } catch { /* ignore */ }
}

function _auto(bytesPerSec, decimal = false) {
  // decimal units look better for network (1 Mbps = 10^6); binary for disk
  const step = decimal ? 1000 : 1024
  const units = decimal
    ? ['B/s', 'KB/s', 'MB/s', 'GB/s', 'TB/s']
    : ['B/s', 'KB/s', 'MB/s', 'GB/s', 'TB/s']
  let v = bytesPerSec
  let i = 0
  while (v >= step && i < units.length - 1) { v /= step; i++ }
  return v.toFixed(1) + ' ' + units[i]
}

function _fixedDivisor(pref) {
  // returns [divisor, suffix] or null for auto
  switch (pref) {
    case 'bps': return [1, 'B/s']
    case 'kbps': return [1024, 'KB/s']
    case 'mbps': return [1024 * 1024, 'MB/s']
    case 'gbps': return [1024 ** 3, 'GB/s']
    case 'mbit': return [125000, 'Mbps']   // 1 MB = 8 Mb, bytes->megabits (decimal)
    case 'gbit': return [125000000, 'Gbps']
    case 'bs': return [1, 'B/s']
    case 'kbs': return [1024, 'KB/s']
    case 'mbs': return [1024 * 1024, 'MB/s']
    case 'gbs': return [1024 ** 3, 'GB/s']
    default: return null
  }
}

// network rate (bytes/sec input)
export function fmtNetRate(bps) {
  if (bps == null || isNaN(bps)) return '—'
  const f = _fixedDivisor(getNetUnit())
  if (f) {
    const [div, suffix] = f
    const v = bps / div
    return (v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2)) + ' ' + suffix
  }
  return _auto(bps)
}

// disk rate (bytes/sec input)
export function fmtDiskRate(bps) {
  if (bps == null || isNaN(bps)) return '—'
  const f = _fixedDivisor(getDiskUnit())
  if (f) {
    const [div, suffix] = f
    const v = bps / div
    return (v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2)) + ' ' + suffix
  }
  return _auto(bps)
}

// axis-label formatter factory for ECharts (fixed precision for axes)
export function netAxisFormatter() {
  const f = _fixedDivisor(getNetUnit())
  if (!f) return (v) => _auto(v)
  const [div, suffix] = f
  return (v) => (v / div).toFixed(v / div >= 100 ? 0 : 1) + ' ' + suffix
}

export function diskAxisFormatter() {
  const f = _fixedDivisor(getDiskUnit())
  if (!f) return (v) => _auto(v)
  const [div, suffix] = f
  return (v) => (v / div).toFixed(v / div >= 100 ? 0 : 1) + ' ' + suffix
}

export function fmtSizeMB(mb) {
  if (mb == null || isNaN(mb)) return '—'
  if (mb >= 1024 * 1024) return (mb / 1024 / 1024).toFixed(1) + ' TB'
  if (mb >= 1024) return (mb / 1024).toFixed(1) + ' GB'
  return Math.round(mb) + ' MB'
}

export function fmtSizeGB(gb) {
  if (gb == null || isNaN(gb)) return '—'
  if (gb >= 1024) return (gb / 1024).toFixed(1) + ' TB'
  return gb.toFixed(1) + ' GB'
}

export function pct(v) {
  if (v == null || isNaN(v)) return 0
  return Math.max(0, Math.min(100, Math.round(v * 10) / 10))
}

export function fmtTime(t) {
  if (!t) return '—'
  const d = new Date(t)
  if (isNaN(d.getTime())) return t
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

export function fmtUptime(seconds) {
  if (!seconds || seconds <= 0) return '—'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d}天${h}小时`
  if (h > 0) return `${h}小时${m}分`
  return `${m}分钟`
}

export function fmtNetBytes(bytes) {
  if (bytes == null || isNaN(bytes)) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  let v = bytes
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return v.toFixed(1) + ' ' + units[i]
}

// legacy alias (auto units) kept for any remaining callers
export function fmtBps(bps) {
  if (bps == null || isNaN(bps)) return '—'
  return _auto(bps)
}

export function fmtDuration(seconds) {
  if (seconds == null || isNaN(seconds) || seconds < 0) return '—'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (d > 0) return `${d}d ${h}h ${m}m`
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

export function fmtFreq(mhz) {
  if (mhz == null || isNaN(mhz) || mhz <= 0) return '—'
  return (mhz / 1000).toFixed(2) + ' GHz'
}
