<template>
  <div class="status-page" :class="themeClass">
    <div class="sp-container">
      <!-- header -->
      <header class="sp-header">
        <div class="sp-live-dot" :class="data?.overall?.all_operational ? 'ok' : 'bad'"></div>
        <h1>{{ data?.title || '服务状态' }}</h1>
        <p class="sp-desc">{{ data?.description }}</p>
      </header>

      <!-- unpublished -->
      <div v-if="loaded && !data?.published" class="sp-card sp-empty">
        此状态页未发布。管理员可在「系统设置 → 状态页」中开启。
      </div>

      <!-- overall banner -->
      <div v-if="data?.published" class="sp-card sp-banner" :class="data.overall?.all_operational ? 'ok' : 'bad'">
        <template v-if="data.overall?.all_operational">
          <span class="sp-banner-icon">✓</span> 全部系统正常运行 · {{ data.overall.servers_online }}/{{ data.overall.servers_total }} 台在线
        </template>
        <template v-else>
          <span class="sp-banner-icon">!</span> 部分系统异常 · {{ data.overall.servers_online }}/{{ data.overall.servers_total }} 台在线
        </template>
      </div>

      <!-- server rows -->
      <div v-if="data?.published" class="sp-list">
        <div v-for="s in data.servers" :key="s.id" class="sp-card sp-row">
          <div class="sp-row-head">
            <div class="sp-row-name">
              <span class="sp-dot" :class="s.online ? 'ok' : 'bad'"></span>
              <b>{{ s.name }}</b>
              <span v-if="s.server_type === 'cpu'" class="sp-tag">CPU</span>
              <span v-else class="sp-tag gpu">GPU</span>
            </div>
            <div class="sp-row-meta">
              <span v-if="data.show_latency && s.online" class="sp-latency">{{ s.avg_latency_ms }} ms</span>
              <span class="sp-uptime">{{ s.uptime_30d == null ? '—' : s.uptime_30d + '%' }}</span>
              <span class="sp-status-label" :class="s.online ? 'ok' : 'bad'">{{ s.online ? '正常' : '离线' }}</span>
            </div>
          </div>

          <!-- GPU utilization -->
          <div v-if="data.show_gpu && s.gpus?.length" class="sp-gpus">
            <div v-for="g in s.gpus" :key="g.index" class="sp-gpu" :class="gpuClass(g.util)">
              <span class="sp-gpu-label">GPU{{ g.index }}</span>
              <div class="sp-gpu-bar">
                <div class="sp-gpu-fill" :style="{ width: Math.min(g.util, 100) + '%' }"></div>
              </div>
              <span class="sp-gpu-val">{{ g.util }}%</span>
              <span class="sp-gpu-mem">{{ g.mem_pct }}% 显存</span>
            </div>
          </div>

          <!-- uptime bars -->
          <div class="sp-bars">
            <el-tooltip v-for="(d, i) in s.history" :key="i" :disabled="!d.uptime" placement="top">
              <template #content>
                {{ d.date }}：<template v-if="d.uptime == null">无数据</template>
                <template v-else>{{ d.uptime }}% 可用（{{ d.n }} 次探测）</template>
              </template>
              <div class="sp-bar" :class="barClass(d)"></div>
            </el-tooltip>
          </div>
          <div class="sp-bars-axis">
            <span>{{ axisLabel(s.history, 'first') }}</span>
            <span>{{ axisLabel(s.history, 'mid') }}</span>
            <span>今天</span>
          </div>
        </div>
      </div>

      <footer class="sp-footer" v-if="data?.footer">{{ data.footer }}</footer>
      <footer class="sp-footer sub" v-if="data?.generated_at">
        数据实时来自 SSH 探测 · 更新于 {{ fmtTime(data.generated_at) }}
      </footer>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import axios from 'axios'
import { fmtTime } from '../format'

const data = ref(null)
const loaded = ref(false)
let timer = null

const themeClass = computed(() => {
  const t = data.value?.theme || 'auto'
  if (t === 'dark') return 'sp-dark'
  if (t === 'light') return 'sp-light'
  // auto: follow the app-level html.dark class if present
  return document.documentElement.classList.contains('dark') ? 'sp-dark' : 'sp-light'
})

function gpuClass(util) {
  if (util >= 90) return 'hot'
  if (util >= 50) return 'busy'
  return 'idle'
}

function barClass(d) {
  if (d.uptime == null) return 'none'
  if (d.uptime >= 99.5) return 'ok'
  if (d.uptime >= 90) return 'warn'
  return 'bad'
}

function axisLabel(history, pos) {
  if (!history?.length) return ''
  const idx = pos === 'first' ? 0 : Math.floor(history.length / 2)
  return history[idx]?.date?.slice(5) || ''
}

async function load() {
  try {
    // public endpoint — plain axios, no auth header
    const { data: d } = await axios.get('/api/status-public')
    data.value = d
  } catch {
    data.value = null
  } finally {
    loaded.value = true
  }
}

onMounted(() => {
  load()
  timer = setInterval(load, 60000)
})
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.status-page {
  min-height: 100vh;
  font-family: -apple-system, 'PingFang SC', 'Segoe UI', Roboto, sans-serif;
}
.sp-light { background: #f5f7fb; color: #1f2d3d; }
.sp-dark { background: #0c1425; color: #dce7f5; }

.sp-container { max-width: 860px; margin: 0 auto; padding: 48px 20px 40px; }

.sp-header { text-align: center; margin-bottom: 28px; }
.sp-header h1 { font-size: 26px; margin: 10px 0 6px; }
.sp-desc { opacity: .65; font-size: 14px; margin: 0; }
.sp-live-dot {
  width: 14px; height: 14px; border-radius: 50%; display: inline-block;
  animation: sp-pulse 2s infinite;
}
.sp-live-dot.ok { background: #10b981; box-shadow: 0 0 0 4px rgba(16,185,129,.2); }
.sp-live-dot.bad { background: #ef4444; box-shadow: 0 0 0 4px rgba(239,68,68,.2); }
@keyframes sp-pulse {
  0%,100% { box-shadow: 0 0 0 4px rgba(16,185,129,.25); }
  50% { box-shadow: 0 0 0 8px rgba(16,185,129,.08); }
}

.sp-card {
  border-radius: 10px;
  padding: 16px 20px;
  margin-bottom: 12px;
}
.sp-light .sp-card { background: #fff; border: 1px solid #e3e9f2; }
.sp-dark .sp-card { background: #131f36; border: 1px solid #1e2d47; }

.sp-empty { text-align: center; opacity: .7; padding: 40px; }

.sp-banner { display: flex; align-items: center; gap: 10px; font-size: 15px; font-weight: 600; }
.sp-banner.ok { border-left: 4px solid #10b981; }
.sp-banner.bad { border-left: 4px solid #ef4444; }
.sp-banner-icon {
  width: 22px; height: 22px; border-radius: 50%; color: #fff;
  display: inline-flex; align-items: center; justify-content: center; font-size: 13px;
}
.sp-banner.ok .sp-banner-icon { background: #10b981; }
.sp-banner.bad .sp-banner-icon { background: #ef4444; }

.sp-row-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.sp-row-name { display: flex; align-items: center; gap: 8px; font-size: 15px; }
.sp-dot { width: 9px; height: 9px; border-radius: 50%; }
.sp-dot.ok { background: #10b981; }
.sp-dot.bad { background: #ef4444; }
.sp-tag {
  font-size: 10px; padding: 1px 6px; border-radius: 8px; border: 1px solid currentColor;
  opacity: .55; font-weight: 600; letter-spacing: .05em;
}
.sp-tag.gpu { color: #0891b2; }
.sp-row-meta { display: flex; align-items: center; gap: 14px; font-size: 13px; }
.sp-latency { opacity: .6; font-variant-numeric: tabular-nums; }
.sp-uptime { font-weight: 600; font-variant-numeric: tabular-nums; }
.sp-status-label.ok { color: #10b981; font-weight: 600; }
.sp-status-label.bad { color: #ef4444; font-weight: 600; }

.sp-bars { display: flex; gap: 3px; align-items: flex-end; height: 34px; }
.sp-bar { flex: 1; min-width: 3px; height: 100%; border-radius: 2px; cursor: default; }
.sp-bar.ok { background: #10b981; }
.sp-bar.warn { background: #f59e0b; }
.sp-bar.bad { background: #ef4444; }
.sp-bar.none { background: currentColor; opacity: .12; }
.sp-bars-axis {
  display: flex; justify-content: space-between; font-size: 11px; opacity: .45; margin-top: 6px;
  font-variant-numeric: tabular-nums;
}

.sp-footer { text-align: center; font-size: 12px; opacity: .5; margin-top: 22px; }
.sp-footer.sub { margin-top: 6px; }

@media (max-width: 560px) {
  .sp-container { padding: 28px 12px 24px; }
  .sp-row-meta { gap: 8px; }
  .sp-latency { display: none; }
}
</style>

.sp-gpus { display: flex; flex-direction: column; gap: 5px; margin-bottom: 12px; }
.sp-gpu { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.sp-gpu-label { width: 44px; opacity: .65; font-variant-numeric: tabular-nums; flex: none; }
.sp-gpu-bar { flex: 1; height: 6px; border-radius: 3px; background: currentColor; opacity: .9; overflow: hidden; position: relative; }
.sp-gpu-bar::before { content: ''; position: absolute; inset: 0; opacity: .12; background: currentColor; }
.sp-gpu-fill { height: 100%; border-radius: 3px; transition: width .5s; }
.sp-gpu.idle .sp-gpu-fill { background: #10b981; }
.sp-gpu.busy .sp-gpu-fill { background: #0891b2; }
.sp-gpu.hot .sp-gpu-fill { background: #f59e0b; }
.sp-gpu.idle .sp-gpu-bar { color: #10b981; }
.sp-gpu.busy .sp-gpu-bar { color: #0891b2; }
.sp-gpu.hot .sp-gpu-bar { color: #f59e0b; }
.sp-gpu-val { width: 38px; text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; flex: none; }
.sp-gpu-mem { width: 64px; opacity: .55; font-variant-numeric: tabular-nums; flex: none; font-size: 11px; }
@media (max-width: 560px) { .sp-gpu-mem { display: none; } }
