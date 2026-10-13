import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import test from 'node:test'

const views = new URL('../src/views/', import.meta.url)
const files = readdirSync(views).filter(name => name.endsWith('.vue'))
const source = name => readFileSync(new URL(name, views), 'utf8')

test('responsive visibility is applied to Spin wrappers, not loading indicators', () => {
  for (const name of files) {
    for (const [tag] of source(name).matchAll(/<a-spin\b[^>]*>/g)) {
      assert.doesNotMatch(tag, /\sclass="[^"]*\b(?:mobile-only|desktop-only)\b/, name)
    }
  }
})

test('every responsive column declares a larger breakpoint instead of a span fallback', () => {
  for (const name of files) {
    for (const [tag] of source(name).matchAll(/<a-col\b[^>]*>/g)) {
      if (!tag.includes(':xs=')) continue
      assert.match(tag, /:(?:sm|md|lg|xl|xxl)=/, `${name}: ${tag}`)
      assert.doesNotMatch(tag, /:span=/, `${name}: xs must not permanently override a span fallback`)
    }
  }
})

test('shared alignment rules stretch native cards and constrain table links', () => {
  const css = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8')
  assert.match(css, /\.kpi-row > \.ant-col\s*\{[^}]*display: flex/)
  assert.match(css, /\.ant-table-cell \.server-link\s*\{[^}]*overflow: hidden/)
  assert.match(css, /\.mobile-data-card__title \.table-link\s*\{[^}]*overflow-wrap: anywhere/)
  for (const name of ['Dashboard.vue', 'GpuAnalysis.vue', 'Reports.vue', 'Users.vue', 'ServerDetail.vue']) {
    assert.match(source(name), /class="[^"]*kpi-row/, name)
  }
})

test('conditional unit controls have a real DOM visibility wrapper', () => {
  const cockpit = source('Cockpit.vue')
  assert.doesNotMatch(cockpit, /<RateUnitPicker[^>]*v-show/)
  assert.match(cockpit, /<span v-show="trendMetric === 'net'"><RateUnitPicker/)
  assert.match(cockpit, /<span v-show="trendMetric === 'disk'"><RateUnitPicker/)
})

test('empty optional filter values render native placeholders without changing filter state', () => {
  for (const [name, fields] of [['Reports.vue', ['tag']], ['Servers.vue', ['tagFilter', 'statusFilter']]]) {
    for (const field of fields) {
      assert.ok(source(name).includes(`:value="${field} || undefined" @update:value="${field} = $event"`), `${name}: ${field}`)
    }
  }
})
