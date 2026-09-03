import assert from 'node:assert/strict'
import test from 'node:test'

import { csvCell, csvRow } from '../src/csv.js'

test('quotes RFC 4180 special characters', () => {
  assert.equal(csvCell('a,"b"\nc'), '"a,""b""\nc"')
  assert.equal(csvRow(['a', 'b']), '"a","b"')
})

test('neutralizes spreadsheet formula prefixes', () => {
  for (const value of ['=1+1', '+cmd', '-2+3', '@SUM(A1)', '  =HYPERLINK("x")']) {
    assert.ok(csvCell(value).startsWith('"\''), value)
  }
})
