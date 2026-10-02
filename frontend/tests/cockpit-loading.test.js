import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/views/Cockpit.vue', import.meta.url), 'utf8')
const loadSource = source.match(/^async function loadAll\(\) \{[\s\S]*?^\}/m)[0]
const makeRef = value => ({ value })

function cockpit(get) {
  const refs = {
    stats: makeRef({ servers_online: 2 }), gpuMatrix: makeRef([{ server_id: 1 }]), matrixLoaded: makeRef(true),
    alerts: makeRef([{ id: 1 }]), latest: makeRef([{ server_id: 1 }]),
    healthSummary: makeRef([{ overall: 'ok' }]), energy: makeRef({ total_kwh: 10 }),
    clusterPowerW: makeRef(500), navSummary: makeRef({ open_alerts: 25 }),
  }
  const load = vm.runInNewContext(`(${loadSource})`, { ...refs, api: { get } })
  return { load, ...refs }
}

test('cockpit failures reject the refresh and preserve last successful panel values', async () => {
  const state = cockpit(() => Promise.reject(new Error('unavailable')))
  await assert.rejects(state.load(), /资源总览.*告警计数/)
  assert.deepEqual(state.stats.value, { servers_online: 2 })
  assert.equal(state.gpuMatrix.value.length, 1)
  assert.equal(state.navSummary.value.open_alerts, 25)
  assert.equal(state.clusterPowerW.value, 500)
})

test('cockpit uses a separate total alert count and applies successful panels on partial failure', async () => {
  const state = cockpit(path => {
    if (path === '/metrics/dashboard') return Promise.reject(new Error('unavailable'))
    if (path === '/cluster/nav-summary') return Promise.resolve({ data: { open_alerts: 100 } })
    if (path.includes('/alerts/events')) return Promise.resolve({ data: Array.from({ length: 20 }, (_, id) => ({ id, recovered_at: 'today' })) })
    return Promise.resolve({ data: [] })
  })
  await assert.rejects(state.load(), /资源总览/)
  assert.equal(state.navSummary.value.open_alerts, 100)
  assert.equal(state.alerts.value.filter(row => !row.recovered_at).length, 0)
  assert.match(source, /const openAlerts = computed\(\(\) => navSummary\.value\?\.open_alerts/)
  assert.match(source, /error \? 'warning'/)
})
