import { bootstrapSession } from './composables'

let pending

/** Validate cached display data once, before any protected route is rendered. */
export function ensureSessionReady() {
  pending ||= bootstrapSession()
  return pending
}
