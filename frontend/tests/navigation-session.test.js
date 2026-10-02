import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { pageScript, deferred } from '../test-support/page-script.js'

test('public status skips authorization bootstrap, protected routes wait for verified state', async () => {
  const pending = deferred()
  let bootstrapCalls = 0, user = { role: 'admin', mfa_required: true }
  const source = readFileSync(new URL('../src/router.js', import.meta.url), 'utf8')
    .replace(/^import .*$/gm, '').replace('export default router', '')
  let guard
  const context = {
    createWebHistory: () => ({}), createRouter: () => ({ beforeEach: fn => { guard = fn } }),
    ensureSessionReady: () => { bootstrapCalls++; return pending.promise },
    getSession: () => ({ user }),
  }
  vm.createContext(context)
  vm.runInContext(source, context)
  assert.equal(await guard({ name: 'status', meta: { public: true } }), true)
  assert.equal(bootstrapCalls, 0)
  let finished = false
  const protectedNavigation = guard({ name: 'settings', fullPath: '/settings', meta: { admin: true } })
  protectedNavigation.then(() => { finished = true })
  await Promise.resolve()
  assert.equal(finished, false)
  user = null // Bootstrap invalidates the cached, unverified administrator.
  pending.resolve()
  assert.deepEqual(JSON.parse(JSON.stringify(await protectedNavigation)), { name: 'login', query: { redirect: '/settings' } })
  user = { role: 'viewer' }
  assert.equal(await guard({ name: 'personal-password', fullPath: '/account/password', meta: {} }), true)
  assert.equal((await guard({ name: 'mfa-setup', fullPath: '/mfa-setup', meta: {} })).name, 'cockpit')
  user = { role: 'admin', mfa_required: true, mfa_enrolled: false }
  assert.equal(await guard({ name: 'mfa-setup', fullPath: '/mfa-setup', meta: {} }), true)
})

test('session bootstrap is shared by overlapping navigations', async () => {
  const pending = deferred()
  let calls = 0
  const source = readFileSync(new URL('../src/session-bootstrap.js', import.meta.url), 'utf8')
    .replace(/^import .*$/gm, '').replace('export function', 'function')
  const context = { bootstrapSession: () => { calls++; return pending.promise } }
  vm.createContext(context)
  vm.runInContext(`${source}; globalThis.run = ensureSessionReady`, context)
  const first = context.run()
  const second = context.run()
  assert.equal(first, second)
  assert.equal(calls, 1)
  pending.resolve()
  await Promise.all([first, second])
})

test('failed logout keeps the session and confirmation can be retried', async () => {
  let cleared = 0, navigated = 0, fail = true
  const view = pageScript('Layout', {
    useRoute: () => ({ path: '/cockpit', meta: {} }),
    useRouter: () => ({ push: async () => { navigated++ } }),
    getSession: () => ({ user: { username: 'viewer', role: 'viewer' } }),
    clearSession: () => { cleared++ },
    api: { post: async () => { if (fail) throw new Error('network failure') } },
    AntApp: { useApp: () => ({ message: { error() {} } }) },
  }, 'onUserMenuClick, logout, logoutOpen, logoutSaving')
  view.onUserMenuClick({ key: 'logout' })
  await view.logout()
  assert.equal(cleared, 0)
  assert.equal(navigated, 0)
  assert.equal(view.logoutOpen.value, true)
  assert.equal(view.logoutSaving.value, false)
  fail = false
  await view.logout()
  assert.equal(cleared, 1)
  assert.equal(navigated, 1)
  assert.equal(view.logoutOpen.value, false)
})
