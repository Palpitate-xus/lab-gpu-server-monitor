import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { createRequestScope } from '../src/requestState.js'

const script = readFileSync(new URL('../src/views/Reports.vue', import.meta.url), 'utf8')
  .split('<script setup>')[1].split('</script>')[0].replace(/^import .*$/gm, '')
const deferred = () => {
  let resolve, reject
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail })
  return { promise, resolve, reject }
}

function view(get) {
  let dispose, filename
  const state = vm.runInNewContext(`${script}\n;({ load, report, hours, tag, loading, loadError, loadedQuery, idleRatio, idleRatioColor, exportCsv })`, {
    ref: value => ({ value }), computed: fn => ({ get value() { return fn() } }),
    onMounted: () => {}, onUnmounted: callback => { dispose = callback },
    createRequestScope, api: { get }, AntApp: { useApp: () => ({ message: { info() {}, error() {} } }) },
    Blob, URL: { createObjectURL: () => 'blob:mock', revokeObjectURL() {} },
    csvRow: cells => cells.join(','), document: { createElement: () => ({ click() { filename = this.download } }) },
  })
  return { state, dispose: () => dispose(), filename: () => filename }
}

test('reports keep data, loaded query, error and loading scoped to the latest filter', async () => {
  const old = deferred(), latest = deferred()
  const { state } = view((_path, options) => options.params.hours === 24 ? old.promise : latest.promise)
  const first = state.load()
  state.hours.value = 168
  state.tag.value = 'current'
  const second = state.load()
  latest.resolve({ data: { window_hours: 168, servers: [] } })
  await second
  old.resolve({ data: { window_hours: 24, servers: [] } })
  await first
  assert.equal(state.report.value.window_hours, 168)
  assert.equal(state.loadedQuery.value.hours, 168)
  assert.equal(state.loadedQuery.value.tag, 'current')
  assert.equal(state.loading.value, false)
  assert.equal(state.loadError.value, '')
})

test('old report failures and unmounted responses cannot modify current state', async () => {
  const old = deferred()
  const { state, dispose } = view((_path, options) => options.params.hours === 24 ? old.promise : Promise.resolve({ data: { window_hours: 72 } }))
  const first = state.load()
  state.hours.value = 72
  await state.load()
  old.reject(new Error('obsolete'))
  await first
  assert.equal(state.loadError.value, '')
  dispose()
  await state.load()
  assert.equal(state.report.value.window_hours, 72)
})

test('CSV filenames describe the loaded query and failed refreshes cannot export stale data', async () => {
  let fail = false
  const { state, filename } = view(() => fail ? Promise.reject(new Error('current failure')) : Promise.resolve({ data: { window_hours: 24, servers: [{ server_name: 'demo' }] } }))
  await state.load()
  state.hours.value = 168
  state.exportCsv()
  assert.equal(filename(), 'gpu-utilization-24h.csv')
  fail = true
  await state.load()
  assert.equal(state.loadError.value, '加载失败')
  state.exportCsv()
  assert.equal(filename(), 'gpu-utilization-24h.csv')
})

test('unknown legacy card time stays unknown instead of showing a fabricated ratio', () => {
  const { state } = view(() => {})
  state.report.value = { total_gpu_hours: null, total_idle_gpu_hours: 8, idle_ratio_pct: null }
  assert.equal(state.idleRatio.value, null)
  assert.equal(state.idleRatioColor(null), undefined, 'unknown ratios must not appear healthy')
  assert.equal(state.idleRatioColor(0), 'green')
  assert.equal(state.idleRatioColor(20), 'orange')
  assert.equal(state.idleRatioColor(40), 'red')
  state.report.value = { total_gpu_hours: 8, total_idle_gpu_hours: 8, idle_ratio_pct: 100 }
  assert.equal(state.idleRatio.value, 100)
})
