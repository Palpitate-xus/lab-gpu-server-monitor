import assert from 'node:assert/strict'
import test from 'node:test'
import { buildServerPayload } from '../src/server-form.js'

const base = { username: '', password: '', private_key: '', passphrase: '', bmc_password: '', tags: ['lab'] }

test('password edit preserves blank active credentials but removes stale keys', () => {
  const payload = buildServerPayload({ ...base, auth_type: 'password', private_key: 'old-key', passphrase: 'old-passphrase' }, true)
  assert.equal('username' in payload, false)
  assert.equal('password' in payload, false)
  assert.equal('bmc_password' in payload, false)
  assert.equal(payload.private_key, '')
  assert.equal(payload.passphrase, '')
})

test('key edit preserves blank key and passphrase and clears the password fallback', () => {
  const payload = buildServerPayload({ ...base, auth_type: 'key', password: 'stale-password' }, true)
  assert.equal('private_key' in payload, false)
  assert.equal('passphrase' in payload, false)
  assert.equal(payload.password, '')
})

test('replacement unencrypted key explicitly clears its previous passphrase', () => {
  const payload = buildServerPayload({ ...base, auth_type: 'key', private_key: 'new-key' }, true)
  assert.equal(payload.private_key, 'new-key')
  assert.equal(payload.passphrase, '')
})

test('payload snapshots tags and leaves draft inputs untouched', () => {
  const form = { ...base, auth_type: 'key', password: 'draft-password' }
  const payload = buildServerPayload(form, true)
  payload.tags.push('other')
  assert.equal(form.password, 'draft-password')
  assert.deepEqual(form.tags, ['lab'])
})
