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

// rates are bytes/sec
export function fmtBps(bps) {
  if (bps == null || isNaN(bps)) return '—'
  const units = ['B/s', 'KB/s', 'MB/s', 'GB/s', 'TB/s']
  let v = bps
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return v.toFixed(1) + ' ' + units[i]
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
