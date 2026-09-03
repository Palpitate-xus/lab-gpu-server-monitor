export function safeLocalRedirect(value, origin = globalThis.location?.origin) {
  const fallback = '/cockpit'
  if (
    typeof value !== 'string'
    || !origin
    || !value.startsWith('/')
    || value.startsWith('//')
    || value.includes('\\')
    || /[\u0000-\u001f\u007f]/.test(value)
  ) return fallback

  try {
    const base = new URL(origin)
    const target = new URL(value, base)
    if (target.origin !== base.origin || !target.pathname.startsWith('/')) return fallback
    return `${target.pathname}${target.search}${target.hash}`
  } catch {
    return fallback
  }
}
