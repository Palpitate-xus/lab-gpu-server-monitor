import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { createRequestScope } from '../src/requestState.js'

function dashboard(get) {
  let dispose
  const script = readFileSync(new URL('../src/views/Dashboard.vue', import.meta.url), 'utf8')
    .split('<script setup>')[1].split('</script>')[0].replace(/^import .*$/gm, '')
  const state = vm.runInNewContext(`${script}\n;({ load, stats, metrics, servers, loading, loadError })`, {
    ref: value => ({ value }), computed: fn => ({ get value() { return fn() } }),
    onMounted() {}, onUnmounted: callback => { dispose = callback }, useRouter: () => ({}),
    AntApp: { useApp: () => ({ message: {} }) }, api: { get }, createRequestScope,
    document: { hidden: false, removeEventListener() {} }, clearInterval() {},
  })
  return { state, dispose: () => dispose() }
}

test('dashboard does not overlap identical manual and timer refreshes', async () => {
  let resolve, count = 0
  const pending = new Promise(ok => { resolve = ok })
  const { state } = dashboard(path => { count++; return path === '/metrics/dashboard' ? pending : Promise.resolve({ data: [] }) })
  const first = state.load()
  await state.load(true)
  assert.equal(count, 3)
  assert.equal(state.loading.value, true)
  resolve({ data: { servers_online: 2 } })
  await first
  assert.equal(state.stats.value.servers_online, 2)
  assert.equal(state.loading.value, false)
})

test('dashboard preserves successful panels on partial failure and ignores unmounted work', async () => {
  let fail = false
  const { state, dispose } = dashboard(path => fail && path === '/metrics/dashboard'
    ? Promise.reject(new Error('failure')) : Promise.resolve({ data: path === '/metrics/dashboard' ? { servers_online: 2 } : [] }))
  await state.load()
  fail = true
  await state.load()
  assert.equal(state.stats.value.servers_online, 2)
  assert.match(state.loadError.value, /1 项数据/)
  dispose()
  await state.load()
  assert.equal(state.stats.value.servers_online, 2)
})
