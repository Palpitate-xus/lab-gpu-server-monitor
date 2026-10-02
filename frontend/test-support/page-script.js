import { readFileSync } from 'node:fs'
import vm from 'node:vm'

// Exercise each page's real script, with API calls isolated from any deployment.
export const ref = value => ({ value })
export const computed = getter => ({ get value() { return getter() } })
export const deferred = () => {
  let resolve, reject
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail })
  return { promise, resolve, reject }
}

export function pageScript(name, bindings, exports) {
  const source = readFileSync(new URL(`../src/views/${name}.vue`, import.meta.url), 'utf8')
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1]
    .replace(/^import[\s\S]*?from ['"][^'"]+['"]\s*$/gm, '')
  const context = {
    ref, computed, reactive: value => value,
    onMounted: () => {}, onUnmounted: () => {}, defineExpose: () => {},
    document: { hidden: false },
    isAdminSession: () => true,
    fmtTime: value => value,
    ...bindings,
  }
  vm.createContext(context)
  vm.runInContext(`${script}\nglobalThis.page = { ${exports} }`, context)
  return context.page
}
