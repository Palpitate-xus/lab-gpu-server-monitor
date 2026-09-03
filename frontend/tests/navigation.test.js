import assert from 'node:assert/strict'
import test from 'node:test'

import { safeLocalRedirect } from '../src/navigation.js'

const origin = 'https://gpu-monitor.example.com'

test('keeps only normalized same-origin application paths', () => {
  assert.equal(safeLocalRedirect('/servers/1?tab=gpu#top', origin), '/servers/1?tab=gpu#top')
  assert.equal(safeLocalRedirect('//evil.example/path', origin), '/cockpit')
  assert.equal(safeLocalRedirect('/\\evil.example/path', origin), '/cockpit')
  assert.equal(safeLocalRedirect('https://evil.example/path', origin), '/cockpit')
  assert.equal(safeLocalRedirect('/ok\nLocation: https://evil.example', origin), '/cockpit')
})
