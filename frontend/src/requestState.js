/** Ignore both successful and failed responses from superseded requests. */
export function createLatestRequest() {
  let sequence = 0
  const applyLatest = async (promise, apply) => {
    const request = ++sequence
    let result
    try {
      result = await promise
    } catch (error) {
      if (request !== sequence) return undefined
      throw error
    }
    if (request !== sequence) return undefined
    return apply ? apply(result) : result
  }
  applyLatest.invalidate = () => { sequence++ }
  return applyLatest
}

export function compareGpuIdentity(a, b) {
  return String(a.server_name || '').localeCompare(String(b.server_name || ''), undefined, { numeric: true })
    || Number(a.server_id || 0) - Number(b.server_id || 0)
    || Number(a.index) - Number(b.index)
}

/** A per-view request lifetime: cancel superseded work and guard all writes. */
export function createRequestScope() {
  let sequence = 0
  let controller
  let disposed = false
  return {
    begin() {
      controller?.abort()
      const request = ++sequence
      controller = new AbortController()
      if (disposed) controller.abort()
      return { signal: controller.signal, current: () => !disposed && request === sequence }
    },
    dispose() {
      disposed = true
      sequence++
      controller?.abort()
    },
  }
}
