<template>
  <div class="cockpit" v-loading="loading">
    <el-alert v-if="invalidId" title="无效的服务器 ID" type="warning" show-icon :closable="false" style="margin-bottom:14px">
      <template #default>请返回 <el-link type="primary" @click="$router.push('/servers')">服务器列表</el-link> 重新进入。</template>
    </el-alert>
    <div class="toolbar detail-toolbar">
      <el-page-header @back="$router.push('/servers')" :content="server?.name || '...'" />
      <div class="detail-toolbar-actions">
        <el-tag v-if="metric?.status === 'ok'" type="success">正常</el-tag>
        <el-tag v-else-if="metric" type="danger">采集异常</el-tag>
        <el-tag v-if="server?.status && server.status !== 'active'" type="warning" effect="dark">
          {{ statusCn[server.status] }}<span v-if="server.status_reason">：{{ server.status_reason }}</span>
        </el-tag>
        <el-dropdown v-if="isAdmin" @command="setStatus">
          <el-button size="small">状态切换</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="active">运行中</el-dropdown-item>
              <el-dropdown-item command="maintenance">维护中</el-dropdown-item>
              <el-dropdown-item command="drained">已排空</el-dropdown-item>
              <el-dropdown-item command="rma">返修中</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button size="small" :icon="Refresh" @click="load">刷新</el-button>
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
      <el-alert v-if="metric.status !== 'ok'" :title="`采集失败: ${metric.error}`" type="error" show-icon :closable="false" style="margin-bottom:14px" />

      <!-- ===== health model tree ===== -->
      <el-card id="detail-health" v-if="health && health.categories" class="page-card detail-section" style="margin-top:14px">
        <template #header>
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span>健康模型</span>
            <el-tag :type="overallTag(health.overall)" effect="dark" size="small">{{ overallLabel(health.overall) }}</el-tag>
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
      </el-card>

      <!-- ===== btop-style overview stats ===== -->
      <el-row id="detail-resources" :gutter="14" class="detail-kpis detail-section">
        <el-col :span="6" :xs="{ span: 12 }"><el-card class="stat-card detail-kpi-card">
          <div class="stat-value" :style="{color: utilColor(metric.cpu_percent)}">{{ metric.cpu_percent }}%</div>
          <div class="stat-label">CPU ({{ metric.cpu_count }} 核 {{ fmtFreq(metric.cpu_freq_avg) }})</div>
          <div class="stat-sub">{{ metric.cpu_model || '—' }}</div>
        </el-card></el-col>
        <el-col :span="6" :xs="{ span: 12 }"><el-card class="stat-card detail-kpi-card">
          <div class="stat-value detail-capacity-value">{{ fmtSizeMB(metric.mem_used_mb) }} <i>/</i> {{ fmtSizeMB(metric.mem_total_mb) }}</div>
          <div class="stat-label">内存 ({{ memPct }}%)</div>
          <div class="stat-sub">可用 {{ fmtSizeMB(metric.mem_available_mb) }} · 缓存 {{ fmtSizeMB(metric.mem_cached_mb) }} · Swap {{ fmtSizeMB(metric.swap_used_mb) }}/{{ fmtSizeMB(metric.swap_total_mb) }}</div>
        </el-card></el-col>
        <el-col :span="6" :xs="{ span: 12 }"><el-card class="stat-card detail-kpi-card">
          <div class="stat-value detail-capacity-value">{{ (metric.disk_used_gb ?? 0).toFixed(0) }} <i>/</i> {{ (metric.disk_total_gb ?? 0).toFixed(0) }} GB</div>
          <div class="stat-label">磁盘 ({{ diskPct }}%)</div>
          <div class="stat-sub">{{ (metric.disks||[]).length }} 个挂载点</div>
        </el-card></el-col>
        <el-col :span="6" :xs="{ span: 12 }"><el-card class="stat-card detail-kpi-card">
          <div class="stat-value">{{ fmtUptime(metric.uptime_seconds) }}</div>
          <div class="stat-label">运行时长</div>
          <div class="stat-sub">{{ metric.os }} · {{ metric.kernel }}</div>
        </el-card></el-col>
      </el-row>

      <!-- ===== per-core grid (btop style) ===== -->
      <el-card class="page-card" style="margin-top:14px">
        <template #header>
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
          <el-tooltip v-for="c in cores" :key="c.id" :placement="'top'">
            <template #content>
              核心 {{ c.id }}: {{ c.util }}% · {{ fmtFreq(c.freq_mhz) }}<span v-if="c.temp"> · {{ c.temp }}°C</span>
            </template>
            <div class="core-block" :class="coreClass(c.util)">
              <div class="core-fill" :style="{height: c.util + '%'}"></div>
              <span class="core-text">{{ c.util > 60 ? c.util : (c.util > 25 ? c.util : '') }}</span>
            </div>
          </el-tooltip>
        </div>
      </el-card>

      <!-- ===== GPU cards (GPU servers only) ===== -->
      <el-card id="detail-gpus" v-if="isGpuServer" class="page-card detail-section">
        <template #header>
          <div class="detail-card-head">
            <span>GPU ({{ gpus.length }})</span>
            <span style="color:var(--csub);font-size:13px">驱动 {{ metric.gpu_driver || '—' }}</span>
          </div>
        </template>
        <el-empty v-if="!gpus.length" description="未检测到 GPU（nvidia-smi 不可用）" :image-size="60" />
        <el-row :gutter="14" v-else>
          <el-col :span="12" :xs="{ span: 24 }" v-for="g in gpus" :key="g.uuid + g.index">
            <el-card class="gpu-card" shadow="hover">
              <div class="gpu-card-head">
                <b>GPU {{ g.index }} · {{ g.name }}</b>
                <div class="gpu-card-tags">
                  <el-tag v-if="gpuRisk(g.uuid)?.risk >= 30" size="small" :type="gpuRisk(g.uuid).risk >= 60 ? 'danger' : 'warning'" effect="dark">风险 {{ gpuRisk(g.uuid).risk }}</el-tag>
                  <el-tag v-if="g.throttle_reasons?.length" size="small" type="warning" effect="plain">降频: {{ throttleShort(g.throttle_reasons) }}</el-tag>
                  <el-tag v-if="g.pstate" size="small" type="info">{{ g.pstate }}</el-tag>
                  <el-tag v-if="g.compute_mode && g.compute_mode !== 'Default'" size="small" type="warning">{{ g.compute_mode }}</el-tag>
                </div>
              </div>
              <el-descriptions :column="2" size="small" border>
                <el-descriptions-item label="利用率">
                  <el-progress :percentage="pct(g.utilization)" :color="utilColor(g.utilization)" :stroke-width="12" style="width:130px" />
                </el-descriptions-item>
                <el-descriptions-item label="显存">
                  <el-progress :percentage="gpuMemPct(g)" :color="utilColor(gpuMemPct(g))" :stroke-width="12" style="width:130px" />
                  <div class="mono" style="font-size:12px">{{ fmtSizeMB(g.mem_used_mb) }} / {{ fmtSizeMB(g.mem_total_mb) }}</div>
                </el-descriptions-item>
                <el-descriptions-item label="温度">
                  <span :style="{ color: tempColor(g.temperature) }">{{ g.temperature }}°C</span>
                  <span v-if="g.mem_temperature" style="margin-left:6px;color:var(--csub)">显存 {{ g.mem_temperature }}°C</span>
                </el-descriptions-item>
                <el-descriptions-item label="功耗">{{ g.power_draw }} / {{ g.power_limit }} W</el-descriptions-item>
                <el-descriptions-item label="核心频率">{{ g.clock_graphics ? (g.clock_graphics + ' MHz') : '—' }}<span v-if="g.clock_graphics_max" style="color:var(--csub)"> / {{ g.clock_graphics_max }}</span></el-descriptions-item>
                <el-descriptions-item label="显存频率">{{ g.clock_memory ? (g.clock_memory + ' MHz') : '—' }}<span v-if="g.clock_memory_max" style="color:var(--csub)"> / {{ g.clock_memory_max }}</span></el-descriptions-item>
                <el-descriptions-item label="PCIe">Gen{{ g.pcie_gen_current }} x{{ g.pcie_width_current }}<span v-if="g.pcie_gen_max && (g.pcie_gen_current < g.pcie_gen_max || g.pcie_width_current < g.pcie_width_max)" style="color:var(--cyellow)">（应为 Gen{{ g.pcie_gen_max }} x{{ g.pcie_width_max }}，降级!）</span><span v-else-if="g.pcie_gen_max" style="color:var(--csub)"> / Gen{{ g.pcie_gen_max }} x{{ g.pcie_width_max }}</span></el-descriptions-item>
                <el-descriptions-item label="ECC">
                  <span v-if="g.ecc_supported">{{ g.ecc_mode }} · 不可纠正 {{ g.ecc_uncorrected_volatile ?? 0 }}</span>
                  <span v-else style="color:var(--csub)">不支持（消费卡）</span>
                </el-descriptions-item>
                <el-descriptions-item label="风扇">{{ g.fan_speed }}%</el-descriptions-item>
                <el-descriptions-item label="编解码">编码 {{ g.encoder_sessions ?? 0 }} · 解码 {{ g.decoder_sessions ?? 0 }}</el-descriptions-item>
              </el-descriptions>
              <div v-if="g.processes?.length" style="margin-top:8px">
                <div style="font-size:12px;color:var(--csub);margin-bottom:4px">GPU 进程</div>
                <el-table class="desktop-only" :data="g.processes" size="small" max-height="220">
                  <el-table-column prop="pid" label="PID" width="80" />
                  <el-table-column prop="user" label="用户" width="100" show-overflow-tooltip />
                  <el-table-column label="显存" width="100">
                    <template #default="{ row }">{{ fmtSizeMB(row.mem_mb) }}</template>
                  </el-table-column>
                  <el-table-column prop="command" label="进程" min-width="140" show-overflow-tooltip />
                </el-table>
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
            </el-card>
          </el-col>
        </el-row>
      </el-card>

      <!-- ===== network & disk IO rates ===== -->
      <el-row :gutter="14">
        <el-col :span="12" :xs="{ span: 24 }">
          <el-card class="page-card">
            <template #header><div style="display:flex;justify-content:space-between;align-items:center">网络速率 (实时)<RateUnitPicker kind="net" @change="onUnitChange" /></div></template>
            <el-table :data="metric.net_ifaces || []" size="small" max-height="260">
              <el-table-column prop="iface" label="接口" min-width="110" />
              <el-table-column label="↓ 接收" width="120">
                <template #default="{ row }"><span class="mono">{{ fmtNetRate(row.rx_bps) }}</span></template>
              </el-table-column>
              <el-table-column label="↑ 发送" width="120">
                <template #default="{ row }"><span class="mono">{{ fmtNetRate(row.tx_bps) }}</span></template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!(metric.net_ifaces||[]).length" description="暂无活动接口" :image-size="40" />
          </el-card>
        </el-col>
        <el-col :span="12" :xs="{ span: 24 }">
          <el-card class="page-card">
            <template #header><div style="display:flex;justify-content:space-between;align-items:center">磁盘 IO (实时)<RateUnitPicker kind="disk" @change="onUnitChange" /></div></template>
            <el-table :data="metric.disk_io || []" size="small" max-height="260">
              <el-table-column prop="device" label="设备" min-width="90" />
              <el-table-column label="读" width="110">
                <template #default="{ row }"><span class="mono">{{ fmtDiskRate(row.read_bps) }}</span></template>
              </el-table-column>
              <el-table-column label="写" width="110">
                <template #default="{ row }"><span class="mono">{{ fmtDiskRate(row.write_bps) }}</span></template>
              </el-table-column>
              <el-table-column label="IOPS r/w" width="110">
                <template #default="{ row }"><span class="mono">{{ row.read_iops }}/{{ row.write_iops }}</span></template>
              </el-table-column>
              <el-table-column label="繁忙" width="90">
                <template #default="{ row }">{{ row.busy_percent }}%</template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!(metric.disk_io||[]).length" description="暂无活动 IO" :image-size="40" />
          </el-card>
        </el-col>
      </el-row>

      <!-- ===== disks + logged users ===== -->
      <el-row :gutter="14">
        <el-col :span="16" :xs="{ span: 24 }">
          <el-card class="page-card">
            <template #header>磁盘分区</template>
            <el-table :data="metric.disks || []" size="small" max-height="300">
              <el-table-column prop="mount" label="挂载点" min-width="130" show-overflow-tooltip />
              <el-table-column prop="device" label="设备" min-width="110" show-overflow-tooltip class-name="mono" />
              <el-table-column label="用量" width="200">
                <template #default="{ row }">
                  <el-progress :percentage="pct(row.percent)" :color="utilColor(row.percent)" :stroke-width="10" />
                </template>
              </el-table-column>
              <el-table-column label="已用/总量" width="140">
                <template #default="{ row }"><span class="mono">{{ row.used_gb.toFixed(0) }}/{{ row.total_gb.toFixed(0) }} GB</span></template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>
        <el-col :span="8" :xs="{ span: 24 }">
          <el-card class="page-card">
            <template #header>登录用户</template>
            <el-table :data="metric.users || []" size="small" max-height="260">
              <el-table-column prop="user" label="用户" width="90" />
              <el-table-column prop="from" label="来源" min-width="110" show-overflow-tooltip />
              <el-table-column prop="login" label="登录时间" min-width="110" show-overflow-tooltip />
            </el-table>
            <el-empty v-if="!(metric.users||[]).length" description="无登录用户" :image-size="40" />
          </el-card>
        </el-col>
      </el-row>

      <!-- ===== live process table (btop parity: sort/kill/renice) ===== -->
      <el-card v-if="isAdmin" class="page-card">
        <template #header>
          <div class="detail-card-head process-card-head">
            <span>进程 (实时 SSH · {{ procs.length }})</span>
            <div class="process-card-actions">
              <el-radio-group v-model="procSort" size="small" @change="loadProcs">
                <el-radio-button value="cpu">CPU</el-radio-button>
                <el-radio-button value="mem">内存</el-radio-button>
                <el-radio-button value="time">时长</el-radio-button>
              </el-radio-group>
              <el-input v-model="procFilter" placeholder="过滤..." size="small" style="width:150px" clearable />
              <el-button size="small" :icon="Refresh" @click="loadProcs">刷新</el-button>
            </div>
          </div>
        </template>
        <el-table :data="filteredProcs" size="small" max-height="420" v-loading="procsLoading"
                  :default-sort="{ prop: procSort === 'mem' ? 'rss_mb' : 'cpu', order: 'descending' }">
          <el-table-column prop="pid" label="PID" width="80" sortable />
          <el-table-column prop="user" label="用户" width="100" show-overflow-tooltip sortable />
          <el-table-column prop="cpu" label="CPU%" width="85" sortable>
            <template #default="{ row }">{{ row.cpu.toFixed(1) }}</template>
          </el-table-column>
          <el-table-column prop="rss_mb" label="内存 MB" width="95" sortable>
            <template #default="{ row }">{{ row.rss_mb.toFixed(0) }}</template>
          </el-table-column>
          <el-table-column prop="mem" label="mem%" width="80" sortable>
            <template #default="{ row }">{{ row.mem.toFixed(1) }}</template>
          </el-table-column>
          <el-table-column prop="stat" label="状态" width="70" />
          <el-table-column label="运行时长" width="95" sortable :sort-method="(a,b)=>a.etimes-b.etimes">
            <template #default="{ row }">{{ fmtDuration(row.etimes) }}</template>
          </el-table-column>
          <el-table-column prop="command" label="命令" min-width="240" show-overflow-tooltip class-name="mono" />
          <el-table-column v-if="isAdmin" label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="warning" :disabled="!row.start_ticks" @click="renice(row)">renice</el-button>
              <el-popconfirm :title="`确定 kill 进程 ${row.pid} (${(row.command || '').slice(0,30)})？`" @confirm="kill(row, 'TERM')">
                <template #reference>
                  <el-button size="small" type="danger" :disabled="!row.start_ticks">kill</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- ===== history charts (cockpit style, multi-panel) ===== -->
      <el-card id="detail-trends" class="page-card detail-section">
        <template #header>
          <div class="detail-card-head trend-card-head">
            <span>资源消耗趋势</span>
            <el-radio-group v-model="hours" size="small" @change="loadHistory">
              <el-radio-button :value="1">1小时</el-radio-button>
              <el-radio-button :value="3">3小时</el-radio-button>
              <el-radio-button :value="6">6小时</el-radio-button>
              <el-radio-button :value="24">24小时</el-radio-button>
              <el-radio-button :value="168">7天</el-radio-button>
            </el-radio-group>
          </div>
        </template>
        <el-row :gutter="14">
          <el-col v-if="isGpuServer" :span="12" :xs="{ span: 24 }">
            <div class="chart-sub-title">GPU 利用率 / 显存 / 温度 / 功耗</div>
            <v-chart v-if="history.length" :option="gpuChartOption" class="chart-box" autoresize />
            <el-empty v-else description="暂无历史数据" :image-size="50" />
          </el-col>
          <el-col :span="isGpuServer ? 12 : 24" :xs="{ span: 24 }">
            <div class="chart-sub-title">CPU / 内存 / Swap / 每核负载</div>
            <v-chart v-if="history.length" :option="sysChartOption" class="chart-box" autoresize />
            <el-empty v-else description="暂无历史数据" :image-size="50" />
          </el-col>
        </el-row>
        <el-row :gutter="14" style="margin-top:8px">
          <el-col :span="12" :xs="{ span: 24 }">
            <div class="chart-sub-title" style="display:flex;justify-content:space-between;align-items:center">网络吞吐 (接收 / 发送)<RateUnitPicker kind="net" @change="onUnitChange" /></div>
            <v-chart v-if="history.length" :option="netChartOption" class="chart-box-sm" autoresize />
          </el-col>
          <el-col :span="12" :xs="{ span: 24 }">
            <div class="chart-sub-title" style="display:flex;justify-content:space-between;align-items:center">磁盘 IO (读 / 写)<RateUnitPicker kind="disk" @change="onUnitChange" /></div>
            <v-chart v-if="history.length" :option="diskChartOption" class="chart-box-sm" autoresize />
          </el-col>
        </el-row>
      </el-card>

      <!-- ===== enterprise: events / nvme / services / inventory ===== -->
      <el-card id="detail-enterprise" class="page-card detail-section enterprise-card">
        <el-tabs v-model="entTab">
          <el-tab-pane label="内核事件" name="events">
            <div class="enterprise-toolbar">
              <el-radio-group v-model="evSev" size="small" @change="loadEvents">
                <el-radio-button value="">全部</el-radio-button>
                <el-radio-button value="critical">严重</el-radio-button>
                <el-radio-button value="warning">警告</el-radio-button>
              </el-radio-group>
              <el-button size="small" :icon="Refresh" @click="loadEvents">刷新</el-button>
              <span class="enterprise-toolbar__hint">XID / OOM / MCE / EDAC / AER / IO / NFS 错误（journalctl -k 增量）</span>
            </div>
            <el-table class="desktop-only" :data="events" size="small" max-height="320">
              <el-table-column label="时间" width="160">
                <template #default="{ row }"><span class="mono">{{ fmtTime(row.collected_at) }}</span></template>
              </el-table-column>
              <el-table-column label="级别" width="80">
                <template #default="{ row }">
                  <el-tag :type="row.severity === 'critical' ? 'danger' : row.severity === 'warning' ? 'warning' : 'info'" size="small">{{ row.severity }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="event_type" label="类型" width="170">
                <template #default="{ row }"><b class="mono">{{ row.event_type }}</b><span v-if="row.xid" class="mono" style="margin-left:6px;color:var(--cred)">Xid {{ row.xid }}</span></template>
              </el-table-column>
              <el-table-column prop="gpu_uuid" label="GPU" width="130" show-overflow-tooltip>
                <template #default="{ row }"><span class="mono" style="font-size:11px">{{ row.gpu_uuid ? row.gpu_uuid.slice(0, 16) : '' }}</span></template>
              </el-table-column>
              <el-table-column prop="message" label="消息" min-width="400" show-overflow-tooltip />
            </el-table>
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
                  <el-tag :type="row.severity === 'critical' ? 'danger' : row.severity === 'warning' ? 'warning' : 'info'" size="small">
                    {{ row.severity }}
                  </el-tag>
                </div>
                <p>{{ row.message }}</p>
                <div class="mobile-data-card__meta">
                  <span>时间</span><span>{{ fmtTime(row.collected_at) }}</span>
                  <span>GPU</span><span class="mono enterprise-event-card__gpu">{{ row.gpu_uuid || '—' }}</span>
                </div>
              </article>
            </div>
            <el-empty v-if="!events.length" description="24 小时内无内核异常事件" :image-size="50" />
          </el-tab-pane>

          <el-tab-pane label="NVMe / 存储" name="nvme">
            <el-table :data="slowHealth.nvme_smart || []" size="small" max-height="260">
              <el-table-column prop="device" label="设备" width="110" />
              <el-table-column label="温度" width="80">
                <template #default="{ row }">{{ row.temperature ? row.temperature + '°C' : '—' }}</template>
              </el-table-column>
              <el-table-column label="健康" width="90">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.critical_warning ? 'danger' : (row.available_spare !== undefined && row.available_spare <= (row.available_spare_threshold ?? 10) ? 'warning' : 'success')">
                    {{ row.critical_warning ? '异常' : '正常' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="寿命已用" width="100">
                <template #default="{ row }">{{ row.percentage_used !== undefined ? row.percentage_used + '%' : '—' }}</template>
              </el-table-column>
              <el-table-column label="介质错误" width="90">
                <template #default="{ row }"><span :style="row.media_errors ? 'color:var(--cred)' : ''">{{ row.media_errors ?? '—' }}</span></template>
              </el-table-column>
              <el-table-column label="意外断电" width="90">
                <template #default="{ row }">{{ row.unsafe_shutdowns ?? '—' }}</template>
              </el-table-column>
              <el-table-column label="读/写单元" min-width="150">
                <template #default="{ row }"><span class="mono" style="font-size:11px">{{ fmtUnits(row.data_units_read) }} / {{ fmtUnits(row.data_units_written) }}</span></template>
              </el-table-column>
            </el-table>
            <el-empty v-if="!(slowHealth.nvme_smart||[]).length" description="未检测到 NVMe 设备（或无 nvme-cli 权限）" :image-size="50" />
            <template v-if="(slowHealth.mdraid?.arrays||[]).length">
              <div class="chart-sub-title" style="margin-top:14px">RAID 阵列</div>
              <el-table :data="slowHealth.mdraid.arrays" size="small" max-height="240">
                <el-table-column prop="name" label="阵列" width="100" />
                <el-table-column prop="level" label="级别" width="80" />
                <el-table-column label="状态" width="120">
                  <template #default="{ row }">
                    <el-tag size="small" :type="row.degraded ? 'danger' : 'success'">{{ row.state }} ({{ row.active_disks }}/{{ row.total_disks }})</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="重建进度" width="120">
                  <template #default="{ row }">{{ row.recovery_percent !== undefined ? row.recovery_percent + '%' : '—' }}</template>
                </el-table-column>
              </el-table>
            </template>
            <template v-if="(slowHealth.nfs_mounts||[]).length">
              <div class="chart-sub-title" style="margin-top:14px">NFS / 共享存储挂载</div>
              <el-table :data="slowHealth.nfs_mounts" size="small" max-height="240">
                <el-table-column prop="server" label="服务器" width="140" />
                <el-table-column prop="export" label="导出路径" min-width="160" show-overflow-tooltip />
                <el-table-column prop="mount" label="挂载点" min-width="140" show-overflow-tooltip />
                <el-table-column prop="type" label="类型" width="90" />
              </el-table>
            </template>
          </el-tab-pane>

          <el-tab-pane label="服务 / MIG" name="services">
            <el-row :gutter="14">
              <el-col :span="12" :xs="{ span: 24 }">
                <div class="chart-sub-title">关键服务状态</div>
                <el-table :data="serviceRows" size="small" max-height="240">
                  <el-table-column prop="name" label="服务" width="180" />
                  <el-table-column label="状态" width="110">
                    <template #default="{ row }">
                      <el-tag size="small" :type="row.state === 'active' ? 'success' : row.state === 'inactive' ? 'info' : 'danger'">{{ row.state }}</el-tag>
                    </template>
                  </el-table-column>
                </el-table>
                <template v-if="(slowHealth.systemd_failed||[]).length">
                  <div class="chart-sub-title" style="color:var(--cred)">失败的 systemd 单元</div>
                  <el-table :data="slowHealth.systemd_failed" size="small" max-height="240">
                    <el-table-column prop="unit" label="单元" min-width="200" />
                    <el-table-column prop="active" label="状态" width="90" />
                  </el-table>
                </template>
              </el-col>
              <el-col :span="12" :xs="{ span: 24 }">
                <div class="chart-sub-title">MIG（多实例 GPU）</div>
                <el-table :data="slowHealth.mig || []" size="small" max-height="240">
                  <el-table-column prop="gpu_index" label="GPU" width="70" />
                  <el-table-column label="MIG 模式" width="120">
                    <template #default="{ row }">
                      <el-tag size="small" :type="row.mode === 'Enabled' ? 'success' : 'info'">{{ row.mode }}</el-tag>
                    </template>
                  </el-table-column>
                </el-table>
                <el-empty v-if="!(slowHealth.mig||[]).length" description="无 MIG 支持 / 未启用" :image-size="40" />
                <div class="chart-sub-title" style="margin-top:10px">IPMI / BMC 传感器</div>
                <el-table :data="(slowHealth.ipmi||[]).slice(0, 8)" size="small" max-height="240">
                  <el-table-column prop="name" label="传感器" min-width="140" show-overflow-tooltip />
                  <el-table-column prop="value" label="值" width="90" />
                  <el-table-column prop="unit" label="单位" width="80" />
                </el-table>
                <el-empty v-if="!(slowHealth.ipmi||[]).length" description="无 IPMI 数据（需要 ipmitool 权限）" :image-size="40" />
              </el-col>
            </el-row>
          </el-tab-pane>

          <el-tab-pane label="资产 / 拓扑" name="inventory">
            <el-descriptions v-if="inventory.machine_id" :column="3" border size="small">
              <el-descriptions-item label="Machine ID"><span class="mono" style="font-size:11px">{{ inventory.machine_id }}</span></el-descriptions-item>
              <el-descriptions-item label="厂商/型号">{{ (inventory.dmi||{}).sys_vendor }} {{ (inventory.dmi||{}).product_name }}</el-descriptions-item>
              <el-descriptions-item label="序列号"><span class="mono" style="font-size:11px">{{ (inventory.dmi||{}).product_serial }}</span></el-descriptions-item>
              <el-descriptions-item label="BIOS">{{ (inventory.dmi||{}).bios_version }} ({{ (inventory.dmi||{}).bios_date }})</el-descriptions-item>
              <el-descriptions-item label="CPU">{{ (inventory.lscpu||{}).model_name }}</el-descriptions-item>
              <el-descriptions-item label="插槽/核心">{{ (inventory.lscpu||{}).sockets }} 路 / {{ (inventory.lscpu||{}).cores_per_socket }} 核</el-descriptions-item>
              <el-descriptions-item label="NUMA 节点">{{ ((inventory.numa||{}).nodes||[]).map(n => `node${n.id}: ${n.cpus} (${n.mem_gb}GB)`).join('；') || (inventory.lscpu||{}).numa_nodes }}</el-descriptions-item>
              <el-descriptions-item label="时间同步">{{ (inventory.time_info||{}).system_clock_synchronized === 'yes' ? 'NTP 已同步' : '未同步' }}</el-descriptions-item>
              <el-descriptions-item label="IP">{{ (inventory.ip_addrs||[]).join(' · ') }}</el-descriptions-item>
            </el-descriptions>
            <div v-if="inventory.gpu_topology" class="chart-sub-title" style="margin-top:14px">GPU 拓扑（nvidia-smi topo -m）</div>
            <pre v-if="inventory.gpu_topology" class="topo-pre">{{ inventory.gpu_topology }}</pre>
            <div class="chart-sub-title" style="margin-top:14px">磁盘 / 网卡</div>
            <el-row :gutter="14">
              <el-col :span="12" :xs="{ span: 24 }">
                <el-table :data="(inventory.disks||[]).slice(0, 12)" size="small" max-height="300">
                  <el-table-column prop="name" label="磁盘" width="90" />
                  <el-table-column prop="size" label="容量" width="90" />
                  <el-table-column prop="type" label="类型" width="80" />
                  <el-table-column prop="model" label="型号" min-width="140" show-overflow-tooltip />
                </el-table>
              </el-col>
              <el-col :span="12" :xs="{ span: 24 }">
                <el-table :data="physicalNics" size="small" max-height="240">
                  <el-table-column prop="name" label="网卡" width="110" />
                  <el-table-column prop="mac" label="MAC" min-width="140">
                    <template #default="{ row }"><span class="mono" style="font-size:11px">{{ row.mac }}</span></template>
                  </el-table-column>
                  <el-table-column prop="state" label="状态" width="80" />
                  <el-table-column prop="speed" label="速率" width="80" />
                </el-table>
              </el-col>
            </el-row>
          </el-tab-pane>

          <el-tab-pane label="带外 IPMI" name="ipmi">
            <div v-if="!server?.has_bmc" style="padding:20px;text-align:center;color:var(--csub)">
              未配置带外管理。请在「编辑服务器」中填写 BMC 地址 / 账号，即可从监控主机直连 IPMI（关机 / 宕机也能监控）。
            </div>
            <template v-else-if="ipmi?.snapshot">
              <el-alert v-if="!ipmi.snapshot.ok" type="error" :closable="false" show-icon
                :title="`BMC 连接失败：${ipmi.snapshot.error}`" style="margin-bottom:12px" />
              <el-row :gutter="12" style="margin-bottom:12px">
                <el-col :span="6" :xs="{ span: 12 }"><div class="ipmi-kpi"><b :style="{ color: ipmi.summary?.power_on ? 'var(--cgreen)' : 'var(--cred)' }">{{ ipmi.summary?.power_on ? '开启' : '关闭' }}</b><span>机箱电源</span></div></el-col>
                <el-col :span="6" :xs="{ span: 12 }"><div class="ipmi-kpi"><b>{{ ipmi.summary?.power_w || '—' }} W</b><span>整机功耗（DCMI）</span></div></el-col>
                <el-col :span="6" :xs="{ span: 12 }"><div class="ipmi-kpi"><b>{{ (ipmi.snapshot.sensors || []).length }}</b><span>传感器</span></div></el-col>
                <el-col :span="6" :xs="{ span: 12 }"><div class="ipmi-kpi"><b class="mono" style="font-size:13px">{{ fmtTime(ipmi.snapshot.collected_at) }}</b><span>最近采集（每 5 分钟）</span></div></el-col>
              </el-row>
              <el-row :gutter="12">
                <el-col :span="12" :xs="24">
                  <div class="chart-sub-title">BMC 信息（mc info）</div>
                  <el-descriptions :column="1" border size="small">
                    <el-descriptions-item v-for="(v, k) in ipmi.snapshot.mc_info" :key="k" :label="k">{{ v }}</el-descriptions-item>
                  </el-descriptions>
                  <div class="chart-sub-title" style="margin-top:10px">机箱状态（chassis）</div>
                  <el-descriptions :column="1" border size="small">
                    <el-descriptions-item v-for="(v, k) in ipmi.snapshot.chassis" :key="k" :label="k">{{ v }}</el-descriptions-item>
                  </el-descriptions>
                  <div class="chart-sub-title" style="margin-top:10px">功耗统计（dcmi power）</div>
                  <el-descriptions :column="1" border size="small">
                    <el-descriptions-item v-for="(v, k) in ipmi.snapshot.power" :key="k" :label="k">{{ v }}</el-descriptions-item>
                  </el-descriptions>
                  <div class="chart-sub-title" style="margin-top:10px">BMC 网络（lan）</div>
                  <el-descriptions :column="1" border size="small">
                    <el-descriptions-item v-for="(v, k) in ipmi.snapshot.lan" :key="k" :label="k">{{ v }}</el-descriptions-item>
                  </el-descriptions>
                </el-col>
                <el-col :span="12" :xs="24">
                  <div class="chart-sub-title">全部传感器（sdr）</div>
                  <el-table :data="ipmi.snapshot.sensors || []" size="small" max-height="300">
                    <el-table-column prop="name" label="传感器" min-width="130" show-overflow-tooltip />
                    <el-table-column prop="reading" label="读数" width="130" show-overflow-tooltip />
                    <el-table-column label="状态" width="80">
                      <template #default="{ row }">
                        <el-tag size="small" :type="row.status === 'ok' ? 'success' : 'danger'">{{ row.status }}</el-tag>
                      </template>
                    </el-table-column>
                  </el-table>
                  <div class="chart-sub-title" style="margin-top:10px">硬件事件日志（SEL，新→旧）</div>
                  <el-table :data="(ipmi.snapshot.sel || []).slice().reverse()" size="small" max-height="260">
                    <el-table-column prop="record" label="#" width="56" />
                    <el-table-column label="时间" width="150">
                      <template #default="{ row }"><span class="mono">{{ row.date }} {{ row.time }}</span></template>
                    </el-table-column>
                    <el-table-column prop="event" label="事件" min-width="180" show-overflow-tooltip />
                  </el-table>
                  <el-empty v-if="!(ipmi.snapshot.sel || []).length" description="无 SEL 事件" :image-size="40" />
                  <div class="chart-sub-title" style="margin-top:10px">FRU 资产信息</div>
                  <el-descriptions v-for="(f, i) in ipmi.snapshot.fru" :key="i" :column="1" border size="small" style="margin-bottom:8px">
                    <el-descriptions-item v-for="(v, k) in f" :key="k" :label="k">{{ v }}</el-descriptions-item>
                  </el-descriptions>
                  <el-empty v-if="!(ipmi.snapshot.fru || []).length" description="无 FRU 信息" :image-size="40" />
                </el-col>
              </el-row>
            </template>
            <el-empty v-else description="等待首次 IPMI 采集（每 5 分钟一次）" :image-size="60" />
          </el-tab-pane>

          <el-tab-pane label="台账" name="notes">
            <div v-if="isAdmin" style="display:flex;gap:8px;margin-bottom:12px">
              <el-select v-model="noteKind" size="small" style="width:110px">
                <el-option value="note" label="备注" />
                <el-option value="maintenance" label="维护" />
                <el-option value="repair" label="维修" />
              </el-select>
              <el-input v-model="noteInput" size="small" placeholder="记录维护/维修信息，如：更换 /dev/nvme1，SN xxx" style="flex:1" @keyup.enter="addNote" />
              <el-button size="small" type="primary" @click="addNote">记录</el-button>
            </div>
            <el-table :data="notes" size="small" max-height="320">
              <el-table-column label="时间" width="160">
                <template #default="{ row }"><span class="mono">{{ fmtTime(row.ts) }}</span></template>
              </el-table-column>
              <el-table-column label="类型" width="80">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.kind === 'repair' ? 'danger' : row.kind === 'maintenance' ? 'warning' : 'info'">
                    {{ { note: '备注', maintenance: '维护', repair: '维修' }[row.kind] || row.kind }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="username" label="操作人" width="100" />
              <el-table-column prop="content" label="内容" min-width="300" show-overflow-tooltip />
            </el-table>
            <el-empty v-if="!notes.length" description="暂无记录" :image-size="50" />
          </el-tab-pane>

          <el-tab-pane label="采集健康" name="collect">
            <template v-if="collectHealth">
              <el-row :gutter="14">
                <el-col :span="6" :xs="{ span: 12 }"><div class="stat-card" style="padding:12px;border:1px solid var(--cborder);border-radius:8px">
                  <div class="stat-value" :style="{ color: collectHealth.success_rate >= 95 ? 'var(--cgreen)' : 'var(--cred)' }">{{ collectHealth.success_rate }}%</div>
                  <div class="stat-label">24h 采集成功率</div>
                </div></el-col>
                <el-col :span="6" :xs="{ span: 12 }"><div class="stat-card" style="padding:12px;border:1px solid var(--cborder);border-radius:8px">
                  <div class="stat-value">{{ collectHealth.ok }}/{{ collectHealth.total }}</div>
                  <div class="stat-label">成功/总次数</div>
                </div></el-col>
                <el-col :span="6" :xs="{ span: 12 }"><div class="stat-card" style="padding:12px;border:1px solid var(--cborder);border-radius:8px">
                  <div class="stat-value">{{ collectHealth.avg_ssh_latency }}s</div>
                  <div class="stat-label">平均 SSH 延迟</div>
                </div></el-col>
                <el-col :span="6" :xs="{ span: 12 }"><div class="stat-card" style="padding:12px;border:1px solid var(--cborder);border-radius:8px">
                  <div class="stat-value">{{ collectHealth.avg_duration }}s</div>
                  <div class="stat-label">平均采集耗时</div>
                </div></el-col>
              </el-row>
              <template v-if="Object.keys(collectHealth.errors || {}).length">
                <div class="chart-sub-title" style="margin-top:14px;color:var(--cyellow)">错误分布</div>
                <el-table :data="Object.entries(collectHealth.errors).map(([code, n]) => ({ code, n }))" size="small" max-height="200">
                  <el-table-column prop="code" label="错误码" width="220" class-name="mono" />
                  <el-table-column prop="n" label="次数" width="120" />
                </el-table>
              </template>
              <div v-else style="margin-top:12px;color:var(--csub);font-size:12px">24 小时内无采集错误</div>
            </template>
            <el-empty v-else description="暂无数据" :image-size="50" />
          </el-tab-pane>
        </el-tabs>
      </el-card>
    </template>
    <el-empty v-else-if="!loading" description="暂无采集数据，请等待采集周期或点击「立即采集」" />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import api from '../api'
import { isAdminSession, useLatestOnly } from '../composables'
import RateUnitPicker from '../components/RateUnitPicker.vue'
import { diskAxisFormatter, fmtDiskRate, fmtDuration, fmtFreq, fmtNetRate, fmtSizeMB, fmtTime, fmtUptime, netAxisFormatter, pct } from '../format'
import { chartTheme } from '../theme'

use([CanvasRenderer, LineChart, GridComponent, LegendComponent, TooltipComponent])

const route = useRoute()
// reactive: the router reuses this component when navigating between servers
const serverId = computed(() => Number(route.params.id))
const invalidId = computed(() => !Number.isFinite(serverId.value) || serverId.value <= 0)
const applyHistory = useLatestOnly()
const applyProcs = useLatestOnly()
const loading = ref(false)
const server = ref(null)
const isGpuServer = computed(() => (server.value?.server_type ?? 'gpu') === 'gpu')
const metric = ref(null)
let _lastFailToast = 0
function loadFail(e) {
  // one gentle toast per 30s — polling failures must not spam
  const now = Date.now()
  if (now - _lastFailToast < 30000) return
  _lastFailToast = now
  if (e?.response?.status === 401) return  // global interceptor handles logout
  ElMessage.warning(e?.friendlyMessage || '部分数据加载失败')
}

const unitEpoch = ref(0)
function onUnitChange() { unitEpoch.value++ }
const history = ref([])
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

async function loadHealth() {
  try { health.value = (await api.get(`/servers/${serverId.value}/health`)).data } catch (e) { loadFail(e); health.value = null }
}
async function loadRisk() {
  try { riskGpus.value = (await api.get(`/servers/${serverId.value}/risk`)).data.gpus || [] } catch (e) { loadFail(e); riskGpus.value = [] }
}
async function loadEvents() {
  try {
    const { data } = await api.get(`/servers/${serverId.value}/kernel-events`, { params: { hours: 24, severity: evSev.value } })
    events.value = data
  } catch (e) { loadFail(e); events.value = [] }
}
async function loadSlowHealth() {
  try { slowHealth.value = (await api.get(`/servers/${serverId.value}/slow-health`)).data } catch (e) { loadFail(e); slowHealth.value = {} }
}
const ipmi = ref(null)
async function loadIpmi() {
  try { ipmi.value = (await api.get(`/servers/${serverId.value}/ipmi/latest`)).data } catch { ipmi.value = null }
}
async function loadInventory() {
  try { inventory.value = (await api.get(`/servers/${serverId.value}/inventory`)).data } catch (e) { loadFail(e); inventory.value = {} }
}
async function loadNotes() {
  try { notes.value = (await api.get(`/servers/${serverId.value}/notes`)).data } catch (e) { loadFail(e); notes.value = [] }
}
async function loadCollectHealth() {
  try { collectHealth.value = (await api.get(`/servers/${serverId.value}/collect-health`)).data } catch { collectHealth.value = null }
}
function loadEnterprise() {
  loadHealth(); loadRisk(); loadEvents(); loadSlowHealth(); loadInventory(); loadNotes(); loadCollectHealth(); loadIpmi()
}

async function setStatus(status) {
  try {
    let reason = ''
    if (status !== 'active') {
      const { value } = await ElMessageBox.prompt('请填写原因（将记入台账）', '状态变更', {
        inputPlaceholder: '例如：更换 3 号 GPU / 系统重装', inputValidator: v => !!v?.trim() || '原因不能为空'
      })
      reason = value.trim()
    }
    const { data } = await api.post(`/servers/${serverId.value}/status`, { status, reason })
    server.value = data
    ElMessage.success(`已切换为「${statusCn[status]}」`)
    loadNotes()
  } catch (e) {
    if (e !== 'cancel' && e?.friendlyMessage) ElMessage.error(e.friendlyMessage)
  }
}

async function addNote() {
  if (!noteInput.value.trim()) return
  try {
    await api.post(`/servers/${serverId.value}/notes`, { kind: noteKind.value, content: noteInput.value.trim() })
    noteInput.value = ''
    loadNotes()
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '记录失败')
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
  return (units * 512 / 1024 / 1024 / 1024).toFixed(1) + 'TB'  // data units -> GB (512k each)
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
function overallTag(s) { return s === 'critical' ? 'danger' : s === 'warning' ? 'warning' : s === 'ok' ? 'success' : 'info' }
function overallLabel(s) { return { critical: '危急', warning: '警告', ok: '健康', unknown: '未知' }[s] || s }
function statusLabel(s) { return { critical: '危急', warning: '警告', ok: '正常' }[s] || s }

const isAdmin = computed(() => isAdminSession())
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
  if (v >= 90) return '#f56c6c'
  if (v >= 70) return '#e6a23c'
  return '#67c23a'
}

function tempColor(t) {
  if (t >= 80) return '#f56c6c'
  if (t >= 70) return '#e6a23c'
  return '#67c23a'
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
    const d = new Date(t.time)
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
  if (invalidId.value || document.hidden) return
  loading.value = !metric.value
  try {
    const [serverList, latest] = await Promise.allSettled([
      api.get('/servers').then(r => r.data),
      api.get(`/metrics/server/${serverId.value}/latest`).then(r => r.data),
      loadHistory()
    ])
    server.value = serverList.status === 'fulfilled'
      ? (serverList.value || []).find(s => s.id === serverId.value) || null
      : server.value
    metric.value = latest.status === 'fulfilled' ? latest.value : null
  } catch (e) {
    if (!metric.value) ElMessage.error(e.friendlyMessage || '加载失败')
  } finally {
    loading.value = false
  }
}

async function loadHistory() {
  if (invalidId.value) return
  try {
    await applyHistory(
      api.get(`/metrics/server/${serverId.value}/history?hours=${hours.value}`).then(r => r.data),
      (data) => { history.value = data }
    )
  } catch {
    history.value = []
  }
}

async function loadProcs() {
  if (invalidId.value || document.hidden || !isAdmin.value) return
  procsLoading.value = true
  try {
    await applyProcs(
      api.post(`/metrics/server/${serverId.value}/processes?sort=${procSort.value}`).then(r => r.data),
      (data) => { procs.value = data.processes }
    )
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '获取进程失败')
  } finally {
    procsLoading.value = false
  }
}

async function kill(row, signal) {
  try {
    const { value: reauth_password } = await ElMessageBox.prompt(
      `请输入当前管理员密码以确认向进程 ${row.pid} 发送 ${signal}`,
      '敏感操作再次认证',
      { inputType: 'password', inputPattern: /.+/, inputErrorMessage: '请输入当前密码' }
    )
    const { data } = await api.post(`/metrics/server/${serverId.value}/processes/action`, {
      action: 'kill', pid: row.pid, start_ticks: row.start_ticks, signal, reauth_password
    })
    ElMessage.success(`已发送 ${signal} 到 ${row.pid}: ${data.message}`)
    clearTimeout(killTimer)
    killTimer = setTimeout(loadProcs, 800)
  } catch (e) {
    ElMessage.error(e.friendlyMessage || 'kill 失败')
  }
}

async function renice(row) {
  try {
    const { value } = await ElMessageBox.prompt(`调整进程 ${row.pid} 的 nice 值 (-20 最高优先级 ~ 19 最低)`, 'Renice', {
      inputValue: '10', inputPattern: /^-?\d+$/, inputErrorMessage: '请输入 -20 到 19 之间的整数'
    })
    const nice = Math.max(-20, Math.min(19, parseInt(value)))
    const { value: reauth_password } = await ElMessageBox.prompt(
      `请输入当前管理员密码以确认调整进程 ${row.pid}`,
      '敏感操作再次认证',
      { inputType: 'password', inputPattern: /.+/, inputErrorMessage: '请输入当前密码' }
    )
    await api.post(`/metrics/server/${serverId.value}/processes/action`, {
      action: 'renice', pid: row.pid, start_ticks: row.start_ticks, nice, reauth_password
    })
    ElMessage.success(`已 renice ${row.pid} -> ${nice}`)
  } catch (e) {
    if (e !== 'cancel' && e?.friendlyMessage) ElMessage.error(e.friendlyMessage)
  }
}

function startTimers() {
  stopTimers()
  liveTimer = setInterval(loadProcs, 15000)
  entTimer = setInterval(() => { loadHealth(); loadEvents() }, 60000)
  mainTimer = setInterval(load, 30000)
}
function stopTimers() {
  clearInterval(liveTimer); clearInterval(entTimer); clearInterval(mainTimer)
  liveTimer = entTimer = mainTimer = null
}

// re-initialize everything when the route param changes (component is reused)
watch(serverId, () => {
  metric.value = null; history.value = []; procs.value = []; events.value = []
  server.value = null; health.value = null; riskGpus.value = []; slowHealth.value = {}
  inventory.value = {}; notes.value = []; collectHealth.value = null
  load(); loadProcs(); loadEnterprise(); startTimers()
})

onMounted(() => {
  if (invalidId.value) return
  load()
  loadProcs()
  loadEnterprise()
  startTimers()
})
onUnmounted(() => { stopTimers(); clearTimeout(killTimer) })
</script>

<style scoped>
.health-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 10px;
}
.detail-toolbar { justify-content: space-between; }
.detail-toolbar-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
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
.detail-kpis { row-gap: 14px; }
.detail-kpi-card { min-height: 128px; }
.detail-capacity-value { white-space: normal; font-size: clamp(18px, 1.8vw, 25px); }
.detail-capacity-value i { margin: 0 3px; color: var(--csub); font-size: .72em; font-style: normal; }
.detail-card-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
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
.st-critical .health-dot { background: var(--cred); animation: pulse 2s infinite; }
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
  border: 1px solid var(--cborder, #dde5f0);
  border-radius: 4px;
  overflow: hidden;
  background: var(--cpanel2, #f7f9fc);
  cursor: default;
}
.core-fill {
  position: absolute;
  bottom: 0; left: 0; right: 0;
  transition: height .4s;
}
.core-idle .core-fill { background: color-mix(in srgb, var(--csub, #64748b) 40%, transparent); }
.core-ok   .core-fill { background: color-mix(in srgb, var(--cgreen, #059669) 55%, transparent); }
.core-warn .core-fill { background: color-mix(in srgb, var(--cyellow, #d97706) 60%, transparent); }
.core-crit .core-fill { background: color-mix(in srgb, var(--cred, #dc2626) 65%, transparent); }
.core-text {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  color: var(--ctext, #1f2d3d);
}

.ipmi-kpi {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  background: var(--cpanel2, #f7f9fc); border: 1px solid var(--cborder, #dde5f0);
  border-radius: 8px; padding: 10px 6px;
}
.ipmi-kpi b { font-size: 17px; }
.ipmi-kpi span { font-size: 11px; color: var(--csub, #64748b); }
@media (max-width: 768px) {
  .detail-toolbar { align-items: flex-start; }
  .detail-toolbar :deep(.el-page-header) { flex-basis: 100%; }
  .detail-toolbar-actions { width: 100%; }
  .detail-jump-nav { width: 100%; }
  .detail-jump-nav button { flex: 1 0 auto; }
  .health-grid { grid-template-columns: 1fr; }
  .detail-kpi-card { min-height: 112px; }
  .detail-capacity-value { font-size: 16px; line-height: 1.35; }
  .detail-card-head { align-items: flex-start; flex-direction: column; }
  .process-card-actions { width: 100%; justify-content: flex-start; }
  .process-card-actions :deep(.el-input) { flex: 1 1 130px; width: auto !important; }
  .trend-card-head :deep(.el-radio-group) { max-width: 100%; overflow-x: auto; }
  .gpu-card-head { flex-direction: column; }
  .gpu-card-tags { justify-content: flex-start; }
  .gpu-card :deep(.el-card__body) { padding: 14px; }
  .gpu-card :deep(.el-progress) { max-width: 95px; }
  .gpu-card :deep(.el-descriptions__table) { width: 100%; table-layout: fixed; }
  .gpu-card :deep(.el-descriptions__table tbody) { display: block; width: 100%; }
  .gpu-card :deep(.el-descriptions__table tr) {
    display: grid;
    grid-template-columns: minmax(72px, auto) minmax(0, 1fr);
    width: 100%;
  }
  .gpu-card :deep(.el-descriptions__cell) {
    display: block;
    width: auto !important;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .chart-box { height: 250px; }
  .chart-box-sm { height: 220px; }
  .enterprise-card :deep(.el-tabs__nav-wrap) { padding: 0 24px; }
  .enterprise-card :deep(.el-tabs__item) { padding: 0 12px; }
  .enterprise-toolbar { align-items: stretch; flex-wrap: wrap; }
  .enterprise-toolbar :deep(.el-radio-group) { min-width: 220px; flex: 1; flex-wrap: nowrap; }
  .enterprise-toolbar :deep(.el-radio-button) { flex: 1; }
  .enterprise-toolbar :deep(.el-radio-button__inner) { width: 100%; padding-inline: 8px; }
  .enterprise-toolbar__hint { width: 100%; }
  .topo-pre { max-height: 260px; }
}
@media (max-width: 420px) {
  .detail-kpi-card :deep(.el-card__body) { padding: 15px 10px; }
  .detail-kpi-card .stat-sub { white-space: normal; overflow-wrap: anywhere; }
  .core-grid { grid-template-columns: repeat(auto-fill, minmax(36px, 1fr)); }
  .core-block { height: 52px; }
}
</style>
