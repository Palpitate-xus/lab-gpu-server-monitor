import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import { createLatestRequest } from '../src/requestState.js'

// Execute the actual SFC setup with fake lifecycle hooks and API responses.
// Resolving the compiler via Vue uses its installed dependency, not a test-only copy.
const require = createRequire(import.meta.url)
const vueRequire = createRequire(require.resolve('vue'))
const { parse, compileScript } = vueRequire('@vue/compiler-sfc')
const source = readFileSync(new URL('../src/views/ServerDetail.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const { scriptSetupAst } = compileScript(descriptor, { id: 'server-detail-regression' })
let setup = descriptor.scriptSetup.content
for (const node of [...scriptSetupAst].reverse()) {
  if (node.type === 'ImportDeclaration') setup = setup.slice(0, node.start) + setup.slice(node.end)
}
const composables = readFileSync(new URL('../src/composables.js', import.meta.url), 'utf8')
const latestOnly = composables.match(/export function useLatestOnly\(\) \{[\s\S]*?\n\}/)[0].replace('export ', '')

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

function createView({ role = 'admin', get = async () => ({ data: {} }), post = async () => ({ data: {} }) } = {}) {
  const messages = []
  const calls = []
  const route = { params: { id: '1' } }
  const watchers = []
  let unmount
  const context = {
    ref: value => ({ value }),
    computed: getter => ({ get value() { return getter() } }),
    watch: (value, callback) => watchers.push({ value, callback }),
    onMounted: () => {},
    onUnmounted: callback => { unmount = callback },
    useRoute: () => route,
    isAdminSession: () => role === 'admin',
    createLatestRequest,
    AntApp: { useApp: () => ({ message: Object.fromEntries(['success', 'warning', 'error'].map(kind => [kind, text => messages.push({ kind, text })])) }) },
    api: {
      get: (path, options) => { calls.push({ method: 'get', path, options }); return get(path, options) },
      post: (path, body) => { calls.push({ method: 'post', path, body }); return post(path, body) },
    },
    use: () => {},
    CanvasRenderer: {}, LineChart: {}, GridComponent: {}, LegendComponent: {}, TooltipComponent: {},
    document: { hidden: false, addEventListener() {}, removeEventListener() {} },
    setInterval: () => 1, clearInterval() {}, setTimeout: () => 1, clearTimeout() {},
  }
  runInNewContext(`${latestOnly}\n${setup}\nglobalThis.view = {
    load, loadHistory, loadProcs, loadEnterprise, ensureEnterpriseTab, refreshAll,
    loadEvents, loadNotes, openKill, openRenice, submitKill, submitRenice, clearProcessAction,
    health, metric, history, historyError, loadError, events, evSev, slowHealth, ipmi,
    notes, collectHealth, entTab, panelUpdated, panelErrors, panelLoading, procsLoading,
    procSort, procs, pendingProcess, reauthPassword, reniceValue, actionSaving,
    killModalOpen, reniceModalOpen, serverId,
  };`, context)
  return {
    ...context.view, calls, messages, document: context.document,
    invalidateRoute: () => { context.document.hidden = true; route.params.id = '2'; watchers.find(w => w.value === context.view.serverId).callback() },
    unmount: () => unmount(),
  }
}

const tick = () => new Promise(resolve => setImmediate(resolve))

test('enterprise panels are lazy, share slow-health data and expire empty snapshots', async () => {
  const view = createView({ get: async () => ({ data: { collected_at: null, nvme_smart: [] } }) })
  assert.equal(view.calls.length, 0)
  await view.ensureEnterpriseTab('nvme')
  await view.ensureEnterpriseTab('services')
  assert.equal(view.calls.length, 1, 'NVMe and services share the same fresh request')
  view.panelUpdated.value['slow-health'] -= 60001
  await view.ensureEnterpriseTab('services')
  assert.equal(view.calls.length, 2, 'empty data is not cached forever')
  await view.ensureEnterpriseTab('services', true)
  assert.equal(view.calls.length, 3, 'explicit refresh bypasses the TTL')
})

test('enterprise polling pauses while hidden and checks actual API permissions', async () => {
  const view = createView({ role: 'viewer', get: async () => ({ data: { success_rate: 100 } }) })
  for (const tab of ['nvme', 'services', 'inventory', 'ipmi']) assert.equal(await view.ensureEnterpriseTab(tab), false)
  assert.equal(view.calls.length, 0)
  await view.ensureEnterpriseTab('collect')
  assert.equal(view.collectHealth.value.success_rate, 100, 'collect-health is available to viewers')
  view.document.hidden = true
  await view.loadEnterprise(true)
  assert.equal(view.calls.length, 1)
})

test('identical panel reads are deduplicated; stale severity failures cannot replace new results', async () => {
  const first = deferred(), second = deferred()
  const view = createView({ get: (_path, options) => options.params.severity === '' ? first.promise : second.promise })
  const old = view.loadEvents()
  const joined = view.loadEvents()
  await tick()
  assert.equal(view.calls.length, 1)
  view.evSev.value = 'critical'
  const current = view.loadEvents()
  await tick()
  second.resolve({ data: [{ id: 20, severity: 'critical' }] })
  await current
  first.reject(new Error('old request failed'))
  await Promise.all([old, joined])
  assert.equal(view.events.value[0].id, 20)
  assert.equal(view.panelErrors.value.events, undefined)
  assert.equal(view.panelLoading.value.events, false)
})

test('failed panel refresh preserves successful data with an explicit stale warning', async () => {
  let fail = false
  const view = createView({ get: async () => {
    if (fail) throw { friendlyMessage: 'service unavailable' }
    return { data: { snapshot: { ok: true } } }
  } })
  await view.ensureEnterpriseTab('ipmi')
  fail = true
  await view.ensureEnterpriseTab('ipmi', true)
  assert.equal(view.ipmi.value.snapshot.ok, true)
  assert.equal(view.panelErrors.value.ipmi, 'service unavailable')
})

test('results from a previous server or unmounted view cannot populate a panel', async () => {
  for (const invalidate of ['invalidateRoute', 'unmount']) {
    const pending = deferred()
    const view = createView({ get: () => pending.promise })
    const load = view.ensureEnterpriseTab('nvme')
    await tick()
    view[invalidate]()
    pending.resolve({ data: { nvme_smart: [{ device: 'old-server' }] } })
    await load
    assert.equal(view.slowHealth.value.nvme_smart, undefined)
  }
})

test('top-level refresh reloads the currently open hardware panel', async () => {
  const view = createView({ get: async path => ({ data: path === '/servers' ? [{ id: 1 }] : path.includes('history') ? [] : {} }) })
  view.entTab.value = 'inventory'
  await view.ensureEnterpriseTab('inventory')
  await view.refreshAll()
  assert.equal(view.calls.filter(call => call.path.endsWith('/inventory')).length, 2)
  assert.ok(view.calls.some(call => call.path.endsWith('/overview')))
  assert.ok(view.calls.some(call => call.path.endsWith('/latest')))
})

test('main polling deduplicates overlaps and does not erase the last successful metric', async () => {
  const response = deferred()
  let fail = false
  const view = createView({ get: path => path.endsWith('/latest')
    ? fail ? Promise.reject({ friendlyMessage: 'connection failed' }) : response.promise
    : Promise.resolve({ data: path === '/servers' ? [{ id: 1 }] : [] }) })
  const first = view.load(), second = view.load()
  await tick()
  assert.equal(view.calls.filter(call => call.path.endsWith('/latest')).length, 1)
  response.resolve({ data: { cpu_percent: 42 } })
  await Promise.all([first, second])
  fail = true
  await view.load()
  assert.equal(view.metric.value.cpu_percent, 42)
  assert.equal(view.loadError.value, 'connection failed')
})

test('process polling deduplicates same-sort reads and keeps loading until the latest sort settles', async () => {
  const old = deferred(), current = deferred()
  const view = createView({ post: path => path.endsWith('sort=cpu') ? old.promise : current.promise })
  const first = view.loadProcs(), joined = view.loadProcs()
  await tick()
  assert.equal(view.calls.length, 1)
  view.procSort.value = 'mem'
  const second = view.loadProcs()
  await tick()
  old.resolve({ data: { processes: [{ pid: 1 }] } })
  await Promise.all([first, joined])
  assert.equal(view.procsLoading.value, true)
  current.resolve({ data: { processes: [{ pid: 2 }] } })
  await second
  assert.equal(view.procs.value[0].pid, 2)
  assert.equal(view.procsLoading.value, false)
})

test('history keeps new data when an older request fails, and preserves charts on current failure', async () => {
  const old = deferred(), current = deferred()
  let call = 0
  const view = createView({ get: () => ++call === 1 ? old.promise : call === 2 ? current.promise : Promise.reject({ friendlyMessage: 'unavailable' }) })
  const first = view.loadHistory()
  const second = view.loadHistory()
  current.resolve({ data: [{ cpu_percent: 50 }] })
  await second
  old.reject(new Error('stale failure'))
  await first
  assert.equal(view.history.value[0].cpu_percent, 50)
  assert.equal(view.historyError.value, '')
  await view.loadHistory()
  assert.equal(view.history.value[0].cpu_percent, 50)
  assert.equal(view.historyError.value, 'unavailable')
})

test('nice requires a non-empty in-range integer and never coerces null to zero', async () => {
  const view = createView()
  view.openRenice({ pid: 12, start_ticks: 100 })
  view.reauthPassword.value = 'current-password'
  for (const value of [null, undefined, '', NaN, 1.5, -21, 20]) {
    view.reniceValue.value = value
    await view.submitRenice()
  }
  assert.equal(view.calls.length, 0)
  view.reniceValue.value = 0
  await view.submitRenice()
  assert.equal(view.calls[0].body.nice, 0)
})

test('kill and renice reject repeated Enter submissions and clear passwords on success or cancel', async () => {
  for (const action of ['Kill', 'Renice']) {
    const response = deferred()
    const view = createView({ post: () => response.promise })
    view[`open${action}`]({ pid: 12, start_ticks: 100 }, 'TERM')
    view.reauthPassword.value = 'current-password'
    const first = view[`submit${action}`]()
    const second = view[`submit${action}`]()
    assert.equal(view.calls.length, 1)
    assert.equal(view.actionSaving.value, true)
    response.resolve({ data: { message: 'ok' } })
    await Promise.all([first, second])
    assert.equal(view.reauthPassword.value, '')
    assert.equal(view.pendingProcess.value, null)
    view[`open${action}`]({ pid: 13, start_ticks: 101 }, 'TERM')
    view.reauthPassword.value = 'new-password'
    view.clearProcessAction()
    assert.equal(view.reauthPassword.value, '')
    assert.equal(view.pendingProcess.value, null)
  }
})

test('every table has stable row identity and administrator panels are hidden from viewers', () => {
  for (const table of source.match(/<a-table\s(?:[^>"']|"[^"]*"|'[^']*')*>/g) || []) assert.match(table, /(?:\s|:)row-key=/)
  for (const key of ['nvme', 'services', 'inventory', 'ipmi']) assert.match(source, new RegExp(`<a-tab-pane v-if="isAdmin"[^>]*key="${key}"`))
  assert.match(source, /<a-tab-pane tab="采集健康" key="collect">/)
})
