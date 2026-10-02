import assert from 'node:assert/strict'
import test from 'node:test'
import { fmtTime, parseTime } from '../src/format.js'

test('UTC datetime strings with missing database offsets match explicit UTC', () => {
  const instant = Date.parse('2026-10-02T12:00:00.123Z')
  assert.equal(parseTime('2026-10-02T12:00:00.123').getTime(), instant)
  assert.equal(parseTime('2026-10-02 12:00:00.123').getTime(), instant)
  assert.equal(parseTime('2026-10-02T20:00:00.123+08:00').getTime(), instant)
  assert.equal(parseTime(instant).getTime(), instant)
})

test('time formatting localizes UTC samples consistently in non-UTC browsers', () => {
  const previousTimezone = process.env.TZ
  try {
    process.env.TZ = 'Asia/Shanghai'
    assert.equal(fmtTime('2026-10-02T12:00:00'), '2026-10-02 20:00:00')
    assert.equal(fmtTime('2026-10-02T12:00:00Z'), '2026-10-02 20:00:00')
    assert.equal(fmtTime(null), '—')
    assert.equal(fmtTime('invalid'), 'invalid')
  } finally {
    if (previousTimezone === undefined) delete process.env.TZ
    else process.env.TZ = previousTimezone
  }
})
