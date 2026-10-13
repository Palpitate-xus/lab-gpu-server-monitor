<template>
  <a-spin :spinning="loading" tip="正在加载服务器数据…">
  <div class="cockpit">
    <a-alert v-if="invalidId" type="warning" show-icon :closable="false" style="margin-bottom:14px">
      <template #message>
        无效的服务器 ID，请返回
        <a-button type="link" size="small" class="inline-link" @click="$router.push('/servers')">服务器列表</a-button>
        重新进入。
      </template>
    </a-alert>
    <div class="toolbar detail-toolbar">
      <a-page-header :title="server?.name || '服务器详情'" @back="$router.push('/servers')" />
      <div class="detail-toolbar-actions">
        <a-tag v-if="metric?.status === 'ok'" color="success">正常</a-tag>
        <a-tag v-else-if="metric" color="error">采集异常</a-tag>
        <a-tag v-if="server?.status && server.status !== 'active'" color="warning">
          {{ statusCn[server.status] }}<span v-if="server.status_reason">：{{ server.status_reason }}</span>
        </a-tag>
        <a-dropdown v-if="isAdmin" :trigger="['click']">
          <a-button size="small" :disabled="actionSaving">状态切换</a-button>
          <template #overlay>
            <a-menu @click="onStatusMenu">
              <a-menu-item key="active">运行中</a-menu-item>
              <a-menu-item key="maintenance">维护中</a-menu-item>
              <a-menu-item key="drained">已排空</a-menu-item>
              <a-menu-item key="rma">返修中</a-menu-item>
            </a-menu>
          </template>
        </a-dropdown>
        <a-button size="small" @click="refreshAll"><ReloadOutlined />刷新</a-button>
      </div>
    </div>

    <nav v-if="metric" class="detail-jump-nav" aria-label="服务器详情分区导航">
      <button type="button" @click="scrollToSection('detail-health')">健康</button>
      <button type="button" @click="scrollToSection('detail-resources')">资源</button>
      <button v-if="isGpuServer" type="button" @click="scrollToSection('detail-gpus')">GPU</button>
      <button type="button" @click="scrollToSection('detail-trends')">趋势</button>
      <button type="button" @click="scrollToSection('detail-enterprise')">硬件与事件</button>
    </nav>

    <template v-if="metric">
      <a-alert v-if="loadError" :message="`刷新失败：${loadError}。当前显示上次成功读取的数据。`" type="warning" show-icon :closable="false" style="margin-bottom:14px" />
      <a-alert v-if="panelErrors.overview" :message="`健康信息刷新失败：${panelErrors.overview}。已有健康信息可能已过期。`" type="warning" show-icon :closable="false" style="margin-bottom:14px" />
      <a-alert v-if="metric.status !== 'ok'" :message="`采集失败: ${metricErrorText}`" type="error" show-icon :closable="false" style="margin-bottom:14px" />

      <!-- ===== health model tree ===== -->
      <a-card id="detail-health" v-if="health && health.categories" class="page-card detail-section" style="margin-top:14px">
        <template #title>
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span>健康模型</span>
            <a-tag :color="overallTag(health.overall)">{{ overallLabel(health.overall) }}</a-tag>
          </div>
        </template>
        <div class="health-grid">
          <div v-for="c in health.categories" :key="c.name" class="health-cat" :class="`st-${c.status}`">
            <div class="health-cat-head">
              <span class="health-dot"></span>
              <b>{{ c.name }}</b>
              <span class="health-status">{{ statusLabel(c.status) }}</span>
            </div>
            <div class="health-detail">{{ c.detail || '—' }}</div>
            <div v-if="c.children" class="health-children">
              <div v-for="ch in c.children" :key="ch.name" class="health-sub" :class="`st-${ch.status}`">
                <b>{{ ch.name }}</b>
                <span class="health-detail">{{ ch.detail }}</span>
              </div>
            </div>
          </div>
        </div>
      </a-card>

      <!-- ===== btop-style overview stats ===== -->
      <a-row id="detail-resources" :gutter="16" class="detail-kpis detail-section kpi-row">
        <a-col :xs="12" :lg="6"><a-card class="stat-card detail-kpi-card">
          <div class="stat-value" :style="{color: utilColor(metric.cpu_percent)}">{{ metric.cpu_percent }}%</div>
          <div class="stat-label">CPU ({{ metric.cpu_count }} 核 {{ fmtFreq(metric.cpu_freq_avg) }})</div>
          <div class="stat-sub">{{ metric.cpu_model || '—' }}</div>
        </a-card></a-col>
        <a-col :xs="12" :lg="6"><a-card class="stat-card detail-kpi-card">
          <div class="stat-value detail-capacity-value">{{ fmtSizeMB(metric.mem_used_mb) }} <i>/</i> {{ fmtSizeMB(metric.mem_total_mb) }}</div>
          <div class="stat-label">内存 ({{ memPct }}%)</div>
          <div class="stat-sub">可用 {{ fmtSizeMB(metric.mem_available_mb) }} · 缓存 {{ fmtSizeMB(metric.mem_cached_mb) }} · Swap {{ fmtSizeMB(metric.swap_used_mb) }}/{{ fmtSizeMB(metric.swap_total_mb) }}</div>
        </a-card></a-col>
        <a-col :xs="12" :lg="6"><a-card class="stat-card detail-kpi-card">
          <div class="stat-value detail-capacity-value">{{ (metric.disk_used_gb ?? 0).toFixed(0) }} <i>/</i> {{ (metric.disk_total_gb ?? 0).toFixed(0) }} GB</div>
          <div class="stat-label">磁盘 ({{ diskPct }}%)</div>
          <div class="stat-sub">{{ (metric.disks||[]).length }} 个挂载点</div>
        </a-card></a-col>
        <a-col :xs="12" :lg="6"><a-card class="stat-card detail-kpi-card">
          <div class="stat-value">{{ fmtUptime(metric.uptime_seconds) }}</div>
          <div class="stat-label">运行时长</div>
          <div class="stat-sub">{{ metric.os }} · {{ metric.kernel }}</div>
        </a-card></a-col>
      </a-row>

      <!-- ===== per-core grid (btop style) ===== -->
      <a-card class="page-card" style="margin-top:14px">
        <template #title>
          <div class="detail-card-head">
            <span>CPU 核心 ({{ cores.length }})</span>
            <div style="display:flex;gap:16px;font-size:12px;color:var(--csub);align-items:center">
              <span>负载 {{ (metric.load1 ?? 0).toFixed(2) }} / {{ (metric.load5 ?? 0).toFixed(2) }} / {{ (metric.load15 ?? 0).toFixed(2) }}</span>
              <span v-if="metric.cpu_temp_package">封装温度 {{ metric.cpu_temp_package }}°C</span>
              <span>采集耗时 {{ metric.duration }}s</span>
            </div>
          </div>
        </template>
        <div class="core-grid">
          <a-tooltip v-for="c in cores" :key="c.id" :placement="'top'">
            <template #title>
              核心 {{ c.id }}: {{ c.util }}% · {{ fmtFreq(c.freq_mhz) }}<span v-if="c.temp"> · {{ c.temp }}°C</span>
            </template>
            <div class="core-block" :class="coreClass(c.util)">
              <div class="core-fill" :style="{height: c.util + '%'}"></div>
              <span class="core-text">{{ c.util > 60 ? c.util : (c.util > 25 ? c.util : '') }}</span>
            </div>
          </a-tooltip>
        </div>
      </a-card>

      <!-- ===== GPU cards (GPU servers only) ===== -->
      <a-card id="detail-gpus" v-if="isGpuServer" class="page-card detail-section">
        <template #title>
          <div class="detail-card-head">
            <span>GPU ({{ gpus.length }})</span>
            <span style="color:var(--csub);font-size:13px">驱动 {{ metric.gpu_driver || '—' }}</span>
          </div>
        </template>
        <a-empty v-if="!gpus.length" description="未检测到 GPU（nvidia-smi 不可用）" />
        <a-row :gutter="16" v-else>
          <a-col :xs="24" :lg="12" v-for="g in gpus" :key="g.uuid + g.index">
            <a-card class="gpu-card">
              <div class="gpu-card-head">
                <b>GPU {{ g.index }} · {{ g.name }}</b>
                <div class="gpu-card-tags">
                  <a-tag v-if="gpuRisk(g.uuid)?.risk >= 30" :color="gpuRisk(g.uuid).risk >= 60 ? 'error' : 'warning'">风险 {{ gpuRisk(g.uuid).risk }}</a-tag>
                  <a-tag v-if="g.throttle_reasons?.length" color="warning">降频: {{ throttleShort(g.throttle_reasons) }}</a-tag>
                  <a-tag v-if="g.pstate" color="default">{{ g.pstate }}</a-tag>
                  <a-tag v-if="g.compute_mode && g.compute_mode !== 'Default'" color="warning">{{ g.compute_mode }}</a-tag>
                </div>
              </div>
              <a-descriptions :column="{ xs: 1, sm: 2 }" size="small" bordered>
                <a-descriptions-item label="利用率">
                  <a-progress :percent="pct(g.utilization)" :stroke-color="utilColor(g.utilization)" :stroke-width="12" style="width:130px" />
                </a-descriptions-item>
                <a-descriptions-item label="显存">
                  <a-progress :percent="gpuMemPct(g)" :stroke-color="utilColor(gpuMemPct(g))" :stroke-width="12" style="width:130px" />
                  <div class="mono" style="font-size:12px">{{ fmtSizeMB(g.mem_used_mb) }} / {{ fmtSizeMB(g.mem_total_mb) }}</div>
                </a-descriptions-item>
                <a-descriptions-item label="温度">
                  <span :style="{ color: tempColor(g.temperature) }">{{ g.temperature }}°C</span>
                  <span v-if="g.mem_temperature" style="margin-left:6px;color:var(--csub)">显存 {{ g.mem_temperature }}°C</span>
                </a-descriptions-item>
                <a-descriptions-item label="功耗">{{ g.power_draw }} / {{ g.power_limit }} W</a-descriptions-item>
                <a-descriptions-item label="核心频率">{{ g.clock_graphics ? (g.clock_graphics + ' MHz') : '—' }}<span v-if="g.clock_graphics_max" style="color:var(--csub)"> / {{ g.clock_graphics_max }}</span></a-descriptions-item>
                <a-descriptions-item label="显存频率">{{ g.clock_memory ? (g.clock_memory + ' MHz') : '—' }}<span v-if="g.clock_memory_max" style="color:var(--csub)"> / {{ g.clock_memory_max }}</span></a-descriptions-item>
                <a-descriptions-item label="PCIe">Gen{{ g.pcie_gen_current }} x{{ g.pcie_width_current }}<span v-if="g.pcie_gen_max && (g.pcie_gen_current < g.pcie_gen_max || g.pcie_width_current < g.pcie_width_max)" style="color:var(--cyellow)">（应为 Gen{{ g.pcie_gen_max }} x{{ g.pcie_width_max }}，降级!）</span><span v-else-if="g.pcie_gen_max" style="color:var(--csub)"> / Gen{{ g.pcie_gen_max }} x{{ g.pcie_width_max }}</span></a-descriptions-item>
                <a-descriptions-item label="ECC">
                  <span v-if="g.ecc_supported">{{ g.ecc_mode }} · 不可纠正 {{ g.ecc_uncorrected_volatile ?? 0 }}</span>
                  <span v-else style="color:var(--csub)">不支持（消费卡）</span>
                </a-descriptions-item>
                <a-descriptions-item label="风扇">{{ g.fan_speed }}%</a-descriptions-item>
                <a-descriptions-item label="编解码">编码 {{ g.encoder_sessions ?? 0 }} · 解码 {{ g.decoder_sessions ?? 0 }}</a-descriptions-item>
              </a-descriptions>
              <div v-if="g.processes?.length" style="margin-top:8px">
                <div style="font-size:12px;color:var(--csub);margin-bottom:4px">GPU 进程</div>
                <a-table class="desktop-only" :data-source="g.processes" row-key="pid" size="small" :scroll="{ y: 220 }" :pagination="false">
                  <a-table-column data-index="pid" title="PID" width="80" />
                  <a-table-column data-index="user" title="用户" width="100" :ellipsis="true" />
                  <a-table-column title="显存" width="100">
                    <template #default="{ record: row }">{{ fmtSizeMB(row.mem_mb) }}</template>
                  </a-table-column>
                  <a-table-column data-index="command" title="进程" width="140" :ellipsis="true" />
                </a-table>
                <div class="mobile-only gpu-process-list">
                  <div v-for="row in g.processes" :key="row.pid" class="gpu-process-item">
                    <div>
                      <b class="mono">PID {{ row.pid }}</b>
                      <span>{{ row.user || '未知用户' }}</span>
                    </div>
                    <span class="mono">{{ fmtSizeMB(row.mem_mb) }}</span>
                    <p class="mono">{{ row.command || '—' }}</p>
                  </div>
                </div>
              </div>
            </a-card>
          </a-col>
        </a-row>
      </a-card>

      <!-- ===== network & disk IO rates ===== -->
      <a-row :gutter="16">
        <a-col :xs="24" :lg="12">
          <a-card class="page-card">
            <template #title><div style="display:flex;justify-content:space-between;align-items:center">网络速率 (实时)<RateUnitPicker kind="net" @change="onUnitChange" /></div></template>
            <a-table :data-source="metric.net_ifaces || []" row-key="iface" size="small" :scroll="{ y: 260 }" :pagination="false">
              <a-table-column data-index="iface" title="接口" width="110" />
              <a-table-column title="↓ 接收" width="120">
                <template #default="{ record: row }"><span class="mono">{{ fmtNetRate(row.rx_bps) }}</span></template>
              </a-table-column>
              <a-table-column title="↑ 发送" width="120">
                <template #default="{ record: row }"><span class="mono">{{ fmtNetRate(row.tx_bps) }}</span></template>
              </a-table-column>
            </a-table>
            <a-empty v-if="!(metric.net_ifaces||[]).length" description="暂无活动接口" />
          </a-card>
        </a-col>
        <a-col :xs="24" :lg="12">
          <a-card class="page-card">
            <template #title><div style="display:flex;justify-content:space-between;align-items:center">磁盘 IO (实时)<RateUnitPicker kind="disk" @change="onUnitChange" /></div></template>
            <a-table :data-source="metric.disk_io || []" row-key="device" size="small" :scroll="{ y: 260 }" :pagination="false">
              <a-table-column data-index="device" title="设备" width="90" />
              <a-table-column title="读" width="110">
                <template #default="{ record: row }"><span class="mono">{{ fmtDiskRate(row.read_bps) }}</span></template>
              </a-table-column>
              <a-table-column title="写" width="110">
                <template #default="{ record: row }"><span class="mono">{{ fmtDiskRate(row.write_bps) }}</span></template>
              </a-table-column>
              <a-table-column title="IOPS r/w" width="110">
                <template #default="{ record: row }"><span class="mono">{{ row.read_iops }}/{{ row.write_iops }}</span></template>
              </a-table-column>
              <a-table-column title="繁忙" width="90">
                <template #default="{ record: row }">{{ row.busy_percent }}%</template>
              </a-table-column>
            </a-table>
            <a-empty v-if="!(metric.disk_io||[]).length" description="暂无活动 IO" />
          </a-card>
        </a-col>
      </a-row>

      <!-- ===== disks + logged users ===== -->
      <a-row :gutter="16">
        <a-col :xs="24" :lg="16">
          <a-card class="page-card">
            <template #title>磁盘分区</template>
            <a-table :data-source="metric.disks || []" :row-key="row => `${row.device}:${row.mount}`" size="small" :scroll="{ y: 300 }" :pagination="false">
              <a-table-column data-index="mount" title="挂载点" width="130" :ellipsis="true" />
              <a-table-column data-index="device" title="设备" width="110" :ellipsis="true" class-name="mono" />
              <a-table-column title="用量" width="200">
                <template #default="{ record: row }">
                  <a-progress :percent="pct(row.percent)" :stroke-color="utilColor(row.percent)" :stroke-width="10" />
                </template>
              </a-table-column>
              <a-table-column title="已用/总量" width="140">
                <template #default="{ record: row }"><span class="mono">{{ row.used_gb.toFixed(0) }}/{{ row.total_gb.toFixed(0) }} GB</span></template>
              </a-table-column>
            </a-table>
          </a-card>
        </a-col>
        <a-col :xs="24" :lg="8">
          <a-card class="page-card">
            <template #title>登录用户</template>
            <a-table :data-source="metric.users || []" :row-key="row => `${row.user}:${row.tty}:${row.login}`" size="small" :scroll="{ y: 260 }" :pagination="false">
              <a-table-column data-index="user" title="用户" width="90" />
              <a-table-column data-index="from" title="来源" width="110" :ellipsis="true" />
              <a-table-column data-index="login" title="登录时间" width="110" :ellipsis="true" />
            </a-table>
            <a-empty v-if="!(metric.users||[]).length" description="无登录用户" />
          </a-card>
        </a-col>
      </a-row>

      <!-- ===== live process table (btop parity: sort/kill/renice) ===== -->
      <a-card v-if="isAdmin" class="page-card">
        <template #title>
          <div class="detail-card-head process-card-head">
            <span>进程 (实时 SSH · {{ procs.length }})</span>
            <div class="process-card-actions">
              <a-radio-group v-model:value="procSort" size="small" @change="loadProcs">
                <a-radio-button value="cpu">CPU</a-radio-button>
                <a-radio-button value="mem">内存</a-radio-button>
                <a-radio-button value="time">时长</a-radio-button>
              </a-radio-group>
              <a-input v-model:value="procFilter" placeholder="过滤..." size="small" style="width:150px" allow-clear />
              <a-button size="small" @click="loadProcs"><ReloadOutlined />刷新</a-button>
            </div>
          </div>
        </template>
        <a-table :data-source="filteredProcs" :row-key="row => `${row.pid}:${row.start_ticks}`" size="small" :scroll="{ y: 420 }" :loading="procsLoading" :pagination="false">
          <a-table-column data-index="pid" title="PID" width="80" :sorter="(a, b) => a.pid - b.pid" />
          <a-table-column data-index="user" title="用户" width="100" :ellipsis="true" :sorter="(a, b) => (a.user || '').localeCompare(b.user || '')" />
          <a-table-column data-index="cpu" title="CPU%" width="85" :sorter="(a, b) => a.cpu - b.cpu">
            <template #default="{ record: row }">{{ row.cpu.toFixed(1) }}</template>
          </a-table-column>
          <a-table-column data-index="rss_mb" title="内存 MB" width="95" :sorter="(a, b) => a.rss_mb - b.rss_mb">
            <template #default="{ record: row }">{{ row.rss_mb.toFixed(0) }}</template>
          </a-table-column>
          <a-table-column data-index="mem" title="mem%" width="80" :sorter="(a, b) => a.mem - b.mem">
            <template #default="{ record: row }">{{ row.mem.toFixed(1) }}</template>
          </a-table-column>
          <a-table-column data-index="stat" title="状态" width="70" />
          <a-table-column title="运行时长" width="95" :sorter="(a, b) => a.etimes - b.etimes">
            <template #default="{ record: row }">{{ fmtDuration(row.etimes) }}</template>
          </a-table-column>
          <a-table-column data-index="command" title="命令" width="240" :ellipsis="true" class-name="mono" />
          <a-table-column v-if="isAdmin" title="操作" width="130" fixed="right">
            <template #default="{ record: row }">
              <a-button size="small" :disabled="!row.start_ticks" @click="openRenice(row)">renice</a-button>
              <a-popconfirm :title="`确定 kill 进程 ${row.pid} (${(row.command || '').slice(0,30)})？`" ok-text="继续" cancel-text="取消" @confirm="openKill(row, 'TERM')">
                <a-button size="small" danger :disabled="!row.start_ticks">kill</a-button>
              </a-popconfirm>
            </template>
          </a-table-column>
        </a-table>
      </a-card>

      <!-- ===== history charts (cockpit style, multi-panel) ===== -->
      <a-card id="detail-trends" class="page-card detail-section">
        <template #title>
          <div class="detail-card-head trend-card-head">
            <span>资源消耗趋势</span>
            <a-radio-group v-model:value="hours" size="small" @change="loadHistory">
              <a-radio-button :value="1">1小时</a-radio-button>
              <a-radio-button :value="3">3小时</a-radio-button>
              <a-radio-button :value="6">6小时</a-radio-button>
              <a-radio-button :value="24">24小时</a-radio-button>
              <a-radio-button :value="168">7天</a-radio-button>
            </a-radio-group>
          </div>
        </template>
        <a-alert v-if="historyError" :message="`趋势加载失败：${historyError}`" type="warning" show-icon :closable="false" style="margin-bottom:12px" />
        <a-row :gutter="16">
          <a-col v-if="isGpuServer" :xs="24" :lg="12">
            <div class="chart-sub-title">GPU 利用率 / 显存 / 温度 / 功耗</div>
            <v-chart v-if="history.length" :option="gpuChartOption" class="chart-box" autoresize />
            <a-empty v-else description="暂无历史数据" />
          </a-col>
          <a-col :xs="24" :lg="isGpuServer ? 12 : 24">
            <div class="chart-sub-title">CPU / 内存 / Swap / 每核负载</div>
            <v-chart v-if="history.length" :option="sysChartOption" class="chart-box" autoresize />
            <a-empty v-else description="暂无历史数据" />
          </a-col>
        </a-row>
        <a-row :gutter="16" style="margin-top:8px">
          <a-col :xs="24" :lg="12">
            <div class="chart-sub-title" style="display:flex;justify-content:space-between;align-items:center">网络吞吐 (接收 / 发送)<RateUnitPicker kind="net" @change="onUnitChange" /></div>
            <v-chart v-if="history.length" :option="netChartOption" class="chart-box-sm" autoresize />
          </a-col>
          <a-col :xs="24" :lg="12">
            <div class="chart-sub-title" style="display:flex;justify-content:space-between;align-items:center">磁盘 IO (读 / 写)<RateUnitPicker kind="disk" @change="onUnitChange" /></div>
            <v-chart v-if="history.length" :option="diskChartOption" class="chart-box-sm" autoresize />
          </a-col>
        </a-row>
      </a-card>

      <!-- ===== enterprise: events / nvme / services / inventory ===== -->
      <a-card id="detail-enterprise" class="page-card detail-section enterprise-card">
        <div class="enterprise-toolbar">
          <a-button size="small" :loading="panelLoading[enterpriseGroup(entTab)]" @click="ensureEnterpriseTab(entTab, true)"><ReloadOutlined />刷新当前页签</a-button>
          <span v-if="panelUpdated[enterpriseGroup(entTab)]" class="enterprise-toolbar__hint">最近读取：{{ fmtTime(panelUpdated[enterpriseGroup(entTab)]) }}</span>
        </div>
        <a-alert v-if="panelErrors[enterpriseGroup(entTab)]" type="warning" show-icon :closable="false" style="margin-bottom:12px"
          :message="`刷新失败：${panelErrors[enterpriseGroup(entTab)]}。已有数据可能已过期，请稍后重试。`" />
        <a-tabs v-model:activeKey="entTab">
          <a-tab-pane tab="内核事件" key="events">
            <div class="enterprise-toolbar">
              <a-radio-group v-model:value="evSev" size="small" @change="loadEvents">
                <a-radio-button value="">全部</a-radio-button>
                <a-radio-button value="critical">严重</a-radio-button>
                <a-radio-button value="warning">警告</a-radio-button>
              </a-radio-group>
              <a-button size="small" @click="loadEvents"><ReloadOutlined />刷新</a-button>
              <span class="enterprise-toolbar__hint">XID / OOM / MCE / EDAC / AER / IO / NFS 错误（journalctl -k 增量）</span>
            </div>
            <a-table class="desktop-only" :data-source="events" row-key="id" size="small" :scroll="{ y: 320 }" :pagination="false">
              <a-table-column title="时间" width="160">
                <template #default="{ record: row }"><span class="mono">{{ fmtTime(row.collected_at) }}</span></template>
              </a-table-column>
              <a-table-column title="级别" width="80">
                <template #default="{ record: row }">
                  <a-tag :color="row.severity === 'critical' ? 'error' : row.severity === 'warning' ? 'warning' : 'default'">{{ row.severity }}</a-tag>
                </template>
              </a-table-column>
              <a-table-column data-index="event_type" title="类型" width="170">
                <template #default="{ record: row }"><b class="mono">{{ row.event_type }}</b><span v-if="row.xid" class="mono" style="margin-left:6px;color:var(--cred)">Xid {{ row.xid }}</span></template>
              </a-table-column>
              <a-table-column data-index="gpu_uuid" title="GPU" width="130" :ellipsis="true">
                <template #default="{ record: row }"><span class="mono" style="font-size:11px">{{ row.gpu_uuid ? row.gpu_uuid.slice(0, 16) : '' }}</span></template>
              </a-table-column>
              <a-table-column data-index="message" title="消息" width="400" :ellipsis="true" />
            </a-table>
            <div v-if="events.length" class="mobile-only enterprise-event-list">
              <article
                v-for="row in events"
                :key="row.id"
                class="mobile-data-card enterprise-event-card"
                :class="`enterprise-event-card--${row.severity}`"
              >
                <div class="mobile-data-card__head">
                  <div class="mobile-data-card__title mono">
                    {{ row.event_type }}
                    <span v-if="row.xid">Xid {{ row.xid }}</span>
                  </div>
                  <a-tag :color="row.severity === 'critical' ? 'error' : row.severity === 'warning' ? 'warning' : 'default'">
                    {{ row.severity }}
                  </a-tag>
                </div>
                <p>{{ row.message }}</p>
                <div class="mobile-data-card__meta">
                  <span>时间</span><span>{{ fmtTime(row.collected_at) }}</span>
                  <span>GPU</span><span class="mono enterprise-event-card__gpu">{{ row.gpu_uuid || '—' }}</span>
                </div>
              </article>
            </div>
            <a-empty v-if="!events.length" description="24 小时内无内核异常事件" />
          </a-tab-pane>

          <a-tab-pane v-if="isAdmin" tab="NVMe / 存储" key="nvme">
            <a-table :data-source="slowHealth.nvme_smart || []" row-key="device" size="small" :scroll="{ y: 260 }" :pagination="false">
              <a-table-column data-index="device" title="设备" width="110" />
              <a-table-column title="温度" width="80">
                <template #default="{ record: row }">{{ row.temperature ? row.temperature + '°C' : '—' }}</template>
              </a-table-column>
              <a-table-column title="健康" width="90">
                <template #default="{ record: row }">
                  <a-tag :color="row.critical_warning ? 'error' : (row.available_spare !== undefined && row.available_spare <= (row.available_spare_threshold ?? 10) ? 'warning' : 'success')">
                    {{ row.critical_warning ? '异常' : '正常' }}
                  </a-tag>
                </template>
              </a-table-column>
              <a-table-column title="寿命已用" width="100">
                <template #default="{ record: row }">{{ row.percentage_used !== undefined ? row.percentage_used + '%' : '—' }}</template>
              </a-table-column>
              <a-table-column title="介质错误" width="90">
                <template #default="{ record: row }"><span :style="row.media_errors ? 'color:var(--cred)' : ''">{{ row.media_errors ?? '—' }}</span></template>
              </a-table-column>
              <a-table-column title="意外断电" width="90">
                <template #default="{ record: row }">{{ row.unsafe_shutdowns ?? '—' }}</template>
              </a-table-column>
              <a-table-column title="读/写单元" width="150">
                <template #default="{ record: row }"><span class="mono" style="font-size:11px">{{ fmtUnits(row.data_units_read) }} / {{ fmtUnits(row.data_units_written) }}</span></template>
              </a-table-column>
            </a-table>
            <a-empty v-if="!(slowHealth.nvme_smart||[]).length" description="未检测到 NVMe 设备（或无 nvme-cli 权限）" />
            <template v-if="(slowHealth.mdraid?.arrays||[]).length">
              <div class="chart-sub-title" style="margin-top:14px">RAID 阵列</div>
              <a-table :data-source="slowHealth.mdraid.arrays" row-key="name" size="small" :scroll="{ y: 240 }" :pagination="false">
                <a-table-column data-index="name" title="阵列" width="100" />
                <a-table-column data-index="level" title="级别" width="80" />
                <a-table-column title="状态" width="120">
                  <template #default="{ record: row }">
                    <a-tag :color="row.degraded ? 'error' : 'success'">{{ row.state }} ({{ row.active_disks }}/{{ row.total_disks }})</a-tag>
                  </template>
                </a-table-column>
                <a-table-column title="重建进度" width="120">
                  <template #default="{ record: row }">{{ row.recovery_percent !== undefined ? row.recovery_percent + '%' : '—' }}</template>
                </a-table-column>
              </a-table>
            </template>
            <template v-if="(slowHealth.nfs_mounts||[]).length">
              <div class="chart-sub-title" style="margin-top:14px">NFS / 共享存储挂载</div>
              <a-table :data-source="slowHealth.nfs_mounts" row-key="mount" size="small" :scroll="{ y: 240 }" :pagination="false">
                <a-table-column data-index="server" title="服务器" width="140" />
                <a-table-column data-index="export" title="导出路径" width="160" :ellipsis="true" />
                <a-table-column data-index="mount" title="挂载点" width="140" :ellipsis="true" />
                <a-table-column data-index="type" title="类型" width="90" />
              </a-table>
            </template>
          </a-tab-pane>

          <a-tab-pane v-if="isAdmin" tab="服务 / MIG" key="services">
            <a-row :gutter="16">
              <a-col :xs="24" :lg="12">
                <div class="chart-sub-title">关键服务状态</div>
                <a-table :data-source="serviceRows" row-key="name" size="small" :scroll="{ y: 240 }" :pagination="false">
                  <a-table-column data-index="name" title="服务" width="180" />
                  <a-table-column title="状态" width="110">
                    <template #default="{ record: row }">
                      <a-tag :color="row.state === 'active' ? 'success' : row.state === 'inactive' ? 'default' : 'error'">{{ row.state }}</a-tag>
                    </template>
                  </a-table-column>
                </a-table>
                <template v-if="(slowHealth.systemd_failed||[]).length">
                  <div class="chart-sub-title" style="color:var(--cred)">失败的 systemd 单元</div>
                  <a-table :data-source="slowHealth.systemd_failed" row-key="unit" size="small" :scroll="{ y: 240 }" :pagination="false">
                    <a-table-column data-index="unit" title="单元" width="200" />
                    <a-table-column data-index="active" title="状态" width="90" />
                  </a-table>
                </template>
              </a-col>
              <a-col :xs="24" :lg="12">
                <div class="chart-sub-title">MIG（多实例 GPU）</div>
                <a-table :data-source="slowHealth.mig || []" row-key="gpu_index" size="small" :scroll="{ y: 240 }" :pagination="false">
                  <a-table-column data-index="gpu_index" title="GPU" width="70" />
                  <a-table-column title="MIG 模式" width="120">
                    <template #default="{ record: row }">
                      <a-tag :color="row.mode === 'Enabled' ? 'success' : 'default'">{{ row.mode }}</a-tag>
                    </template>
                  </a-table-column>
                </a-table>
                <a-empty v-if="!(slowHealth.mig||[]).length" description="无 MIG 支持 / 未启用" />
                <div class="chart-sub-title" style="margin-top:10px">IPMI / BMC 传感器</div>
                <a-table :data-source="(slowHealth.ipmi||[]).slice(0, 8)" row-key="name" size="small" :scroll="{ y: 240 }" :pagination="false">
                  <a-table-column data-index="name" title="传感器" width="140" :ellipsis="true" />
                  <a-table-column data-index="value" title="值" width="90" />
                  <a-table-column data-index="unit" title="单位" width="80" />
                </a-table>
                <a-empty v-if="!(slowHealth.ipmi||[]).length" description="无 IPMI 数据（需要 ipmitool 权限）" />
              </a-col>
            </a-row>
          </a-tab-pane>

          <a-tab-pane v-if="isAdmin" tab="资产 / 拓扑" key="inventory">
            <a-descriptions v-if="inventory.machine_id" :column="3" bordered size="small">
              <a-descriptions-item label="Machine ID"><span class="mono" style="font-size:11px">{{ inventory.machine_id }}</span></a-descriptions-item>
              <a-descriptions-item label="厂商/型号">{{ (inventory.dmi||{}).sys_vendor }} {{ (inventory.dmi||{}).product_name }}</a-descriptions-item>
              <a-descriptions-item label="序列号"><span class="mono" style="font-size:11px">{{ (inventory.dmi||{}).product_serial }}</span></a-descriptions-item>
              <a-descriptions-item label="BIOS">{{ (inventory.dmi||{}).bios_version }} ({{ (inventory.dmi||{}).bios_date }})</a-descriptions-item>
              <a-descriptions-item label="CPU">{{ (inventory.lscpu||{}).model_name }}</a-descriptions-item>
              <a-descriptions-item label="插槽/核心">{{ (inventory.lscpu||{}).sockets }} 路 / {{ (inventory.lscpu||{}).cores_per_socket }} 核</a-descriptions-item>
              <a-descriptions-item label="NUMA 节点">{{ ((inventory.numa||{}).nodes||[]).map(n => `node${n.id}: ${n.cpus} (${n.mem_gb}GB)`).join('；') || (inventory.lscpu||{}).numa_nodes }}</a-descriptions-item>
              <a-descriptions-item label="时间同步">{{ (inventory.time_info||{}).system_clock_synchronized === 'yes' ? 'NTP 已同步' : '未同步' }}</a-descriptions-item>
              <a-descriptions-item label="IP">{{ (inventory.ip_addrs||[]).join(' · ') }}</a-descriptions-item>
            </a-descriptions>
            <div v-if="inventory.gpu_topology" class="chart-sub-title" style="margin-top:14px">GPU 拓扑（nvidia-smi topo -m）</div>
            <pre v-if="inventory.gpu_topology" class="topo-pre">{{ inventory.gpu_topology }}</pre>
            <div class="chart-sub-title" style="margin-top:14px">磁盘 / 网卡</div>
            <a-row :gutter="16">
              <a-col :xs="24" :lg="12">
                <a-table :data-source="(inventory.disks||[]).slice(0, 12)" row-key="name" size="small" :scroll="{ y: 300 }" :pagination="false">
                  <a-table-column data-index="name" title="磁盘" width="90" />
                  <a-table-column data-index="size" title="容量" width="90" />
                  <a-table-column data-index="type" title="类型" width="80" />
                  <a-table-column data-index="model" title="型号" width="140" :ellipsis="true" />
                </a-table>
              </a-col>
              <a-col :xs="24" :lg="12">
                <a-table :data-source="physicalNics" row-key="name" size="small" :scroll="{ y: 240 }" :pagination="false">
                  <a-table-column data-index="name" title="网卡" width="110" />
                  <a-table-column data-index="mac" title="MAC" width="140">
                    <template #default="{ record: row }"><span class="mono" style="font-size:11px">{{ row.mac }}</span></template>
                  </a-table-column>
                  <a-table-column data-index="state" title="状态" width="80" />
                  <a-table-column data-index="speed" title="速率" width="80" />
                </a-table>
              </a-col>
            </a-row>
          </a-tab-pane>

          <a-tab-pane v-if="isAdmin" tab="带外 IPMI" key="ipmi">
            <div v-if="!server?.has_bmc" style="padding:20px;text-align:center;color:var(--csub)">
              未配置带外管理。请在「编辑服务器」中填写 BMC 地址 / 账号，即可从监控主机直连 IPMI（关机 / 宕机也能监控）。
            </div>
            <template v-else-if="ipmi?.snapshot">
              <a-alert v-if="!ipmi.snapshot.ok" type="error" :closable="false" show-icon
                :message="`BMC 连接失败：${ipmi.snapshot.error}`" style="margin-bottom:12px" />
              <a-row :gutter="12" style="margin-bottom:12px">
                <a-col :xs="12" :lg="6"><div class="ipmi-kpi"><b :style="{ color: ipmi.summary?.power_on ? 'var(--cgreen)' : 'var(--cred)' }">{{ ipmi.summary?.power_on ? '开启' : '关闭' }}</b><span>机箱电源</span></div></a-col>
                <a-col :xs="12" :lg="6"><div class="ipmi-kpi"><b>{{ ipmi.summary?.power_w || '—' }} W</b><span>整机功耗（DCMI）</span></div></a-col>
                <a-col :xs="12" :lg="6"><div class="ipmi-kpi"><b>{{ (ipmi.snapshot.sensors || []).length }}</b><span>传感器</span></div></a-col>
                <a-col :xs="12" :lg="6"><div class="ipmi-kpi"><b class="mono" style="font-size:13px">{{ fmtTime(ipmi.snapshot.collected_at) }}</b><span>最近采集（每 5 分钟）</span></div></a-col>
              </a-row>
              <a-row :gutter="12">
                <a-col :xs="24" :lg="12">
                  <div class="chart-sub-title">BMC 信息（mc info）</div>
                  <a-descriptions :column="1" bordered size="small">
                    <a-descriptions-item v-for="(v, k) in ipmi.snapshot.mc_info" :key="k" :label="k">{{ v }}</a-descriptions-item>
                  </a-descriptions>
                  <div class="chart-sub-title" style="margin-top:10px">机箱状态（chassis）</div>
                  <a-descriptions :column="1" bordered size="small">
                    <a-descriptions-item v-for="(v, k) in ipmi.snapshot.chassis" :key="k" :label="k">{{ v }}</a-descriptions-item>
                  </a-descriptions>
                  <div class="chart-sub-title" style="margin-top:10px">功耗统计（dcmi power）</div>
                  <a-descriptions :column="1" bordered size="small">
                    <a-descriptions-item v-for="(v, k) in ipmi.snapshot.power" :key="k" :label="k">{{ v }}</a-descriptions-item>
                  </a-descriptions>
                  <div class="chart-sub-title" style="margin-top:10px">BMC 网络（lan）</div>
                  <a-descriptions :column="1" bordered size="small">
                    <a-descriptions-item v-for="(v, k) in ipmi.snapshot.lan" :key="k" :label="k">{{ v }}</a-descriptions-item>
                  </a-descriptions>
                </a-col>
                <a-col :xs="24" :lg="12">
                  <div class="chart-sub-title">全部传感器（sdr）</div>
                  <a-table :data-source="ipmi.snapshot.sensors || []" :row-key="row => `${row.id}:${row.name}`" size="small" :scroll="{ y: 300 }" :pagination="false">
                    <a-table-column data-index="name" title="传感器" width="130" :ellipsis="true" />
                    <a-table-column data-index="reading" title="读数" width="130" :ellipsis="true" />
                    <a-table-column title="状态" width="80">
                      <template #default="{ record: row }">
                        <a-tag :color="row.status === 'ok' ? 'success' : 'error'">{{ row.status }}</a-tag>
                      </template>
                    </a-table-column>
                  </a-table>
                  <div class="chart-sub-title" style="margin-top:10px">硬件事件日志（SEL，新→旧）</div>
                  <a-table :data-source="(ipmi.snapshot.sel || []).slice().reverse()" :row-key="row => row.record || row.event" size="small" :scroll="{ y: 260 }" :pagination="false">
                    <a-table-column data-index="record" title="#" width="56" />
                    <a-table-column title="时间" width="150">
                      <template #default="{ record: row }"><span class="mono">{{ row.date }} {{ row.time }}</span></template>
                    </a-table-column>
                    <a-table-column data-index="event" title="事件" width="180" :ellipsis="true" />
                  </a-table>
                  <a-empty v-if="!(ipmi.snapshot.sel || []).length" description="无 SEL 事件" />
                  <div class="chart-sub-title" style="margin-top:10px">FRU 资产信息</div>
                  <a-descriptions v-for="(f, i) in ipmi.snapshot.fru" :key="i" :column="1" bordered size="small" style="margin-bottom:8px">
                    <a-descriptions-item v-for="(v, k) in f" :key="k" :label="k">{{ v }}</a-descriptions-item>
                  </a-descriptions>
                  <a-empty v-if="!(ipmi.snapshot.fru || []).length" description="无 FRU 信息" />
                </a-col>
              </a-row>
            </template>
            <a-empty v-else description="等待首次 IPMI 采集（每 5 分钟一次）" />
          </a-tab-pane>

          <a-tab-pane tab="台账" key="notes">
            <div v-if="isAdmin" style="display:flex;gap:8px;margin-bottom:12px">
              <a-select v-model:value="noteKind" size="small" style="width:110px">
                <a-select-option value="note" label="备注" />
                <a-select-option value="maintenance" label="维护" />
                <a-select-option value="repair" label="维修" />
              </a-select>
              <a-input v-model:value="noteInput" size="small" placeholder="记录维护/维修信息，如：更换 /dev/nvme1，SN xxx" style="flex:1" @keyup.enter="addNote" />
              <a-button size="small" type="primary" :loading="noteSaving" @click="addNote">记录</a-button>
            </div>
            <a-table :data-source="notes" row-key="id" size="small" :scroll="{ y: 320 }" :pagination="false">
              <a-table-column title="时间" width="160">
                <template #default="{ record: row }"><span class="mono">{{ fmtTime(row.ts) }}</span></template>
              </a-table-column>
              <a-table-column title="类型" width="80">
                <template #default="{ record: row }">
                  <a-tag :color="row.kind === 'repair' ? 'error' : row.kind === 'maintenance' ? 'warning' : 'default'">
                    {{ { note: '备注', maintenance: '维护', repair: '维修' }[row.kind] || row.kind }}
                  </a-tag>
                </template>
              </a-table-column>
              <a-table-column data-index="username" title="操作人" width="100" />
              <a-table-column data-index="content" title="内容" width="300" :ellipsis="true" />
            </a-table>
            <a-empty v-if="!notes.length" description="暂无记录" />
          </a-tab-pane>

          <a-tab-pane tab="采集健康" key="collect">
            <template v-if="collectHealth">
              <a-row :gutter="16">
                <a-col :xs="12" :lg="6"><div class="stat-card" style="padding:12px;border:1px solid var(--cborder);border-radius:8px">
                  <div class="stat-value" :style="{ color: collectHealth.success_rate >= 95 ? 'var(--cgreen)' : 'var(--cred)' }">{{ collectHealth.success_rate }}%</div>
                  <div class="stat-label">24h 采集成功率</div>
                </div></a-col>
                <a-col :xs="12" :lg="6"><div class="stat-card" style="padding:12px;border:1px solid var(--cborder);border-radius:8px">
                  <div class="stat-value">{{ collectHealth.ok }}/{{ collectHealth.total }}</div>
                  <div class="stat-label">成功/总次数</div>
                </div></a-col>
                <a-col :xs="12" :lg="6"><div class="stat-card" style="padding:12px;border:1px solid var(--cborder);border-radius:8px">
                  <div class="stat-value">{{ collectHealth.avg_ssh_latency }}s</div>
                  <div class="stat-label">平均 SSH 延迟</div>
                </div></a-col>
                <a-col :xs="12" :lg="6"><div class="stat-card" style="padding:12px;border:1px solid var(--cborder);border-radius:8px">
                  <div class="stat-value">{{ collectHealth.avg_duration }}s</div>
                  <div class="stat-label">平均采集耗时</div>
                </div></a-col>
              </a-row>
              <template v-if="Object.keys(collectHealth.errors || {}).length">
                <div class="chart-sub-title" style="margin-top:14px;color:var(--cyellow)">错误分布</div>
                <a-table :data-source="Object.entries(collectHealth.errors).map(([code, n]) => ({ code, n }))" row-key="code" size="small" :scroll="{ y: 200 }" :pagination="false">
                  <a-table-column data-index="code" title="错误码" width="220" class-name="mono" />
                  <a-table-column data-index="n" title="次数" width="120" />
                </a-table>
              </template>
              <div v-else style="margin-top:12px;color:var(--csub);font-size:12px">24 小时内无采集错误</div>
            </template>
            <a-empty v-else description="暂无数据" />
          </a-tab-pane>
        </a-tabs>
      </a-card>
    </template>
    <a-alert v-else-if="loadError" type="error" show-icon :closable="false" style="margin-bottom:14px"
              :message="`数据加载失败：${loadError}`" />
    <a-empty v-else-if="!loading" description="暂无采集数据，请等待采集周期或点击「立即采集」" />
  </div>
  </a-spin>

  <a-modal
    v-model:open="statusModalOpen"
    title="变更服务器状态"
    :confirm-loading="actionSaving"
    ok-text="确认变更"
    cancel-text="取消"
    @ok="submitStatus"
  >
    <a-alert
      :message="`将服务器状态切换为「${statusCn[pendingStatus] || pendingStatus}」`"
      type="info"
      show-icon
      style="margin-bottom:16px"
    />
    <a-form layout="vertical">
      <a-form-item label="变更原因" required>
        <a-textarea
          v-model:value="statusReason"
          :rows="3"
          :maxlength="500"
          show-count
          placeholder="例如：更换 3 号 GPU / 系统重装"
        />
      </a-form-item>
    </a-form>
  </a-modal>

  <a-modal
    v-model:open="killModalOpen"
    title="敏感操作再次认证"
    :confirm-loading="actionSaving"
    :ok-button-props="{ danger: true }"
    ok-text="发送信号"
    cancel-text="取消"
    :cancel-button-props="{ disabled: actionSaving }"
    :closable="!actionSaving"
    :mask-closable="!actionSaving"
    :keyboard="!actionSaving"
    @ok="submitKill"
    @cancel="clearProcessAction"
  >
    <a-alert
      :message="`将向进程 ${pendingProcess?.pid || '—'} 发送 ${pendingSignal}`"
      type="warning"
      show-icon
      style="margin-bottom:16px"
    />
    <a-form layout="vertical">
      <a-form-item label="当前管理员密码" required>
        <a-input-password v-model:value="reauthPassword" placeholder="请输入当前密码" @keyup.enter="submitKill" />
      </a-form-item>
    </a-form>
  </a-modal>

  <a-modal
    v-model:open="reniceModalOpen"
    title="调整进程优先级"
    :confirm-loading="actionSaving"
    ok-text="确认调整"
    cancel-text="取消"
    :cancel-button-props="{ disabled: actionSaving }"
    :closable="!actionSaving"
    :mask-closable="!actionSaving"
    :keyboard="!actionSaving"
    @ok="submitRenice"
    @cancel="clearProcessAction"
  >
    <a-form layout="vertical">
      <a-form-item :label="`进程 ${pendingProcess?.pid || '—'} 的 nice 值`" required>
        <a-input-number v-model:value="reniceValue" :min="-20" :max="19" :precision="0" :step="1" style="width:100%" />
      </a-form-item>
      <a-form-item label="当前管理员密码" required>
        <a-input-password v-model:value="reauthPassword" placeholder="请输入当前密码" @keyup.enter="submitRenice" />
      </a-form-item>
    </a-form>
  </a-modal>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { App as AntApp } from 'ant-design-vue'
import { ReloadOutlined } from '@ant-design/icons-vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import api from '../api'
import { isAdminSession, useLatestOnly } from '../composables'
import RateUnitPicker from '../components/RateUnitPicker.vue'
import { diskAxisFormatter, fmtDiskRate, fmtDuration, fmtFreq, fmtNetRate, fmtSizeMB, fmtTime, fmtUptime, netAxisFormatter, parseTime, pct } from '../format'
import { chartTheme } from '../theme'

use([CanvasRenderer, LineChart, GridComponent, LegendComponent, TooltipComponent])

const { message } = AntApp.useApp()
const route = useRoute()
// reactive: the router reuses this component when navigating between servers
const serverId = computed(() => Number(route.params.id))
const invalidId = computed(() => !Number.isFinite(serverId.value) || serverId.value <= 0)
const applyHistory = useLatestOnly()
const applyProcs = useLatestOnly()
let requestEpoch = 0
let disposed = false
let mainInflight = null
let procsInflight = null
let procsToken = 0
const loading = ref(false)
const server = ref(null)
const isGpuServer = computed(() => (server.value?.server_type ?? 'gpu') === 'gpu')
const metric = ref(null)
const loadError = ref('')
let _lastFailToast = 0
function loadFail(e) {
  // one gentle toast per 30s — polling failures must not spam
  const now = Date.now()
  if (now - _lastFailToast < 30000) return
  _lastFailToast = now
  if (e?.response?.status === 401) return  // global interceptor handles logout
  message.warning(e?.friendlyMessage || '部分数据加载失败')
}

const unitEpoch = ref(0)
function onUnitChange() { unitEpoch.value++ }
const history = ref([])
const historyError = ref('')
const hours = ref(3)

const procs = ref([])
const procsLoading = ref(false)
const procSort = ref('cpu')
const procFilter = ref('')
let liveTimer = null
let entTimer = null
let mainTimer = null
let killTimer = null

const statusCn = { active: '运行中', maintenance: '维护中', drained: '已排空', rma: '返修中' }

function scrollToSection(id) {
  document.getElementById(id)?.scrollIntoView({
    behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
    block: 'start',
  })
}

// ---- enterprise panels ----
const entTab = ref('events')
const health = ref(null)
const riskGpus = ref([])
const events = ref([])
const evSev = ref('')
const slowHealth = ref({})
const inventory = ref({})
const notes = ref([])
const noteInput = ref('')
const noteKind = ref('note')
const collectHealth = ref(null)
const statusModalOpen = ref(false)
const killModalOpen = ref(false)
const reniceModalOpen = ref(false)
const actionSaving = ref(false)
const pendingStatus = ref('')
const statusReason = ref('')
const pendingProcess = ref(null)
const pendingSignal = ref('TERM')
const reauthPassword = ref('')
const reniceValue = ref(10)
const ipmi = ref(null)
const panelErrors = ref({})
const panelUpdated = ref({})
const panelLoading = ref({})
const ENTERPRISE_TTL_MS = 60000
const adminEnterpriseGroups = new Set(['slow-health', 'inventory', 'ipmi'])
const enterpriseInflight = new Map()
const enterpriseTokens = new Map()
function enterpriseGroup(tab) {
  return tab === 'nvme' || tab === 'services' ? 'slow-health' : tab
}

function canLoadPanel(group) {
  return !invalidId.value && !document.hidden && !disposed &&
    (!adminEnterpriseGroups.has(group) || isAdmin.value)
}

// Deduplicate identical polls, but allow a changed filter to supersede a slow request.
// Scope every result to the route and component lifetime, including failures.
async function loadPanel(group, path, apply, params) {
  if (!canLoadPanel(group)) return false
  const requestedServerId = serverId.value
  const epoch = requestEpoch
  const key = JSON.stringify([requestedServerId, params])
  const existing = enterpriseInflight.get(group)
  if (existing?.key === key) return existing.promise
  const token = (enterpriseTokens.get(group) || 0) + 1
  enterpriseTokens.set(group, token)
  const isCurrent = () => !disposed && epoch === requestEpoch && requestedServerId === serverId.value && enterpriseTokens.get(group) === token
  panelLoading.value[group] = true
  const pending = Promise.resolve().then(async () => {
    try {
      if (!isCurrent()) return false
      const { data } = await api.get(`/servers/${requestedServerId}/${path}`, params ? { params } : undefined)
      if (!isCurrent()) return false
      apply(data)
      panelUpdated.value[group] = Date.now()
      delete panelErrors.value[group]
      return true
    } catch (e) {
      if (!isCurrent()) return false
      panelErrors.value[group] = e?.friendlyMessage || '读取失败'
      loadFail(e)
      return false
    } finally {
      if (isCurrent()) panelLoading.value[group] = false
      if (enterpriseInflight.get(group)?.promise === pending) enterpriseInflight.delete(group)
    }
  })
  enterpriseInflight.set(group, { key, promise: pending })
  return pending
}

function loadOverview() {
  return loadPanel('overview', 'overview', (data) => {
    health.value = data.health
    riskGpus.value = data.gpus || []
  })
}
function loadEvents() {
  return loadPanel('events', 'kernel-events', (data) => { events.value = data }, { hours: 24, severity: evSev.value })
}
function loadSlowHealth() {
  return loadPanel('slow-health', 'slow-health', (data) => { slowHealth.value = data || {} })
}
function loadIpmi() {
  return loadPanel('ipmi', 'ipmi/latest', (data) => { ipmi.value = data })
}
function loadInventory() {
  return loadPanel('inventory', 'inventory', (data) => { inventory.value = data || {} })
}
function loadNotes() {
  return loadPanel('notes', 'notes', (data) => { notes.value = data || [] })
}
function loadCollectHealth() {
  return loadPanel('collect', 'collect-health', (data) => { collectHealth.value = data })
}

async function ensureEnterpriseTab(tab, force = false) {
  const group = enterpriseGroup(tab)
  if (!canLoadPanel(group)) return false
  if (!force && group !== 'events' && !panelErrors.value[group] &&
      Date.now() - (panelUpdated.value[group] || 0) < ENTERPRISE_TTL_MS) return true
  const loaders = {
    events: loadEvents,
    'slow-health': loadSlowHealth,
    inventory: loadInventory,
    notes: loadNotes,
    collect: loadCollectHealth,
    ipmi: loadIpmi,
  }
  const loader = loaders[group]
  return loader ? loader() : false
}
function loadEnterprise(force = false) {
  return Promise.allSettled([loadOverview(), ensureEnterpriseTab(entTab.value, force)])
}
function refreshAll() {
  return Promise.allSettled([load(), loadProcs(), loadEnterprise(true)])
}

function onVisibilityChange() {
  if (!document.hidden) refreshAll()
}

function refreshNotesAfterWrite() {
  // A read started before a mutation must not satisfy the post-mutation refresh.
  enterpriseInflight.delete('notes')
  return loadNotes()
}

async function updateStatus(status, reason = '') {
  if (actionSaving.value || !isAdmin.value) return false
  const epoch = requestEpoch
  actionSaving.value = true
  try {
    const { data } = await api.post(`/servers/${serverId.value}/status`, { status, reason })
    if (disposed || epoch !== requestEpoch) return false
    server.value = data
    statusModalOpen.value = false
    statusReason.value = ''
    message.success(`已切换为「${statusCn[status]}」`)
    refreshNotesAfterWrite()
    return true
  } catch (e) {
    if (!disposed && epoch === requestEpoch) message.error(e?.friendlyMessage || '状态变更失败')
    return false
  } finally {
    actionSaving.value = false
  }
}

function onStatusMenu({ key }) {
  if (actionSaving.value) return
  if (key === 'active') {
    updateStatus(key)
    return
  }
  pendingStatus.value = key
  statusReason.value = ''
  statusModalOpen.value = true
}

function submitStatus() {
  if (!statusReason.value.trim()) {
    message.warning('请填写变更原因')
    return
  }
  updateStatus(pendingStatus.value, statusReason.value.trim())
}

const noteSaving = ref(false)
async function addNote() {
  if (noteSaving.value || !isAdmin.value || !noteInput.value.trim()) return
  const epoch = requestEpoch
  noteSaving.value = true
  try {
    await api.post(`/servers/${serverId.value}/notes`, { kind: noteKind.value, content: noteInput.value.trim() })
    if (disposed || epoch !== requestEpoch) return
    noteInput.value = ''
    refreshNotesAfterWrite()
  } catch (e) {
    if (!disposed && epoch === requestEpoch) message.error(e.friendlyMessage || '记录失败')
  } finally {
    noteSaving.value = false
  }
}

const serviceRows = computed(() =>
  Object.entries(slowHealth.value.services || {}).map(([name, state]) => ({ name, state })))
const physicalNics = computed(() =>
  (inventory.value.nics || []).filter(n =>
    n.mac && n.mac !== '00:00:00:00:00:00' &&
    !/^(veth|br-|docker|virbr|flannel|cali|tun|tap|cni|kube)/.test(n.name)
  ).slice(0, 12))

function fmtUnits(units) {
  if (units === undefined || units === null) return '—'
  const gb = units * 512000 / 1e9
  if (gb >= 1000) return (gb / 1000).toFixed(2) + 'TB'
  return gb.toFixed(1) + 'GB'
}
function gpuRisk(uuid) {
  return riskGpus.value.find(r => r.uuid === uuid) || { risk: 0, risk_label: '健康' }
}
function throttleShort(reasons) {
  const map = {
    SW_POWER_CAP: '功耗墙', HW_SLOWDOWN: '硬件降速', HW_THERMAL_SLOWDOWN: '热降频',
    SW_THERMAL_SLOWDOWN: '热降频', HW_POWER_BRAKE_SLOWDOWN: '电源制动', GPU_IDLE: '空闲',
    APPLICATIONS_CLOCKS: '频率限制', SYNC_BOOST: '同步加速',
  }
  return [...new Set(reasons.map(r => map[r] || r))].join('/')
}
function overallTag(s) { return s === 'critical' ? 'error' : s === 'warning' ? 'warning' : s === 'ok' ? 'success' : 'default' }
function overallLabel(s) { return { critical: '危急', warning: '警告', ok: '健康', unknown: '未知' }[s] || s }
function statusLabel(s) { return { critical: '危急', warning: '警告', ok: '正常' }[s] || s }

const isAdmin = computed(() => isAdminSession())
const FAULT_LABELS = {
  SSH_AUTH_FAILED: '认证失败', SSH_HOSTKEY_CHANGED: '主机密钥变更', SSH_DNS_FAILED: 'DNS 失败',
  SSH_REFUSED: '连接拒绝', SSH_DOWN: 'SSH 不可达', COLLECT_TIMEOUT: '采集超时', COLLECT_FAILED: '采集失败',
  CRED_DECRYPT_FAILED: '凭据需重新录入',
}
function faultLabel(code) { return FAULT_LABELS[code] || code }
const metricErrorText = computed(() => {
  if (!metric.value) return ''
  if (isAdmin.value) return metric.value.error || faultLabel(metric.value.error_code)
  const code = metric.value.error_code
  return (code && code !== 'OK') ? faultLabel(code) : '采集异常'
})
const gpus = computed(() => metric.value?.gpus || [])
const cores = computed(() => metric.value?.cores || [])

const memPct = computed(() => pct(metric.value?.mem_total_mb ? metric.value.mem_used_mb / metric.value.mem_total_mb * 100 : 0))
const diskPct = computed(() => pct(metric.value?.disk_total_gb ? metric.value.disk_used_gb / metric.value.disk_total_gb * 100 : 0))

const filteredProcs = computed(() => {
  if (!procFilter.value) return procs.value
  const k = procFilter.value.toLowerCase()
  return procs.value.filter(p =>
    String(p.pid).includes(k) ||
    (p.user || '').toLowerCase().includes(k) ||
    (p.command || '').toLowerCase().includes(k)
  )
})

function gpuMemPct(g) {
  return pct(g.mem_total_mb ? g.mem_used_mb / g.mem_total_mb * 100 : 0)
}

function utilColor(v) {
  if (v >= 90) return '#ff4d4f'
  if (v >= 70) return '#faad14'
  return '#52c41a'
}

function tempColor(t) {
  if (t >= 80) return '#ff4d4f'
  if (t >= 70) return '#faad14'
  return '#52c41a'
}

function coreClass(util) {
  if (util >= 90) return 'core-crit'
  if (util >= 70) return 'core-warn'
  if (util >= 25) return 'core-ok'
  return 'core-idle'
}

const _axisTime = computed(() => {
  const p = (n) => String(n).padStart(2, '0')
  return history.value.map((t) => {
    const d = parseTime(t.time)
    return hours.value >= 24 ? `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}` : `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
  })
})

const _darkBase = computed(() => {
  const T = chartTheme.value
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', backgroundColor: T.tooltipBg, borderColor: T.tooltipBorder, textStyle: { color: T.tooltipText } },
    legend: { textStyle: { color: T.label }, top: 0, icon: 'roundRect', itemWidth: 14, itemHeight: 4 },
    grid: { left: 12, right: 20, top: 32, bottom: 28, containLabel: true },
    dataZoom: [{ type: 'inside' }],
  }
})

const _mk = (name, data, color, extra = {}) => ({
  name, type: 'line', showSymbol: false, smooth: true, data, sampling: 'lttb',
  lineStyle: { width: 2, color }, itemStyle: { color },
  areaStyle: { opacity: 0.1, color }, ...extra,
})

const gpuChartOption = computed(() => ({
  ..._darkBase.value,
  xAxis: { type: 'category', data: _axisTime.value, axisLine: { lineStyle: { color: chartTheme.value.axisLine } }, axisLabel: { color: chartTheme.value.label } },
  yAxis: [
    { type: 'value', max: 100, axisLabel: { color: chartTheme.value.label }, splitLine: { lineStyle: { color: chartTheme.value.splitLine } } },
    { type: 'value', axisLabel: { color: chartTheme.value.label }, splitLine: { show: false } },
  ],
  series: [
    _mk('利用率 %', history.value.map(h => h.gpu_util), chartTheme.value.cyan),
    _mk('显存 %', history.value.map(h => h.gpu_mem_percent), chartTheme.value.purple),
    _mk('温度 °C', history.value.map(h => h.gpu_temp), chartTheme.value.yellow, { yAxisIndex: 1 }),
    _mk('功耗 W', history.value.map(h => h.gpu_power), chartTheme.value.red, { yAxisIndex: 1 }),
  ],
}))

const sysChartOption = computed(() => ({
  ..._darkBase.value,
  xAxis: { type: 'category', data: _axisTime.value, axisLine: { lineStyle: { color: chartTheme.value.axisLine } }, axisLabel: { color: chartTheme.value.label } },
  yAxis: [
    { type: 'value', max: 100, axisLabel: { color: chartTheme.value.label }, splitLine: { lineStyle: { color: chartTheme.value.splitLine } } },
    { type: 'value', axisLabel: { color: chartTheme.value.label }, splitLine: { show: false } },
  ],
  series: [
    _mk('CPU %', history.value.map(h => h.cpu_percent), chartTheme.value.green),
    _mk('内存 %', history.value.map(h => h.mem_percent), chartTheme.value.cyan),
    _mk('Swap %', history.value.map(h => h.swap_percent ?? 0), chartTheme.value.yellow),
    _mk('每核负载', history.value.map(h => h.load_per_core ?? 0), chartTheme.value.purple, { yAxisIndex: 1 }),
  ],
}))

const netChartOption = computed(() => ({
  ..._darkBase.value,
  unitEpoch: unitEpoch.value,
  xAxis: { type: 'category', data: _axisTime.value, axisLine: { lineStyle: { color: chartTheme.value.axisLine } }, axisLabel: { color: chartTheme.value.label } },
  yAxis: [{ type: 'value', axisLabel: { color: chartTheme.value.label, formatter: netAxisFormatter() }, splitLine: { lineStyle: { color: chartTheme.value.splitLine } } }],
  series: [
    _mk('接收', history.value.map(h => h.net_rx_bps ?? 0), chartTheme.value.cyan),
    _mk('发送', history.value.map(h => h.net_tx_bps ?? 0), chartTheme.value.purple),
  ],
}))

const diskChartOption = computed(() => ({
  ..._darkBase.value,
  unitEpoch: unitEpoch.value,
  xAxis: { type: 'category', data: _axisTime.value, axisLine: { lineStyle: { color: chartTheme.value.axisLine } }, axisLabel: { color: chartTheme.value.label } },
  yAxis: [{ type: 'value', axisLabel: { color: chartTheme.value.label, formatter: diskAxisFormatter() }, splitLine: { lineStyle: { color: chartTheme.value.splitLine } } }],
  series: [
    _mk('读', history.value.map(h => h.disk_read_bps ?? 0), chartTheme.value.yellow),
    _mk('写', history.value.map(h => h.disk_write_bps ?? 0), chartTheme.value.red),
  ],
}))

async function load() {
  if (invalidId.value || document.hidden || disposed) return
  if (mainInflight) return mainInflight
  const requestedServerId = serverId.value
  const epoch = requestEpoch
  const isCurrent = () => !disposed && epoch === requestEpoch && requestedServerId === serverId.value
  loading.value = !metric.value
  const pending = Promise.resolve().then(async () => {
    try {
      if (!isCurrent()) return
      const [serverList, latest] = await Promise.allSettled([
        api.get('/servers').then(r => r.data),
        api.get(`/metrics/server/${requestedServerId}/latest`).then(r => r.data),
        loadHistory(),
      ])
      if (!isCurrent()) return
      if (serverList.status === 'fulfilled') server.value = (serverList.value || []).find(s => s.id === requestedServerId) || null
      if (latest.status === 'fulfilled') {
        metric.value = latest.value
        loadError.value = ''
      } else {
        loadError.value = latest.reason?.friendlyMessage || '加载失败'
      }
    } catch (e) {
      if (isCurrent()) loadError.value = e?.friendlyMessage || '加载失败'
    } finally {
      if (isCurrent()) loading.value = false
      if (mainInflight === pending) mainInflight = null
    }
  })
  mainInflight = pending
  return pending
}

async function loadHistory() {
  if (invalidId.value || document.hidden || disposed) return
  const requestedServerId = serverId.value
  const epoch = requestEpoch
  const isCurrent = () => !disposed && epoch === requestEpoch && requestedServerId === serverId.value
  try {
    await applyHistory(
      api.get(`/metrics/server/${requestedServerId}/history?hours=${hours.value}`).then(r => r.data),
      (data) => {
        if (!isCurrent()) return
        history.value = data || []
        historyError.value = ''
      }
    )
  } catch (e) {
    if (isCurrent()) historyError.value = e?.friendlyMessage || '读取失败，请重试'
  }
}

async function loadProcs() {
  if (invalidId.value || document.hidden || disposed || !isAdmin.value) return
  const requestedServerId = serverId.value
  const requestedSort = procSort.value
  const epoch = requestEpoch
  const key = `${epoch}:${requestedServerId}:${requestedSort}`
  if (procsInflight?.key === key) return procsInflight.promise
  const token = ++procsToken
  const isCurrent = () => !disposed && epoch === requestEpoch && requestedServerId === serverId.value && token === procsToken
  procsLoading.value = true
  const pending = Promise.resolve().then(async () => {
    try {
      if (!isCurrent()) return
      await applyProcs(
        api.post(`/metrics/server/${requestedServerId}/processes?sort=${requestedSort}`).then(r => r.data),
        (data) => { if (isCurrent()) procs.value = data.processes || [] }
      )
    } catch (e) {
      if (isCurrent()) message.error(e?.friendlyMessage || '获取进程失败')
    } finally {
      if (isCurrent()) procsLoading.value = false
      if (procsInflight?.promise === pending) procsInflight = null
    }
  })
  procsInflight = { key, promise: pending }
  return pending
}

function openKill(row, signal) {
  if (actionSaving.value || !isAdmin.value) return
  pendingProcess.value = row
  pendingSignal.value = signal
  reauthPassword.value = ''
  killModalOpen.value = true
}

async function submitKill() {
  if (actionSaving.value || !killModalOpen.value || !isAdmin.value) return
  if (!reauthPassword.value) {
    message.warning('请输入当前管理员密码')
    return
  }
  const row = pendingProcess.value
  if (!row?.start_ticks) {
    message.error('进程信息已失效，请刷新后重试')
    return
  }
  const epoch = requestEpoch
  actionSaving.value = true
  try {
    const { data } = await api.post(`/metrics/server/${serverId.value}/processes/action`, {
      action: 'kill',
      pid: row.pid,
      start_ticks: row.start_ticks,
      signal: pendingSignal.value,
      reauth_password: reauthPassword.value,
    })
    if (disposed || epoch !== requestEpoch) return
    killModalOpen.value = false
    reauthPassword.value = ''
    pendingProcess.value = null
    message.success(`已发送 ${pendingSignal.value} 到 ${row.pid}: ${data.message}`)
    clearTimeout(killTimer)
    killTimer = setTimeout(loadProcs, 800)
  } catch (e) {
    if (!disposed && epoch === requestEpoch) message.error(e?.friendlyMessage || '进程操作失败')
  } finally {
    actionSaving.value = false
  }
}

function openRenice(row) {
  if (actionSaving.value || !isAdmin.value) return
  pendingProcess.value = row
  reniceValue.value = 10
  reauthPassword.value = ''
  reniceModalOpen.value = true
}

async function submitRenice() {
  if (actionSaving.value || !reniceModalOpen.value || !isAdmin.value) return
  const value = reniceValue.value
  const nice = Number(value)
  if (value === null || value === undefined || value === '' || !Number.isInteger(nice) || nice < -20 || nice > 19) {
    message.warning('nice 值必须是 -20 到 19 之间的整数')
    return
  }
  if (!reauthPassword.value) {
    message.warning('请输入当前管理员密码')
    return
  }
  const row = pendingProcess.value
  if (!row?.start_ticks) {
    message.error('进程信息已失效，请刷新后重试')
    return
  }
  const epoch = requestEpoch
  actionSaving.value = true
  try {
    await api.post(`/metrics/server/${serverId.value}/processes/action`, {
      action: 'renice',
      pid: row.pid,
      start_ticks: row.start_ticks,
      nice,
      reauth_password: reauthPassword.value,
    })
    if (disposed || epoch !== requestEpoch) return
    reniceModalOpen.value = false
    reauthPassword.value = ''
    pendingProcess.value = null
    message.success(`已 renice ${row.pid} -> ${nice}`)
  } catch (e) {
    if (!disposed && epoch === requestEpoch) message.error(e?.friendlyMessage || '进程操作失败')
  } finally {
    actionSaving.value = false
  }
}

function clearProcessAction() {
  if (actionSaving.value) return
  reauthPassword.value = ''
  pendingProcess.value = null
  killModalOpen.value = false
  reniceModalOpen.value = false
}

function startTimers() {
  stopTimers()
  liveTimer = setInterval(loadProcs, 15000)
  entTimer = setInterval(() => loadEnterprise(), ENTERPRISE_TTL_MS)
  mainTimer = setInterval(load, 30000)
}
function stopTimers() {
  clearInterval(liveTimer); clearInterval(entTimer); clearInterval(mainTimer)
  liveTimer = entTimer = mainTimer = null
}

// re-initialize everything when the route param changes (component is reused)
watch(serverId, () => {
  requestEpoch++
  mainInflight = null; procsInflight = null
  clearTimeout(killTimer)
  reauthPassword.value = ''; pendingProcess.value = null
  killModalOpen.value = false; reniceModalOpen.value = false; statusModalOpen.value = false
  metric.value = null; history.value = []; procs.value = []; events.value = []
  server.value = null; health.value = null; riskGpus.value = []; slowHealth.value = {}
  inventory.value = {}; notes.value = []; collectHealth.value = null; ipmi.value = null
  loadError.value = ''; historyError.value = ''; procsLoading.value = false
  panelUpdated.value = {}; panelErrors.value = {}; panelLoading.value = {}
  enterpriseInflight.clear(); enterpriseTokens.clear()
  load(); loadProcs(); loadEnterprise(); startTimers()
})

watch(entTab, (tab) => ensureEnterpriseTab(tab))

onMounted(() => {
  if (invalidId.value) return
  document.addEventListener('visibilitychange', onVisibilityChange)
  load()
  loadProcs()
  loadEnterprise()
  startTimers()
})
onUnmounted(() => {
  disposed = true
  requestEpoch++
  reauthPassword.value = ''
  document.removeEventListener('visibilitychange', onVisibilityChange)
  stopTimers(); clearTimeout(killTimer)
})
</script>

<style scoped>
.health-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 10px;
}
.detail-toolbar { justify-content: space-between; }
.detail-toolbar :deep(.ant-page-header) { min-width: 0; flex: 1; padding: 0; }
.detail-toolbar :deep(.ant-page-header-heading-title) { min-width: 0; white-space: normal; overflow-wrap: anywhere; font-size: 20px; }
.detail-toolbar-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.inline-link { height: auto; padding: 0 3px; }
.detail-jump-nav {
  position: sticky;
  top: 0;
  z-index: 8;
  display: flex;
  align-items: center;
  gap: 4px;
  width: max-content;
  max-width: 100%;
  margin: 0 0 4px;
  padding: 5px;
  overflow-x: auto;
  border: 1px solid var(--cborder);
  border-radius: 9px;
  background: color-mix(in srgb, var(--cpanel) 92%, transparent);
  box-shadow: 0 8px 24px -20px rgba(15, 23, 42, .8);
  backdrop-filter: blur(12px);
}
.detail-jump-nav button {
  padding: 6px 11px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--csub);
  cursor: pointer;
  font-size: 12px;
  white-space: nowrap;
}
.detail-jump-nav button:hover { background: var(--ctable-hover); color: var(--cprimary); }
.detail-section { scroll-margin-top: 52px; }
.detail-kpis { row-gap: 16px; }
.detail-kpi-card { min-height: 128px; }
.detail-kpi-card .stat-sub { overflow-wrap: anywhere; }
.gpu-card { margin-bottom: 16px; }
.detail-capacity-value { white-space: normal; font-size: clamp(18px, 1.8vw, 25px); }
.detail-capacity-value i { margin: 0 3px; color: var(--csub); font-size: .72em; font-style: normal; }
.detail-card-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.process-card-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
.gpu-card-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; margin-bottom: 8px; }
.gpu-card-head > b { min-width: 0; overflow-wrap: anywhere; }
.gpu-card-tags { display: flex; flex: 0 0 auto; gap: 6px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
.health-cat {
  border: 1px solid var(--cborder);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--cpanel2);
}
.health-cat.st-ok { border-left: 3px solid var(--cgreen); }
.health-cat.st-warning { border-left: 3px solid var(--cyellow); }
.health-cat.st-critical { border-left: 3px solid var(--cred); }
.health-cat-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.health-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--csub);
}
.st-ok .health-dot { background: var(--cgreen); }
.st-warning .health-dot { background: var(--cyellow); }
.st-critical .health-dot { background: var(--cred); }
.health-status { margin-left: auto; font-size: 11px; color: var(--csub); }
.health-detail { font-size: 11px; color: var(--csub); margin-top: 4px; line-height: 1.5; }
.health-children { margin-top: 8px; display: flex; flex-direction: column; gap: 6px; }
.health-sub {
  border-top: 1px dashed var(--cborder);
  padding-top: 6px;
  font-size: 12px;
  display: grid;
  grid-template-columns: minmax(48px, auto) minmax(0, 1fr);
  gap: 6px;
  align-items: baseline;
}
.health-sub .health-detail { margin-top: 0; overflow-wrap: anywhere; }
.health-sub.st-ok { color: var(--ctext); }
.health-sub.st-warning { color: var(--cyellow); }
.health-sub.st-critical { color: var(--cred); }
.enterprise-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.enterprise-toolbar__hint {
  color: var(--csub);
  font-size: 12px;
  line-height: 1.5;
}
.enterprise-event-card + .enterprise-event-card { margin-top: 9px; }
.enterprise-event-card--critical { border-left: 3px solid var(--cred); }
.enterprise-event-card--warning { border-left: 3px solid var(--cyellow); }
.enterprise-event-card--info { border-left: 3px solid var(--cprimary); }
.enterprise-event-card .mobile-data-card__title span {
  margin-left: 5px;
  color: var(--cred);
  font-size: 11px;
}
.enterprise-event-card p {
  margin: 0 0 11px;
  color: var(--ctext);
  font-size: 13px;
  line-height: 1.55;
  overflow-wrap: anywhere;
}
.enterprise-event-card__gpu { overflow-wrap: anywhere; }
.gpu-process-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 5px 10px;
  padding: 9px 10px;
  border: 1px solid var(--cborder);
  border-radius: 7px;
  background: var(--cpanel2);
  font-size: 11px;
}
.gpu-process-item + .gpu-process-item { margin-top: 7px; }
.gpu-process-item > div { display: flex; min-width: 0; gap: 7px; }
.gpu-process-item > div span { color: var(--csub); }
.gpu-process-item > p {
  grid-column: 1 / -1;
  margin: 0;
  overflow: hidden;
  color: var(--csub);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.topo-pre {
  background: var(--cpanel2);
  border: 1px solid var(--cborder);
  border-radius: 8px;
  padding: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  line-height: 1.55;
  overflow-x: auto;
  color: var(--ctext);
  margin: 0;
}
.core-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(46px, 1fr));
  gap: 6px;
}
.core-block {
  position: relative;
  height: 60px;
  border: 1px solid var(--cborder, #d9d9d9);
  border-radius: 4px;
  overflow: hidden;
  background: var(--cpanel2, #fafafa);
  cursor: default;
}
.core-fill {
  position: absolute;
  bottom: 0; left: 0; right: 0;
  transition: height .4s;
}
.core-idle .core-fill { background: color-mix(in srgb, var(--csub, rgba(0, 0, 0, 0.45)) 40%, transparent); }
.core-ok   .core-fill { background: color-mix(in srgb, var(--cgreen, #52c41a) 55%, transparent); }
.core-warn .core-fill { background: color-mix(in srgb, var(--cyellow, #faad14) 60%, transparent); }
.core-crit .core-fill { background: color-mix(in srgb, var(--cred, #ff4d4f) 65%, transparent); }
.core-text {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  color: var(--ctext, rgba(0, 0, 0, 0.88));
}

.ipmi-kpi {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  background: var(--cpanel2, #fafafa); border: 1px solid var(--cborder, #d9d9d9);
  border-radius: 8px; padding: 10px 6px;
}
.ipmi-kpi b { font-size: 17px; }
.ipmi-kpi span { font-size: 11px; color: var(--csub, rgba(0, 0, 0, 0.45)); }
@media (max-width: 768px) {
  .detail-toolbar { align-items: flex-start; }
  .detail-toolbar :deep(.ant-page-header) { flex: 1 1 100%; }
  .detail-toolbar-actions { width: 100%; }
  .detail-jump-nav { width: 100%; }
  .detail-jump-nav button { flex: 1 0 auto; }
  .health-grid { grid-template-columns: 1fr; }
  .detail-kpi-card { min-height: 112px; }
  .detail-capacity-value { font-size: 16px; line-height: 1.35; }
  .detail-card-head { align-items: flex-start; flex-direction: column; }
  .process-card-actions { width: 100%; justify-content: flex-start; }
  .process-card-actions :deep(.ant-input-affix-wrapper) { flex: 1 1 130px; width: auto !important; }
  .trend-card-head :deep(.ant-radio-group) { max-width: 100%; overflow-x: auto; white-space: nowrap; }
  .gpu-card-head { flex-direction: column; }
  .gpu-card-tags { justify-content: flex-start; }
  .gpu-card :deep(.ant-card-body) { padding: 14px; }
  .gpu-card :deep(.ant-progress) { max-width: 95px; }
  .gpu-card :deep(.ant-descriptions-item-content) { min-width: 0; overflow-wrap: anywhere; }
  .chart-box { height: 250px; }
  .chart-box-sm { height: 220px; }
  .enterprise-card :deep(.ant-tabs-nav-wrap) { padding: 0 24px; }
  .enterprise-card :deep(.ant-tabs-tab) { padding-inline: 12px; }
  .enterprise-toolbar { align-items: stretch; flex-wrap: wrap; }
  .enterprise-toolbar :deep(.ant-radio-group) { min-width: 220px; flex: 1; display: flex; flex-wrap: nowrap; }
  .enterprise-toolbar :deep(.ant-radio-button-wrapper) { flex: 1; padding-inline: 8px; text-align: center; }
  .enterprise-toolbar__hint { width: 100%; }
  .topo-pre { max-height: 260px; }
}
@media (max-width: 420px) {
  .detail-kpi-card :deep(.ant-card-body) { padding: 15px 10px; }
  .detail-kpi-card .stat-sub { white-space: normal; overflow-wrap: anywhere; }
  .core-grid { grid-template-columns: repeat(auto-fill, minmax(36px, 1fr)); }
  .core-block { height: 52px; }
}
</style>
