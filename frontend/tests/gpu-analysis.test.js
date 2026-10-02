import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { createRequestScope } from '../src/requestState.js'

const script = readFileSync(new URL('../src/views/GpuAnalysis.vue', import.meta.url), 'utf8')
  .split('<script setup>')[1].split('</script>')[0].replace(/^import .*$/gm, '')

function analysis(get) {
  let dispose
  const state = vm.runInNewContext(`${script}\n;({ load, summary, loading, loadError, viewHint, viewTitle })`, {
    ref: value => ({ value }), computed: fn => ({ get value() { return fn() } }),
    onMounted() {}, onUnmounted: callback => { dispose = callback }, api: { get }, createRequestScope,
    document: { hidden: false, removeEventListener() {} }, clearInterval() {},
  })
  return { state, dispose: () => dispose() }
}

test('GPU analysis ignores old failures and exposes confirmed/candidate semantics', async () => {
  let reject
  const old = new Promise((_ok, fail) => { reject = fail })
  let calls = 0
  const { state } = analysis(() => calls++ === 0 ? old : Promise.resolve({ data: { total_gpus: 8, gpus: [] } }))
  const first = state.load()
  await state.load()
  reject(new Error('obsolete error'))
  await first
  assert.equal(state.summary.value.total_gpus, 8)
  assert.equal(state.loadError.value, '')
  assert.equal(state.loading.value, false)
  assert.match(state.viewTitle.value, /已确认与疑似/)
  assert.match(state.viewHint.value, /不计入/)
})

test('GPU analysis preserves data after current errors and invalidates on unmount', async () => {
  let fail = false
  const { state, dispose } = analysis(() => fail ? Promise.reject(new Error('current')) : Promise.resolve({ data: { total_gpus: 8 } }))
  await state.load()
  fail = true
  await state.load()
  assert.equal(state.summary.value.total_gpus, 8)
  assert.match(state.loadError.value, /current/)
  dispose()
  await state.load()
  assert.equal(state.summary.value.total_gpus, 8)
})
