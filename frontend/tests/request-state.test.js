import assert from 'node:assert/strict'
import test from 'node:test'
import { compareGpuIdentity, createLatestRequest } from '../src/requestState.js'

const deferred = () => {
  let resolve, reject
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail })
  return { promise, resolve, reject }
}

test('superseded successful and failed responses cannot replace latest data', async () => {
  for (const failure of [false, true]) {
    const latest = createLatestRequest()
    const old = deferred()
    let value = null
    const pending = latest(old.promise, result => { value = result })
    await latest(Promise.resolve('current'), result => { value = result })
    if (failure) old.reject(new Error('obsolete error'))
    else old.resolve('obsolete data')
    assert.equal(await pending, undefined)
    assert.equal(value, 'current')
  }
})

test('current failures still propagate and invalidated requests cannot apply', async () => {
  const latest = createLatestRequest()
  await assert.rejects(latest(Promise.reject(new Error('current error'))), /current error/)
  const pending = deferred()
  let applied = false
  const request = latest(pending.promise, () => { applied = true })
  latest.invalidate()
  pending.resolve('result')
  await request
  assert.equal(applied, false)
})

test('GPU identity sort uses numeric server names and numeric GPU indices', () => {
  const rows = [
    { server_name: 'gpu-10', server_id: 10, index: 0 },
    { server_name: 'gpu-2', server_id: 2, index: 10 },
    { server_name: 'gpu-2', server_id: 2, index: 2 },
  ]
  assert.deepEqual(rows.sort(compareGpuIdentity).map(row => [row.server_id, row.index]), [[2, 2], [2, 10], [10, 0]])
})
