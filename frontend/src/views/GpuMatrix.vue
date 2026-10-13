<template>
  <a-spin :spinning="loading && !matrix.length">
  <div class="gm-page">
    <a-alert v-if="error" type="error" show-icon :message="`数据加载失败：${error}`" />

    <!-- toolbar -->
    <a-card size="small" class="gm-toolbar-card">
    <div class="gm-toolbar">
      <div class="gm-toolbar-left">
        <b class="gm-title">GPU 资源矩阵</b>
        <a-tag>共 {{ gpus.length }} 卡</a-tag>
        <a-tag color="green">忙 {{ busyCount }}</a-tag>
        <a-tag color="orange">闲 {{ idleCount }}</a-tag>
        <a-tag v-if="offlineServers.length" color="red">
          离线 {{ offlineServers.length }} 台
        </a-tag>
      </div>
      <div class="gm-toolbar-right">
        <a-input v-model:value="search" placeholder="搜索 GPU 型号 / 服务器" allow-clear
          class="gm-filter gm-filter-search" aria-label="搜索 GPU 型号或服务器">
          <template #prefix><SearchOutlined /></template>
        </a-input>
        <a-select v-model:value="serverFilter" class="gm-filter gm-filter-server" placeholder="全部服务器" allow-clear aria-label="按服务器筛选">
          <a-select-option v-for="s in servers" :key="s.server_id" :value="s.server_id">{{ s.server_name }}</a-select-option>
        </a-select>
        <a-select v-model:value="stateFilter" class="gm-filter gm-filter-state" aria-label="按忙闲状态筛选">
          <a-select-option value="all">全部状态</a-select-option>
          <a-select-option value="busy">繁忙</a-select-option>
          <a-select-option value="idle">空闲</a-select-option>
        </a-select>
        <a-button-group class="gm-sort-group" aria-label="GPU 排序方式">
          <a-button v-for="opt in sortOptions" :key="opt.value"
            :type="sortBy === opt.value ? 'primary' : 'default'" @click="pickSort(opt.value)">
            {{ opt.label }}<span v-if="sortBy === opt.value" class="gm-dir">{{ asc ? ' ↑' : ' ↓' }}</span>
          </a-button>
        </a-button-group>
        <span v-if="lastUpdated" class="gm-updated">更新于 {{ lastUpdated.toLocaleTimeString('zh-CN') }}</span>
      </div>
    </div>
    </a-card>

    <!-- grid -->
    <div v-if="sorted.length" class="gm-grid">
      <a-card v-for="(g, i) in visibleGpus" :key="g.key" size="small" hoverable class="gm-card"
        :class="cellClass(g)" role="link" tabindex="0"
        :aria-label="`查看 ${g.server_name} 的 GPU ${g.index} 详情`"
        @click="$router.push(`/servers/${g.server_id}`)"
        @keydown.enter.prevent="$router.push(`/servers/${g.server_id}`)"
        @keydown.space.prevent="$router.push(`/servers/${g.server_id}`)">
        <div class="gm-rank">#{{ i + 1 }}</div>
        <div class="gm-head">
          <div class="gm-id">
            <b :title="g.server_name">{{ g.server_name }}</b>
            <span class="gm-idx">GPU {{ g.index }}</span>
          </div>
          <span class="gm-model" :title="g.name">{{ shortName(g.name) }}</span>
        </div>

        <div class="gm-util-row">
          <a-progress type="circle" :percent="g.utilization" :size="54" :stroke-color="ringColor(g.utilization)" />
          <div class="gm-metrics">
            <div class="gm-metric">
              <span class="gm-m-label">显存</span>
              <a-progress class="gm-memory-progress" :percent="Math.round(memPct(g))" :show-info="false" size="small" :stroke-color="barColor(memPct(g))" />
              <span class="gm-m-val mono">{{ fmtSizeMB(g.mem_used_mb) }}/{{ fmtSizeMB(g.mem_total_mb) }}</span>
            </div>
            <div class="gm-metric-cols">
              <span class="mono">{{ g.temperature || 0 }}°C</span>
              <span class="mono">{{ Math.round(g.power_draw || 0) }}W</span>
              <span class="gm-pstate" v-if="g.pstate">{{ g.pstate }}</span>
            </div>
          </div>
        </div>

        <div class="gm-procs" v-if="(g.processes || []).length">
          <span class="gm-proc" v-for="p in g.processes.slice(0, 2)" :key="p.pid" :title="p.command">
            {{ p.command }}
          </span>
        </div>
        <div class="gm-procs gm-procs-none" v-else>无占用进程</div>
      </a-card>
    </div>

    <a-empty v-else-if="!loading" description="没有符合条件的 GPU" />

    <div v-if="hiddenCount > 0" class="gm-more">
      <a-button size="small" @click="visibleCount += 200">显示更多（剩余 {{ hiddenCount }}）</a-button>
    </div>
  </div>
  </a-spin>
</template>

<script setup>
import { computed, ref } from 'vue'
import { SearchOutlined } from '@ant-design/icons-vue'
import api from '../api'
import { fmtSizeMB } from '../format'
import { usePoll } from '../composables'
import { compareGpuIdentity } from '../requestState'

const matrix = ref([])
const search = ref('')
const serverFilter = ref(null)
const stateFilter = ref('all')
const sortBy = ref('util')
const asc = ref(false)
const visibleCount = ref(200)

const sortOptions = [
  { value: 'util', label: '利用率' },
  { value: 'mem', label: '显存' },
  { value: 'temp', label: '温度' },
  { value: 'power', label: '功耗' },
  { value: 'server', label: '服务器' },
]

function pickSort(v) {
  if (sortBy.value === v) asc.value = !asc.value
  else { sortBy.value = v; asc.value = false }
}

const { loading, lastUpdated, error } = usePoll(async () => {
  const { data } = await api.get('/metrics/cluster-gpus')
  matrix.value = data || []
}, 30000)

const servers = computed(() => matrix.value)
const offlineServers = computed(() => matrix.value.filter(s => !s.online))

const gpus = computed(() => matrix.value.flatMap(s =>
  (s.gpus || []).map(g => ({ ...g, key: `${s.server_id}-${g.index}`, server_id: s.server_id, server_name: s.server_name, online: s.online }))
))

const memPct = g => (g.mem_total_mb ? (g.mem_used_mb / g.mem_total_mb) * 100 : 0)
const isBusy = g => g.utilization >= 30 || memPct(g) >= 30
const busyCount = computed(() => gpus.value.filter(isBusy).length)
const idleCount = computed(() => gpus.value.length - busyCount.value)

const sorted = computed(() => {
  let list = gpus.value
  if (serverFilter.value != null) list = list.filter(g => g.server_id === serverFilter.value)
  if (stateFilter.value === 'busy') list = list.filter(isBusy)
  if (stateFilter.value === 'idle') list = list.filter(g => !isBusy(g))
  if (search.value.trim()) {
    const q = search.value.trim().toLowerCase()
    list = list.filter(g =>
      (g.name || '').toLowerCase().includes(q) || (g.server_name || '').toLowerCase().includes(q))
  }
  const dir = asc.value ? 1 : -1
  if (sortBy.value === 'server') return [...list].sort((a, b) => compareGpuIdentity(a, b) * dir)
  const keyOf = {
    util: g => g.utilization,
    mem: g => memPct(g),
    temp: g => g.temperature || 0,
    power: g => g.power_draw || 0,
    server: g => `${g.server_name}-${g.index}`,
  }[sortBy.value]
  return [...list].sort((a, b) => {
    const ka = keyOf(a), kb = keyOf(b)
    return (typeof ka === 'string' ? ka.localeCompare(kb) : ka - kb) * dir
  })
})

const visibleGpus = computed(() => sorted.value.slice(0, visibleCount.value))
const hiddenCount = computed(() => Math.max(0, sorted.value.length - visibleCount.value))

function shortName(n) {
  return (n || '').replace(/^NVIDIA\s+/, '').replace(/^GeForce\s+/, '')
}

function cellClass(g) {
  if (!g.online) return 'gm-offline'
  if (g.utilization >= 90 || memPct(g) >= 95) return 'gm-full'
  if (isBusy(g)) return 'gm-busy'
  return 'gm-idle'
}

function barColor(p) {
  if (p >= 90) return '#ff4d4f'
  if (p >= 70) return '#faad14'
  return '#52c41a'
}

function ringColor(u) {
  return u >= 90 ? '#ff4d4f' : u >= 30 ? '#1677ff' : '#52c41a'
}
</script>

<style scoped>
.gm-page { display: flex; flex-direction: column; gap: 16px; }

.gm-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  flex-wrap: wrap; gap: 10px;
}
.gm-toolbar-left, .gm-toolbar-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-width: 0; }
.gm-title { font-size: 15px; }
.gm-dir { font-weight: 700; }
.gm-updated { font-size: 12px; color: var(--csub); }
.gm-filter-search { width: 190px; }
.gm-filter-server { width: 150px; }
.gm-filter-state { width: 110px; }

.gm-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}

.gm-more { display: flex; justify-content: center; }

.gm-card {
  position: relative;
  cursor: pointer;
  transition: transform .15s;
}
.gm-card :deep(.ant-card-body) {
  padding: 14px 16px;
  display: flex; flex-direction: column; gap: 10px;
}
.gm-card:hover { transform: translateY(-2px); }
.gm-card:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--cprimary) 40%, transparent);
  outline-offset: 2px;
  transform: translateY(-2px);
}
.gm-idle  { border-left: 3px solid #52c41a; }
.gm-busy  { border-left: 3px solid #1677ff; }
.gm-full  { border-left: 3px solid #ff4d4f; }
.gm-offline { opacity: .55; border-left: 3px solid var(--csub); }

.gm-rank {
  position: absolute; top: 10px; right: 12px;
  font-size: 12px; color: var(--csub); font-variant-numeric: tabular-nums;
}

.gm-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; padding-right: 28px; }
.gm-id { min-width: 0; flex: 1; display: flex; align-items: baseline; gap: 6px; }
.gm-id b { min-width: 0; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gm-idx { flex: 0 0 auto; font-size: 11px; color: var(--csub); }
.gm-model {
  font-size: 11px; color: var(--csub); max-width: 110px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

.gm-util-row { display: flex; align-items: center; gap: 14px; }
.gm-metrics { flex: 1; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.gm-metric { display: flex; align-items: center; gap: 8px; font-size: 11px; }
.gm-m-label { color: var(--csub); flex-shrink: 0; }
.gm-m-val { color: var(--csub); white-space: nowrap; }
.gm-memory-progress { flex: 1; min-width: 40px; margin: 0; }
.gm-metric-cols { display: flex; gap: 12px; font-size: 12px; color: var(--csub); }
.gm-pstate { font-size: 10px; border: 1px solid var(--cborder); border-radius: 6px; padding: 0 5px; }

.gm-procs { display: flex; gap: 6px; flex-wrap: wrap; }
.gm-proc {
  font-size: 10px; color: var(--csub); background: var(--cpanel2);
  border-radius: 6px; padding: 2px 7px;
  max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.gm-procs-none { font-size: 10px; color: var(--csub); opacity: .7; }

.mono { font-variant-numeric: tabular-nums; }

@media (max-width: 768px) {
  .gm-toolbar { flex-direction: column; align-items: stretch; }
  .gm-toolbar-left { row-gap: 7px; }
  .gm-title { width: 100%; font-size: 16px; }
  .gm-toolbar-right {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 8px;
    width: 100%;
  }
  .gm-filter { width: 100%; min-width: 0; }
  .gm-filter-search { grid-column: 1 / -1; }
  .gm-sort-group {
    display: flex;
    grid-column: 1 / -1;
    max-width: 100%;
    overflow-x: auto;
    padding-bottom: 2px;
  }
  .gm-sort-group :deep(.ant-btn) { min-width: max-content; flex: 1; padding-inline: 10px; }
  .gm-updated { grid-column: 1 / -1; text-align: right; }
  .gm-grid { grid-template-columns: minmax(0, 1fr); }
  .gm-card :deep(.ant-card-body) { padding: 14px; }
}
</style>
