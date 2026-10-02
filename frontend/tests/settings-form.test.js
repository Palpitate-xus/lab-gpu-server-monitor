import assert from 'node:assert/strict'
import test from 'node:test'
import { validateCollectionSettings, validateThresholdSettings } from '../src/settings-form.js'

const valid = { poll_interval: 60, retention_days: 0, energy_price: 0 }
test('collection settings accept backend ranges without changing configured sampling granularity', () => {
  assert.equal(validateCollectionSettings(valid), '')
  assert.equal(validateCollectionSettings({ poll_interval: 86400, retention_days: 3650, energy_price: 100 }), '')
})

test('empty, fractional or out-of-range required settings cannot be silently omitted', () => {
  for (const [field, value] of [['poll_interval', null], ['poll_interval', 60.5], ['poll_interval', 9], ['retention_days', null], ['retention_days', -1], ['retention_days', 0.5], ['energy_price', null], ['energy_price', NaN], ['energy_price', Infinity]]) {
    assert.notEqual(validateCollectionSettings({ ...valid, [field]: value }), '')
  }
})

test('detector thresholds preserve supported decimal values and reject missing numbers', () => {
  const values = { gpu_idle_vram_pct: 30.5, gpu_idle_minutes: 30, health_cpu_pct: 90, health_mem_pct: 92, health_disk_pct: 90 }
  assert.equal(validateThresholdSettings(values), '')
  for (const key of Object.keys(values)) assert.notEqual(validateThresholdSettings({ ...values, [key]: null }), '')
  assert.notEqual(validateThresholdSettings({ ...values, gpu_idle_minutes: 1 }), '')
})
