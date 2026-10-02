<template>
  <div class="cockpit">
    <div class="toolbar server-toolbar">
      <a-button v-if="isAdmin" type="primary" @click="openCreate"><template #icon><PlusOutlined /></template>添加服务器</a-button>
      <a-button @click="load"><template #icon><ReloadOutlined /></template>刷新</a-button>
      <a-input v-model:value="keyword" placeholder="搜索名称 / IP" allow-clear style="width:220px">
        <template #prefix><SearchOutlined /></template>
      </a-input>
      <a-select v-model:value="tagFilter" placeholder="按标签筛选" allow-clear style="width:160px">
        <a-select-option v-for="t in allTags" :key="t" :value="t">{{ t }}</a-select-option>
      </a-select>
      <a-select v-model:value="statusFilter" placeholder="按状态筛选" allow-clear style="width:150px">
        <a-select-option value="active">运行中</a-select-option>
        <a-select-option value="maintenance">维护中</a-select-option>
        <a-select-option value="drained">已排空</a-select-option>
        <a-select-option value="rma">返修中</a-select-option>
      </a-select>
    </div>

    <a-card class="server-list-card">
      <a-table class="desktop-only" :data-source="filtered" :loading="loading" :pagination="false" :scroll="{ x: 1180, y: 640 }" row-key="id" size="middle">
        <a-table-column data-index="name" title="名称" :width="150" ellipsis>
          <template #default="{ record: row }">
            <a-button type="link" size="small" class="table-link" @click="$router.push(`/servers/${row.id}`)">{{ row.name }}</a-button>
          </template>
        </a-table-column>
        <a-table-column title="类型" :width="80">
          <template #default="{ record: row }">
            <a-tag :color="(row.server_type || 'gpu') === 'gpu' ? 'green' : undefined">
              {{ (row.server_type || 'gpu') === 'gpu' ? 'GPU' : 'CPU' }}
            </a-tag>
          </template>
        </a-table-column>
        <a-table-column title="地址" :width="190">
          <template #default="{ record: row }"><span class="mono">{{ isAdmin ? `${row.host}:${row.port}` : '仅管理员可见' }}</span></template>
        </a-table-column>
        <a-table-column title="认证" :width="90">
          <template #default="{ record: row }">
            <a-tag :color="row.auth_type === 'key' ? 'green' : undefined">
              {{ isAdmin ? (row.auth_type === 'key' ? '密钥' : '密码') : '受保护' }}
            </a-tag>
          </template>
        </a-table-column>
        <a-table-column title="标签" :width="160">
          <template #default="{ record: row }">
            <a-tag v-for="t in row.tags" :key="t">{{ t }}</a-tag>
          </template>
        </a-table-column>
        <a-table-column title="状态" :width="100">
          <template #default="{ record: row }">
            <a-tooltip v-if="row.status_reason" :title="row.status_reason" placement="top">
              <a-tag :color="statusTagColor(row.status)">{{ statusCn[row.status] || row.status || '运行中' }}</a-tag>
            </a-tooltip>
            <a-tag v-else :color="statusTagColor(row.status)">{{ statusCn[row.status] || '运行中' }}</a-tag>
          </template>
        </a-table-column>
        <a-table-column title="启用" :width="80">
          <template #default="{ record: row }">
            <a-switch v-model:checked="row.enabled" :disabled="!isAdmin || busyServerIds.has(row.id)" :loading="busyServerIds.has(row.id)" @change="toggleEnabled(row)" />
          </template>
        </a-table-column>
        <a-table-column data-index="note" title="备注" :width="140" ellipsis />
        <a-table-column v-if="isAdmin" title="操作" :width="220" fixed="right">
          <template #default="{ record: row }">
            <div class="table-actions">
              <a-button size="small" @click="openEdit(row)">编辑</a-button>
              <a-button size="small" :loading="testingId === row.id" @click="testExisting(row)">测试</a-button>
              <a-popconfirm title="确定删除该服务器？" ok-text="删除" cancel-text="取消" @confirm="remove(row)">
                <a-button size="small" danger>删除</a-button>
              </a-popconfirm>
            </div>
          </template>
        </a-table-column>
      </a-table>
      <a-spin class="mobile-only" :spinning="loading">
        <div v-if="filtered.length" class="mobile-card-list">
          <article v-for="row in filtered" :key="row.id" class="mobile-data-card server-mobile-card">
            <div class="mobile-data-card__head">
              <div class="mobile-data-card__title">
                <a-button type="link" size="small" class="table-link" @click="$router.push(`/servers/${row.id}`)">{{ row.name }}</a-button>
                <div class="server-address mono">{{ isAdmin ? `${row.host}:${row.port}` : '地址仅管理员可见' }}</div>
              </div>
              <div class="server-card-status">
                <a-tag :color="(row.server_type || 'gpu') === 'gpu' ? 'green' : undefined">{{ (row.server_type || 'gpu') === 'gpu' ? 'GPU' : 'CPU' }}</a-tag>
                <a-tag :color="statusTagColor(row.status)">{{ statusCn[row.status] || '运行中' }}</a-tag>
              </div>
            </div>
            <div v-if="row.tags?.length" class="server-card-tags">
              <a-tag v-for="t in row.tags" :key="t">{{ t }}</a-tag>
            </div>
            <div class="mobile-data-card__meta">
              <span>认证</span><span>{{ isAdmin ? (row.auth_type === 'key' ? 'SSH 密钥' : '用户名 / 密码') : '受保护' }}</span>
              <span>启用采集</span><a-switch v-model:checked="row.enabled" :disabled="!isAdmin || busyServerIds.has(row.id)" :loading="busyServerIds.has(row.id)" @change="toggleEnabled(row)" />
              <template v-if="row.status_reason"><span>状态说明</span><span>{{ row.status_reason }}</span></template>
              <template v-if="row.note"><span>备注</span><span>{{ row.note }}</span></template>
            </div>
            <div v-if="isAdmin" class="mobile-data-card__actions">
              <a-button size="small" @click="openEdit(row)">编辑</a-button>
              <a-button size="small" :loading="testingId === row.id" @click="testExisting(row)">测试连接</a-button>
              <a-popconfirm title="确定删除该服务器？" ok-text="删除" cancel-text="取消" @confirm="remove(row)">
                <a-button size="small" danger>删除</a-button>
              </a-popconfirm>
            </div>
          </article>
        </div>
        <a-empty v-else description="没有符合筛选条件的服务器" />
      </a-spin>
    </a-card>

    <a-modal v-model:open="dlg" :title="editId ? '编辑服务器' : '添加服务器'" :width="620" class="responsive-dialog server-dialog">
      <a-form ref="formRef" :model="form" :rules="rules" :label-col="{ style: { width: '96px' } }" class="responsive-form">
        <a-form-item label="名称" name="name">
          <a-input v-model:value="form.name" placeholder="如 gpu-node-01" :maxlength="128" />
        </a-form-item>
        <a-form-item label="主机" name="host">
          <a-row :gutter="8" class="host-row">
          <a-col :span="16">
            <a-input v-model:value="form.host" placeholder="IP 或主机名" :maxlength="255" />
          </a-col>
          <a-col :span="8">
            <a-form-item name="port" class="port-form-item">
              <a-input-number v-model:value="form.port" :min="1" :max="65535" :precision="0" aria-label="SSH 端口" style="width:100%" />
            </a-form-item>
          </a-col>
          </a-row>
        </a-form-item>
        <a-form-item label="服务器类型" name="server_type">
          <a-radio-group v-model:value="form.server_type">
            <a-radio value="gpu">GPU 服务器</a-radio>
            <a-radio value="cpu">CPU 服务器</a-radio>
          </a-radio-group>
        </a-form-item>
        <a-form-item label="认证方式" name="auth_type">
          <a-radio-group v-model:value="form.auth_type">
            <a-radio value="password">用户名 / 密码</a-radio>
            <a-radio value="key">SSH 密钥</a-radio>
          </a-radio-group>
        </a-form-item>
        <a-form-item label="用户名" name="username">
          <a-input v-model:value="form.username"
            :maxlength="64" :placeholder="editId ? '留空保持不变' : 'gpumon'" />
        </a-form-item>
        <template v-if="form.auth_type === 'password'">
          <a-form-item label="密码" name="password">
            <a-input-password v-model:value="form.password"
              :placeholder="editId && hasPassword ? '留空保持不变' : 'SSH 登录密码'" />
          </a-form-item>
        </template>
        <template v-else>
          <a-form-item label="私钥" name="private_key">
            <a-textarea v-model:value="form.private_key" :rows="5" class="mono"
              :placeholder="editId && hasKey ? '留空保持不变（已配置密钥）' : '-----BEGIN OPENSSH PRIVATE KEY-----'" />
          </a-form-item>
          <a-form-item label="口令">
            <a-input-password v-model:value="form.passphrase" placeholder="私钥口令（没有可留空）" />
          </a-form-item>
        </template>
        <a-form-item label="带外管理">
          <div class="bmc-fields">
            <a-input v-model:value="form.bmc_host" placeholder="BMC/IPMI 地址（可留空）" style="flex:2;min-width:150px" />
            <a-input v-model:value="form.bmc_user" placeholder="BMC 用户" style="flex:1;min-width:100px" />
            <a-input-password v-model:value="form.bmc_password"
              :placeholder="editId && hasBmc ? '留空保持不变' : 'BMC 密码'" style="flex:1;min-width:120px" />
          </div>
        </a-form-item>
        <a-form-item label="标签">
          <div>
            <a-tag v-for="(t, i) in form.tags" :key="i" closable @close="form.tags.splice(i, 1)">{{ t }}</a-tag>
            <a-input v-if="tagInput" ref="tagInputRef" v-model:value="newTag" size="small" style="width:120px"
              @keyup.enter="addTag" @blur="addTag" placeholder="回车添加" />
            <a-button v-else size="small" @click="showTagInput">+ 标签</a-button>
          </div>
        </a-form-item>
        <a-form-item label="备注">
          <a-textarea v-model:value="form.note" :rows="2" />
        </a-form-item>
        <a-form-item label="启用">
          <a-switch v-model:checked="form.enabled" />
        </a-form-item>
      </a-form>
      <template #footer>
        <a-button :loading="testing" :disabled="saving || testingIpmi" @click="testConn">测试连接</a-button>
        <a-button v-if="editId" :loading="testingIpmi" :disabled="saving || testing" @click="testIpmi">测试 IPMI</a-button>
        <a-button @click="dlg = false">取消</a-button>
        <a-button type="primary" :loading="saving" :disabled="testing || testingIpmi" @click="save">保存</a-button>
      </template>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { App as AntApp } from 'ant-design-vue'
import { PlusOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons-vue'
import api from '../api'
import { isAdminSession } from '../composables'
import { buildServerPayload } from '../server-form'

const isAdmin = computed(() => isAdminSession())
const { message, modal } = AntApp.useApp()
const loading = ref(false)
const serversList = ref([])
const keyword = ref('')
const tagFilter = ref('')
const statusFilter = ref('')
const statusCn = { active: '运行中', maintenance: '维护中', drained: '已排空', rma: '返修中' }
function statusTagColor(status) {
  return status === 'maintenance' ? 'orange' : status === 'rma' ? 'red' : status === 'drained' ? undefined : 'green'
}
const dlg = ref(false)
const editId = ref(null)
const hasPassword = ref(false)
const hasKey = ref(false)
const originalAuthType = ref(null)
const busyServerIds = reactive(new Set())
const saving = ref(false)
const testing = ref(false)
const testingId = ref(null)
const formRef = ref()
const tagInput = ref(false)
const tagInputRef = ref()
const newTag = ref('')

const blank = () => ({
  name: '', host: '', port: 22, auth_type: 'password', username: 'gpumon', server_type: 'gpu',
  password: '', private_key: '', passphrase: '', tags: [], note: '', enabled: true,
  bmc_host: '', bmc_user: '', bmc_password: ''
})
const form = reactive(blank())
const hasBmc = ref(false)
const testingIpmi = ref(false)

const rules = computed(() => ({
  name: [{ required: true, whitespace: true, max: 128, message: '名称须为 1–128 个字符', trigger: 'blur' }],
  host: [
    { required: true, max: 255, message: '请输入主机地址（最多 255 个字符）', trigger: 'blur' },
    { pattern: /^[^\s\x00-\x1f\x7f]+$/, message: '主机地址不能含空格或控制字符', trigger: 'blur' }
  ],
  port: [{ validator: (_, value) => Number.isInteger(value) && value >= 1 && value <= 65535
    ? Promise.resolve() : Promise.reject(new Error('端口须为 1–65535 的整数')), trigger: 'change' }],
  username: [
    { required: !editId.value, message: '请输入用户名', trigger: 'blur' },
    { max: 64, message: '用户名最多 64 个字符', trigger: 'blur' }
  ],
  password: [{ required: form.auth_type === 'password' && (!editId.value || originalAuthType.value !== 'password' || !hasPassword.value), message: '请输入 SSH 密码', trigger: 'blur' }],
  private_key: [{ required: form.auth_type === 'key' && (!editId.value || originalAuthType.value !== 'key' || !hasKey.value), message: '请粘贴 SSH 私钥', trigger: 'blur' }]
}))

const allTags = computed(() => [...new Set(serversList.value.flatMap(s => s.tags || []))].sort())

const filtered = computed(() => {
  const k = keyword.value.toLowerCase()
  return serversList.value.filter(s => {
    if (k && !s.name.toLowerCase().includes(k) && !s.host.toLowerCase().includes(k)) return false
    if (tagFilter.value && !(s.tags || []).includes(tagFilter.value)) return false
    if (statusFilter.value && (s.status || 'active') !== statusFilter.value) return false
    return true
  })
})

function addTag() {
  const t = newTag.value.trim()
  if (t && !form.tags.includes(t)) form.tags.push(t)
  tagInput.value = false
  newTag.value = ''
}

async function showTagInput() {
  tagInput.value = true
  newTag.value = ''
  await nextTick()
  tagInputRef.value?.focus()
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/servers')
    serversList.value = data
  } catch (e) {
    message.error(e.friendlyMessage || '加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editId.value = null
  originalAuthType.value = null
  Object.assign(form, blank())
  hasPassword.value = false
  hasKey.value = false
  hasBmc.value = false
  dlg.value = true
}

function openEdit(row) {
  editId.value = row.id
  originalAuthType.value = row.auth_type
  Object.assign(form, blank(), {
    name: row.name, host: row.host, port: row.port, auth_type: row.auth_type,
    username: '', server_type: row.server_type || 'gpu',
    tags: [...(row.tags || [])], note: row.note || '', enabled: row.enabled,
    bmc_host: row.bmc_host || '', bmc_user: row.bmc_user || ''
  })
  hasPassword.value = row.has_password
  hasKey.value = row.has_key
  hasBmc.value = row.has_bmc
  dlg.value = true
}

async function save() {
  if (saving.value || testing.value || testingIpmi.value) return
  saving.value = true
  try {
    await formRef.value.validate()
  } catch {
    saving.value = false
    return
  }
  try {
    const payload = buildServerPayload(form, !!editId.value)
    if (editId.value) {
      await api.put(`/servers/${editId.value}`, payload)
    } else {
      await api.post('/servers', payload)
    }
    message.success('保存成功')
    dlg.value = false
    load()
  } catch (e) {
    message.error(e.friendlyMessage || '保存失败')
  } finally {
    saving.value = false
  }
}

async function testIpmi() {
  if (!editId.value || testingIpmi.value || saving.value || testing.value) return
  modal.confirm({
    title: '测试 IPMI',
    content: '测试前将保存当前 BMC 配置，是否继续？',
    okText: '保存并测试',
    cancelText: '取消',
    async onOk() {
      await runIpmiTest()
    },
  })
}

async function runIpmiTest() {
  if (testingIpmi.value || saving.value || testing.value) return
  testingIpmi.value = true
  try {
    const payload = { bmc_host: form.bmc_host, bmc_user: form.bmc_user }
    if (form.bmc_password) payload.bmc_password = form.bmc_password
    await api.put(`/servers/${editId.value}`, payload)
    const { data } = await api.post(`/servers/${editId.value}/ipmi/test`)
    if (data.ok) {
      const s = data.summary || {}
      message.success(`IPMI 正常 · 电源${s.power_on ? '开启' : '关闭'} · 整机功耗 ${s.power_w}W · 传感器 ${(data.snapshot?.sensors || []).length} 项 · ${data.duration}s`)
      hasBmc.value = true
    } else {
      message.error('IPMI 连接失败：' + (data.error || '未知错误'))
    }
    load()
  } catch (e) {
    message.error(e.friendlyMessage || 'IPMI 测试失败')
  } finally {
    testingIpmi.value = false
  }
}

async function remove(row) {
  try {
    await api.delete(`/servers/${row.id}`)
    message.success('已删除')
    load()
  } catch (e) {
    message.error(e.friendlyMessage || '删除失败')
  }
}

async function toggleEnabled(row) {
  if (busyServerIds.has(row.id)) return
  busyServerIds.add(row.id)
  try {
    await api.put(`/servers/${row.id}`, { enabled: row.enabled })
    message.success(row.enabled ? '已启用' : '已禁用')
  } catch (e) {
    row.enabled = !row.enabled
    message.error(e.friendlyMessage || '操作失败')
  } finally {
    busyServerIds.delete(row.id)
  }
}

async function testConn() {
  if (testing.value || saving.value || testingIpmi.value) return
  testing.value = true
  try {
    await formRef.value.validate()
    const payload = buildServerPayload(form, !!editId.value)
    const { data } = await api.post(editId.value ? `/servers/${editId.value}/test` : '/servers/test', payload)
    data.ok ? message.success(data.message) : message.error(data.message)
  } catch (e) {
    if (!e.errorFields) message.error(e.friendlyMessage || '测试失败')
  } finally {
    testing.value = false
  }
}

async function testExisting(row) {
  if (testingId.value !== null) return
  testingId.value = row.id
  try {
    const { data } = await api.post(`/servers/${row.id}/test`)
    data.ok ? message.success(data.message) : message.error(data.message)
  } catch (e) {
    message.error(e.friendlyMessage || '测试失败')
  } finally {
    testingId.value = null
  }
}

watch(dlg, (open) => {
  if (!open) Object.assign(form, { username: '', password: '', private_key: '', passphrase: '', bmc_password: '' })
})

onMounted(load)
</script>

<style scoped>
.table-link { height: auto; padding: 0; }
.table-actions { display: flex; gap: 8px; }
.host-row { width: 100%; }
.port-form-item { margin-bottom: 0; }
.bmc-fields { display: flex; gap: 8px; flex-wrap: wrap; width: 100%; }
.server-card-status { display: flex; flex: 0 0 auto; align-items: center; gap: 6px; }
.server-address { margin-top: 5px; color: var(--csub); font-size: 11px; font-weight: 400; }
.server-card-tags { display: flex; flex-wrap: wrap; gap: 5px; margin: -2px 0 12px; }
.server-mobile-card :deep(.ant-switch) { justify-self: start; }
@media (max-width: 768px) {
  .server-toolbar :deep(.ant-input-affix-wrapper),
  .server-toolbar :deep(.ant-select) { width: 100% !important; }
  .server-list-card :deep(.ant-card-body) { padding: 12px; }
}
</style>
