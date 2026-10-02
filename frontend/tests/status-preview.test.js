import assert from 'node:assert/strict'
import test from 'node:test'
import { openStatusPreview, STATUS_PREVIEW_STORAGE_PREFIX } from '../src/status-preview.js'

test('opens an isolated draft preview without saving or publishing configuration', () => {
  const operations = []
  const preview = {
    sessionStorage: { setItem: (key, value) => operations.push(['storage', key, value]) },
    opener: 'original-opener',
    location: { replace: url => operations.push(['navigate', url]) },
    close: () => operations.push(['close']),
  }
  const browser = { open: (...args) => (operations.push(['open', ...args]), preview), crypto: { randomUUID: () => 'draft-id' } }
  const cfg = { title: 'Unsaved title', published: true, server_ids: [4] }
  assert.equal(openStatusPreview(cfg, browser), 'draft-id')
  assert.deepEqual(operations, [
    ['open', 'about:blank', '_blank'],
    ['storage', STATUS_PREVIEW_STORAGE_PREFIX + 'draft-id', JSON.stringify(cfg)],
    ['navigate', '/status?preview=1&draft=draft-id'],
  ])
  assert.equal(preview.opener, null)
  assert.deepEqual(cfg, { title: 'Unsaved title', published: true, server_ids: [4] })
})

test('reports popup blocking instead of silently doing nothing', () => {
  assert.throws(() => openStatusPreview({}, { open: () => null }), /阻止了预览窗口/)
})

test('closes blank preview when tab storage fails', () => {
  let closed = false
  const preview = { sessionStorage: { setItem: () => { throw new Error('storage unavailable') } },
    location: { replace: () => assert.fail('must not navigate without the draft') },
    close: () => { closed = true } }
  assert.throws(() => openStatusPreview({}, { open: () => preview }), /storage unavailable/)
  assert.equal(closed, true)
})
