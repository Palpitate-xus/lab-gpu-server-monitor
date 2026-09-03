import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { extname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const sourceRoot = fileURLToPath(new URL('../src', import.meta.url))

function vueFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) return vueFiles(path)
    return extname(entry.name) === '.vue' ? [path] : []
  })
}

function componentName(tag) {
  return `El${tag.split('-').map(part => part[0].toUpperCase() + part.slice(1)).join('')}`
}

test('registers every Element Plus component used by templates', () => {
  const templates = vueFiles(sourceRoot).map(path => readFileSync(path, 'utf8')).join('\n')
  const tags = new Set([...templates.matchAll(/<el-([a-z0-9-]+)/g)].map(match => match[1]))
  const main = readFileSync(join(sourceRoot, 'main.js'), 'utf8')
  const registry = main.match(/for \(const component of \[([\s\S]*?)\]\)/)?.[1] || ''

  for (const tag of tags) {
    const name = componentName(tag)
    assert.match(registry, new RegExp(`\\b${name}\\b`), `${name} is not registered`)
  }
  if (templates.includes('v-loading')) assert.match(main, /app\.use\(ElLoading\)/)
})
