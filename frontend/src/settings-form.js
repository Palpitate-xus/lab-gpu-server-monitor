export function validateCollectionSettings({ poll_interval, retention_days, energy_price }) {
  if (!Number.isInteger(poll_interval) || poll_interval < 10 || poll_interval > 86400) return '采集间隔须为 10–86400 的整数秒'
  if (!Number.isInteger(retention_days) || retention_days < 0 || retention_days > 3650) return '保留天数须为 0–3650 的整数'
  if (typeof energy_price !== 'number' || !Number.isFinite(energy_price) || energy_price < 0 || energy_price > 100) return '电价须为 0–100 的数字'
  return ''
}

export function validateThresholdSettings(values) {
  const fields = [
    ['gpu_idle_vram_pct', 1, 95, '空占显存阈值'],
    ['gpu_idle_minutes', 5, 1440, '空占持续分钟'],
    ['health_cpu_pct', 50, 100, 'CPU 健康阈值'],
    ['health_mem_pct', 50, 100, '内存健康阈值'],
    ['health_disk_pct', 50, 100, '磁盘健康阈值'],
  ]
  for (const [key, min, max, label] of fields) {
    const value = values[key]
    if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max) return `${label}须为 ${min}–${max} 的数字`
  }
  return ''
}
