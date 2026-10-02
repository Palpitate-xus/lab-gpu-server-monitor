import assert from 'node:assert/strict'
import test from 'node:test'
import { pageScript, ref } from '../test-support/page-script.js'

test('status auto theme is reactive and stale snapshots are not healthy', () => {
  const resolved = ref('light')
  const view = pageScript('StatusPage', {
    useRoute: () => ({ query: {} }), useTheme: () => ({ resolved }),
    antTheme: { darkAlgorithm: 'dark', defaultAlgorithm: 'light' },
  }, 'selectedTheme, data, overallState, stateLabel')
  view.data.value = { theme: 'auto', servers: [{ state: 'stale', online: false }] }
  assert.equal(view.selectedTheme.value, 'light')
  resolved.value = 'dark'
  assert.equal(view.selectedTheme.value, 'dark')
  assert.equal(view.overallState.value, 'unknown')
  assert.equal(view.stateLabel({ state: 'stale' }), '探测已过期')
  view.data.value = { theme: 'light', servers: [] }
  assert.equal(view.selectedTheme.value, 'light')
  assert.equal(view.overallState.value, 'unknown')
})

test('status draft preview POSTs the session draft without saving configuration', async () => {
  const calls = []
  const view = pageScript('StatusPage', {
    useRoute: () => ({ query: { preview: '1', draft: 'test-draft' } }),
    useTheme: () => ({ resolved: ref('light') }), antTheme: {},
    sessionStorage: { getItem: key => key === 'gpumon:status-preview:test-draft' ? JSON.stringify({ title: 'Unsaved' }) : null },
    api: { post: async (url, body) => { calls.push({ url, body }); return { data: { title: body.title } } } },
  }, 'load, data')
  await view.load()
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [{ url: '/status-page/preview', body: { title: 'Unsaved' } }])
  assert.equal(view.data.value.title, 'Unsaved')
})

test('missing draft does not fall back to a saved or published configuration', async () => {
  let called = false
  const view = pageScript('StatusPage', {
    useRoute: () => ({ query: { preview: '1', draft: 'missing' } }),
    useTheme: () => ({ resolved: ref('light') }), antTheme: {},
    sessionStorage: { getItem: () => null },
    api: { post: async () => { called = true } }, axios: { get: async () => { called = true } },
  }, 'load, data, loadError')
  await view.load()
  assert.equal(called, false)
  assert.equal(view.data.value, null)
  assert.match(view.loadError.value, /预览草稿不存在/)
})
