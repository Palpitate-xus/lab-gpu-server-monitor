// Credentials are write-only: empty active fields preserve stored values on
// edit; inactive credentials must never be submitted as a usable fallback.
export function buildServerPayload(form, editing = false) {
  const payload = { ...form, tags: [...(form.tags || [])] }
  if (editing) {
    for (const field of ['username', 'bmc_password']) {
      if (!payload[field]) delete payload[field]
    }
  }
  if (payload.auth_type === 'password') {
    payload.private_key = ''
    payload.passphrase = ''
    if (editing && !payload.password) delete payload.password
  } else {
    payload.password = ''
    if (editing && !payload.private_key) delete payload.private_key
    // Empty passphrase explicitly unlocks a newly supplied unencrypted key;
    // otherwise a blank edit keeps the old key's passphrase.
    if (editing && !payload.private_key && !payload.passphrase) delete payload.passphrase
  }
  return payload
}
