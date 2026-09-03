<template>
  <div class="gm-page" v-loading="loading && !matrix.length">
    <el-alert v-if="error" type="error" :closable="false" show-icon style="margin-bottom:14px"
      :title="`数据加载失败：${error}`" />

    <!-- toolbar -->
    <div class="gm-toolbar cockpit-panel">
      <div class="gm-toolbar-left">
        <b class="gm-title">GPU 资源矩阵</b>
        <el-tag size="small" effect="plain">共 {{ gpus.length }} 卡</el-tag>
        <el-tag size="small" type="success" effect="plain">忙 {{ busyCount }}</el-tag>
        <el-tag size="small" type="warning" effect="plain">闲 {{ idleCount }}</el-tag>
        <el-tag size="small" type="danger" effect="plain" v-if="offlineServers.length">
          离线 {{ offlineServers.length }} 台
        </el-tag>
      </div>
      <div class="gm-toolbar-right">
        <el-input v-model="search" placeholder="搜索 GPU 型号 / 服务器" clearable size="small"
          class="gm-filter gm-filter-search" aria-label="搜索 GPU 型号或服务器" :prefix-icon="Search" />
        <el-select v-model="serverFilter" size="small" class="gm-filter gm-filter-server" placeholder="全部服务器" clearable aria-label="按服务器筛选">
          <el-option v-for="s in servers" :key="s.server_id" :value="s.server_id" :label="s.server_name" />
        </el-select>
        <el-select v-model="stateFilter" size="small" class="gm-filter gm-filter-state" aria-label="按忙闲状态筛选">
          <el-option value="all" label="全部状态" />
          <el-option value="busy" label="繁忙" />
          <el-option value="idle" label="空闲" />
        </el-select>
        <el-button-group size="small" class="gm-sort-group" aria-label="GPU 排序方式">
          <el-button v-for="opt in sortOptions" :key="opt.value"
            :type="sortBy === opt.value ? 'primary' : 'default'" @click="pickSort(opt.value)">
            {{ opt.label }}<span v-if="sortBy === opt.value" class="gm-dir">{{ asc ? ' ↑' : ' ↓' }}</span>
          </el-button>
        </el-button-group>
        <span v-if="lastUpdated" class="gm-updated">更新于 {{ lastUpdated.toLocaleTimeString('zh-CN') }}</span>
      </div>
    </div>

    <!-- grid -->
    <div v-if="sorted.length" class="gm-grid">
      <div v-for="(g, i) in sorted" :key="g.key" class="gm-card cockpit-panel"
        :class="cellClass(g)" role="link" tabindex="0"
        :aria-label="`查看 ${g.server_name} 的 GPU ${g.index} 详情`"
        @click="$router.push(`/servers/${g.server_id}`)"
        @keydown.enter.prevent="$router.push(`/servers/${g.server_id}`)"
        @keydown.space.prevent="$router.push(`/servers/${g.server_id}`)">
        <div class="gm-rank">#{{ i + 1 }}</div>
        <div class="gm-head">
          <div class="gm-id">
            <b>{{ g.server_name }}</b>
            <span class="gm-idx">GPU {{ g.index }}</span>
          </div>
          <span class="gm-model" :title="g.name">{{ shortName(g.name) }}</span>
        </div>

        <div class="gm-util-row">
          <div class="gm-ring" :style="ringStyle(g.utilization)">
            <span>{{ g.utilization }}<i>%</i></span>
          </div>
          <div class="gm-metrics">
            <div class="gm-metric">
              <span class="gm-m-label">显存</span>
              <div class="gm-bar"><div :style="{ width: memPct(g) + '%', background: barColor(memPct(g)) }"></div></div>
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
      </div>
    </div>

    <el-empty v-else-if="!loading" description="没有符合条件的 GPU" :image-size="80" />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Search } from '@element-plus/icons-vue'
import api from '../api'
import { fmtSizeMB } from '../format'
import { usePoll } from '../composables'
import '../cockpit.css'

const matrix = ref([])
const search = ref('')
const serverFilter = ref(null)
const stateFilter = ref('all')
const sortBy = ref('util')
const asc = ref(false)

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
  if (p >= 90) return '#f87171'
  if (p >= 70) return '#fbbf24'
  return '#34d399'
}

function ringStyle(u) {
  const color = u >= 90 ? '#f87171' : u >= 30 ? '#22d3ee' : '#34d399'
  return { background: `conic-gradient(${color} ${u * 3.6}deg, var(--cpanel2) 0)` }
}
</script>

<style scoped>
.gm-page { display: flex; flex-direction: column; gap: 14px; }

.gm-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  flex-wrap: wrap; gap: 10px; padding: 12px 16px;
}
.gm-toolbar-left, .gm-toolbar-right { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
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

.gm-card {
  position: relative; padding: 14px 16px; cursor: pointer;
  border: 1px solid var(--cborder); border-radius: 10px;
  transition: transform .15s, box-shadow .15s;
  display: flex; flex-direction: column; gap: 10px;
}
.gm-card:hover { transform: translateY(-2px); box-shadow: 0 6px 18px rgba(8, 145, 178, .12); }
.gm-card:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--cprimary) 40%, transparent);
  outline-offset: 2px;
  transform: translateY(-2px);
}
.gm-idle  { border-left: 3px solid #34d399; }
.gm-busy  { border-left: 3px solid #22d3ee; }
.gm-full  { border-left: 3px solid #f87171; }
.gm-offline { opacity: .55; border-left: 3px solid var(--csub); }

.gm-rank {
  position: absolute; top: 10px; right: 12px;
  font-size: 12px; color: var(--csub); font-variant-numeric: tabular-nums;
}

.gm-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; padding-right: 28px; }
.gm-id { min-width: 0; }
.gm-id b { font-size: 14px; }
.gm-idx { margin-left: 6px; font-size: 11px; color: var(--csub); }
.gm-model {
  font-size: 11px; color: var(--csub); max-width: 110px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

.gm-util-row { display: flex; align-items: center; gap: 14px; }
.gm-ring {
  width: 54px; height: 54px; border-radius: 50%; flex-shrink: 0;
  position: relative;
  display: flex; align-items: center; justify-content: center;
}
.gm-ring span {
  width: 42px; height: 42px; border-radius: 50%; background: var(--cpanel);
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 700; font-variant-numeric: tabular-nums;
}
.gm-ring i { font-style: normal; font-size: 9px; opacity: .6; }

.gm-metrics { flex: 1; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.gm-metric { display: flex; align-items: center; gap: 8px; font-size: 11px; }
.gm-m-label { color: var(--csub); flex-shrink: 0; }
.gm-m-val { color: var(--csub); white-space: nowrap; }
.gm-bar { flex: 1; height: 6px; border-radius: 3px; background: var(--cpanel2); overflow: hidden; }
.gm-bar div { height: 100%; border-radius: 3px; transition: width .5s; }
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
  .gm-sort-group :deep(.el-button) { min-width: max-content; flex: 1; padding-inline: 10px; }
  .gm-updated { grid-column: 1 / -1; text-align: right; }
  .gm-grid { grid-template-columns: minmax(0, 1fr); }
  .gm-card { padding: 14px; }
}
</style>
