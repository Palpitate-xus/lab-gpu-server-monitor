export const STATUS_PREVIEW_STORAGE_PREFIX = 'gpumon:status-preview:'

// The draft stays in this new tab, not in shared localStorage or the server's
// published configuration. Open synchronously to avoid popup blockers.
export function openStatusPreview(config, browserWindow = window) {
  const preview = browserWindow.open('about:blank', '_blank')
  if (!preview) throw new Error('浏览器阻止了预览窗口，请允许本站弹出窗口后重试')
  try {
    const token = browserWindow.crypto?.randomUUID?.()
      || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
    preview.sessionStorage.setItem(STATUS_PREVIEW_STORAGE_PREFIX + token, JSON.stringify(config))
    preview.opener = null
    preview.location.replace(`/status?preview=1&draft=${encodeURIComponent(token)}`)
    return token
  } catch (error) {
    preview.close()
    throw error
  }
}
