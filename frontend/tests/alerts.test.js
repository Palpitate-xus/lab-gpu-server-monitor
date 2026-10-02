import assert from 'node:assert/strict'
import test from 'node:test'
import { pageScript, deferred } from '../test-support/page-script.js'

function alerts(api) {
  return pageScript('Alerts', { api, AntApp: { useApp: () => ({ message: { success() {}, error() {} } }) } },
    'loadEvents, loadRules, events, eventFilter, page, loadingEvents, eventsError, rulesError, pollError, hasMore, rules2, ack, eventBusy')
}

test('alert filter drops older success and failure without ending current loading', async () => {
  const queue = []
  const view = alerts({ get: () => { const item = deferred(); queue.push(item); return item.promise } })
  const old = view.loadEvents()
  view.eventFilter.value = true
  const latest = view.loadEvents()
  queue[0].reject(new Error('obsolete failure'))
  await old
  assert.equal(view.loadingEvents.value, true)
  assert.equal(view.eventsError.value, '')
  queue[1].resolve({ data: [{ id: 2, recovered_at: null }] })
  await latest
  assert.equal(view.events.value[0].id, 2)
  assert.equal(view.loadingEvents.value, false)

  const older = view.loadEvents()
  view.eventFilter.value = false
  const newer = view.loadEvents()
  queue[3].resolve({ data: [{ id: 4 }] })
  await newer
  queue[2].resolve({ data: [{ id: 3 }] })
  await older
  assert.equal(view.events.value[0].id, 4)
})

test('a successful events request cannot clear a failed rules request', async () => {
  const view = alerts({ get: async url => {
    if (url === '/alerts/rules') throw { friendlyMessage: 'rules unavailable' }
    return { data: [] }
  } })
  await view.loadRules()
  await view.loadEvents()
  assert.equal(view.rulesError.value, 'rules unavailable')
  assert.match(view.pollError.value, /rules unavailable/)
  assert.equal(view.eventsError.value, '')
})

test('alert event actions lock by row without blocking other rows', async () => {
  const queue = []
  const view = alerts({
    post: () => { const item = deferred(); queue.push(item); return item.promise },
    get: async () => ({ data: [] }),
  })
  const first = view.ack({ id: 1 })
  const duplicate = view.ack({ id: 1 })
  const other = view.ack({ id: 2 })
  assert.equal(queue.length, 2)
  assert.equal(view.eventBusy.size, 2)
  queue.forEach(item => item.resolve({ data: {} }))
  await Promise.all([first, duplicate, other])
  assert.equal(view.eventBusy.size, 0)
})

test('alert numeric form fields reject cleared threshold and fractional duration', async () => {
  const view = alerts({})
  await assert.rejects(view.rules2.threshold[0].validator({}, null))
  await assert.rejects(view.rules2.duration_minutes[0].validator({}, 1.5))
  await assert.rejects(view.rules2.duration_minutes[0].validator({}, null))
  await view.rules2.duration_minutes[0].validator({}, 0)
  await view.rules2.threshold[0].validator({}, 0)
})
