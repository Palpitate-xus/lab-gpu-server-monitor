import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { extname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const sourceRoot = fileURLToPath(new URL('../src', import.meta.url))
const frontendRoot = fileURLToPath(new URL('..', import.meta.url))

function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) return sourceFiles(path)
    return ['.vue', '.js', '.css'].includes(extname(entry.name)) ? [path] : []
  })
}

function componentName(tag) {
  return `Ant${tag.split('-').map(part => part[0].toUpperCase() + part.slice(1)).join('')}`
}

test('registers every Ant Design component used by templates', () => {
  const source = sourceFiles(sourceRoot).map(path => readFileSync(path, 'utf8')).join('\n')
  const tags = new Set([...source.matchAll(/<a-([a-z0-9-]+)/g)].map(match => match[1]))
  const main = readFileSync(join(sourceRoot, 'main.js'), 'utf8')
  const providers = {
    'button-group': 'AntButton',
    'collapse-panel': 'AntCollapse',
    'config-provider': 'ConfigProvider',
    'descriptions-item': 'AntDescriptions',
    'form-item': 'AntForm',
    'input-password': 'AntInput',
    'layout-content': 'AntLayout',
    'layout-header': 'AntLayout',
    'layout-sider': 'AntLayout',
    'menu-item': 'AntMenu',
    'radio-button': 'AntRadio',
    'radio-group': 'AntRadio',
    'select-option': 'AntSelect',
    'tab-pane': 'AntTabs',
    'table-column': 'AntTable',
    textarea: 'AntInput',
  }

  for (const tag of tags) {
    const name = providers[tag] || componentName(tag)
    assert.match(main, new RegExp(`app\\.use\\(${name}\\)`), `${tag} is not registered by ${name}`)
  }
})

test('contains no Element Plus compatibility layer', () => {
  const source = sourceFiles(sourceRoot).map(path => readFileSync(path, 'utf8')).join('\n')
  const packageJson = readFileSync(join(frontendRoot, 'package.json'), 'utf8')

  assert.doesNotMatch(source, /element-plus|@element-plus|<\/?el-|\bElMessage(?:Box)?\b|v-loading|\.el-/)
  assert.doesNotMatch(packageJson, /element-plus|@element-plus/)
})

test('starts the router only after session bootstrap completes', () => {
  const main = readFileSync(join(sourceRoot, 'main.js'), 'utf8')
  assert.match(
    main,
    /bootstrapSession\(\)\.finally\(\(\) => \{\s*app\.use\(router\)\s*app\.mount\('#app'\)\s*\}\)/,
  )
})
