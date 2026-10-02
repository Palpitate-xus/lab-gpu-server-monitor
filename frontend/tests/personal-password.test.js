import assert from 'node:assert/strict'
import test from 'node:test'
import { deferred, pageScript } from '../test-support/page-script.js'

function passwordPage(api, errors = []) {
  return pageScript('PersonalPassword', {
    api,
    AntApp: { useApp: () => ({ message: { success() {}, error: text => errors.push(text) } }) },
  }, 'submit, saving, form, rules')
}

test('password submit is locked, uses the existing self-service API and clears secrets on success', async () => {
  const pending = deferred()
  const calls = []
  const view = passwordPage({ post: (url, body) => { calls.push({ url, body }); return pending.promise } })
  Object.assign(view.form, { old_password: 'old-test-password', new_password: 'new-test-password', confirm: 'new-test-password' })
  const first = view.submit()
  const repeated = view.submit()
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, '/users/change-password')
  assert.equal('confirm' in calls[0].body, false)
  assert.equal(view.saving.value, true)
  pending.resolve({ data: { ok: true } })
  await Promise.all([first, repeated])
  assert.equal(view.form.old_password, '')
  assert.equal(view.form.new_password, '')
  assert.equal(view.form.confirm, '')
  assert.equal(view.saving.value, false)
})

test('failed password change allows retry and mismatched confirmation is invalid', async () => {
  const errors = []
  const view = passwordPage({ post: async () => { throw { friendlyMessage: 'Old password is incorrect' } } }, errors)
  Object.assign(view.form, { old_password: 'old-test-password', new_password: 'new-test-password', confirm: 'different-password' })
  await assert.rejects(view.rules.confirm[1].validator({}, view.form.confirm))
  await view.submit()
  assert.equal(view.saving.value, false)
  assert.equal(view.form.old_password, 'old-test-password')
  assert.deepEqual(errors, ['Old password is incorrect'])
})
