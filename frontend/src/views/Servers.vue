<template>
  <div class="cockpit">
    <div class="toolbar server-toolbar">
      <el-button v-if="isAdmin" type="primary" :icon="Plus" @click="openCreate">添加服务器</el-button>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
      <el-input v-model="keyword" placeholder="搜索名称 / IP" clearable style="width: 220px" :prefix-icon="Search" />
      <el-select v-model="tagFilter" placeholder="按标签筛选" clearable style="width:160px">
        <el-option v-for="t in allTags" :key="t" :value="t" :label="t" />
      </el-select>
      <el-select v-model="statusFilter" placeholder="按状态筛选" clearable style="width:150px">
        <el-option value="active" label="运行中" />
        <el-option value="maintenance" label="维护中" />
        <el-option value="drained" label="已排空" />
        <el-option value="rma" label="返修中" />
      </el-select>
    </div>

    <el-card class="server-list-card">
      <el-table class="desktop-only" :data="filtered" v-loading="loading" max-height="640">
        <el-table-column prop="name" label="名称" min-width="140">
          <template #default="{ row }">
            <el-link type="primary" @click="$router.push(`/servers/${row.id}`)">{{ row.name }}</el-link>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag :type="(row.server_type || 'gpu') === 'gpu' ? 'success' : 'info'" size="small">
              {{ (row.server_type || 'gpu') === 'gpu' ? 'GPU' : 'CPU' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="地址" min-width="180">
          <template #default="{ row }"><span class="mono">{{ isAdmin ? `${row.host}:${row.port}` : '仅管理员可见' }}</span></template>
        </el-table-column>
        <el-table-column label="认证" width="90">
          <template #default="{ row }">
            <el-tag :type="row.auth_type === 'key' ? 'success' : 'info'" size="small">
              {{ isAdmin ? (row.auth_type === 'key' ? '密钥' : '密码') : '受保护' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="标签" min-width="140">
          <template #default="{ row }">
            <el-tag v-for="t in row.tags" :key="t" size="small" style="margin-right:4px">{{ t }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tooltip v-if="row.status_reason" :content="row.status_reason" placement="top">
              <el-tag :type="statusTagType(row.status)" size="small" effect="dark">{{ statusCn[row.status] || row.status || '运行中' }}</el-tag>
            </el-tooltip>
            <el-tag v-else :type="statusTagType(row.status)" size="small" effect="dark">{{ statusCn[row.status] || '运行中' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" :disabled="!isAdmin" @change="toggleEnabled(row)" />
          </template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="120" show-overflow-tooltip />
        <el-table-column label="操作" width="230" v-if="isAdmin">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="warning" :loading="testingId === row.id" @click="testExisting(row)">测试</el-button>
            <el-popconfirm title="确定删除该服务器？" @confirm="remove(row)">
              <template #reference>
                <el-button size="small" type="danger">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
      <div class="mobile-only" v-loading="loading">
        <div v-if="filtered.length" class="mobile-card-list">
          <article v-for="row in filtered" :key="row.id" class="mobile-data-card server-mobile-card">
            <div class="mobile-data-card__head">
              <div class="mobile-data-card__title">
                <el-link type="primary" @click="$router.push(`/servers/${row.id}`)">{{ row.name }}</el-link>
                <div class="server-address mono">{{ isAdmin ? `${row.host}:${row.port}` : '地址仅管理员可见' }}</div>
              </div>
              <div class="server-card-status">
                <el-tag :type="(row.server_type || 'gpu') === 'gpu' ? 'success' : 'info'" size="small">{{ (row.server_type || 'gpu') === 'gpu' ? 'GPU' : 'CPU' }}</el-tag>
                <el-tag :type="statusTagType(row.status)" size="small" effect="dark">{{ statusCn[row.status] || '运行中' }}</el-tag>
              </div>
            </div>
            <div v-if="row.tags?.length" class="server-card-tags">
              <el-tag v-for="t in row.tags" :key="t" size="small" effect="plain">{{ t }}</el-tag>
            </div>
            <div class="mobile-data-card__meta">
              <span>认证</span><span>{{ isAdmin ? (row.auth_type === 'key' ? 'SSH 密钥' : '用户名 / 密码') : '受保护' }}</span>
              <span>启用采集</span><el-switch v-model="row.enabled" :disabled="!isAdmin" @change="toggleEnabled(row)" />
              <template v-if="row.status_reason"><span>状态说明</span><span>{{ row.status_reason }}</span></template>
              <template v-if="row.note"><span>备注</span><span>{{ row.note }}</span></template>
            </div>
            <div v-if="isAdmin" class="mobile-data-card__actions">
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button size="small" type="warning" :loading="testingId === row.id" @click="testExisting(row)">测试连接</el-button>
              <el-popconfirm title="确定删除该服务器？" @confirm="remove(row)">
                <template #reference><el-button size="small" type="danger" plain>删除</el-button></template>
              </el-popconfirm>
            </div>
          </article>
        </div>
        <el-empty v-else description="没有符合筛选条件的服务器" :image-size="60" />
      </div>
    </el-card>

    <el-dialog v-model="dlg" :title="editId ? '编辑服务器' : '添加服务器'" width="580px" class="responsive-dialog server-dialog">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px" class="responsive-form">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="如 gpu-node-01" />
        </el-form-item>
        <el-form-item label="主机" prop="host">
          <el-col :span="16">
            <el-input v-model="form.host" placeholder="IP 或主机名" />
          </el-col>
          <el-col :span="7" :offset="1">
            <el-input-number v-model="form.port" :min="1" :max="65535" controls-position="right" style="width:100%" />
          </el-col>
        </el-form-item>
        <el-form-item label="服务器类型" prop="server_type">
          <el-radio-group v-model="form.server_type">
            <el-radio value="gpu">GPU 服务器</el-radio>
            <el-radio value="cpu">CPU 服务器</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="认证方式" prop="auth_type">
          <el-radio-group v-model="form.auth_type">
            <el-radio value="password">用户名 / 密码</el-radio>
            <el-radio value="key">SSH 密钥</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username"
            :placeholder="editId ? '留空保持不变' : 'gpumon'" />
        </el-form-item>
        <template v-if="form.auth_type === 'password'">
          <el-form-item label="密码" prop="password">
            <el-input v-model="form.password" type="password" show-password
              :placeholder="editId && hasPassword ? '留空保持不变' : 'SSH 登录密码'" />
          </el-form-item>
        </template>
        <template v-else>
          <el-form-item label="私钥" prop="private_key">
            <el-input v-model="form.private_key" type="textarea" :rows="5" class="mono"
              :placeholder="editId && hasKey ? '留空保持不变（已配置密钥）' : '-----BEGIN OPENSSH PRIVATE KEY-----'" />
          </el-form-item>
          <el-form-item label="口令">
            <el-input v-model="form.passphrase" type="password" show-password placeholder="私钥口令（没有可留空）" />
          </el-form-item>
        </template>
        <el-form-item label="带外管理">
          <div style="display:flex;gap:8px;flex-wrap:wrap;width:100%">
            <el-input v-model="form.bmc_host" placeholder="BMC/IPMI 地址（可留空）" style="flex:2;min-width:150px" />
            <el-input v-model="form.bmc_user" placeholder="BMC 用户" style="flex:1;min-width:100px" />
            <el-input v-model="form.bmc_password" type="password" show-password
              :placeholder="editId && hasBmc ? '留空保持不变' : 'BMC 密码'" style="flex:1;min-width:120px" />
          </div>
        </el-form-item>
        <el-form-item label="标签">
          <div>
            <el-tag v-for="(t, i) in form.tags" :key="i" closable style="margin-right:6px" @close="form.tags.splice(i, 1)">{{ t }}</el-tag>
            <el-input v-if="tagInput" ref="tagInputRef" v-model="newTag" size="small" style="width:120px"
              @keyup.enter="addTag" @blur="addTag" placeholder="回车添加" />
            <el-button v-else size="small" @click="tagInput = true; newTag = ''">+ 标签</el-button>
          </div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="testConn" :loading="testing">测试连接</el-button>
        <el-button v-if="editId" @click="testIpmi" :loading="testingIpmi">测试 IPMI</el-button>
        <el-button @click="dlg = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import api from '../api'
import { isAdminSession } from '../composables'

const isAdmin = computed(() => isAdminSession())
const loading = ref(false)
const serversList = ref([])
const keyword = ref('')
const tagFilter = ref('')
const statusFilter = ref('')
const statusCn = { active: '运行中', maintenance: '维护中', drained: '已排空', rma: '返修中' }
function statusTagType(s) {
  return s === 'maintenance' ? 'warning' : s === 'rma' ? 'danger' : s === 'drained' ? 'info' : 'success'
}
const dlg = ref(false)
const editId = ref(null)
const hasPassword = ref(false)
const hasKey = ref(false)
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
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  host: [{ required: true, message: '请输入主机地址', trigger: 'blur' }],
  username: [{ required: !editId.value, message: '请输入用户名', trigger: 'blur' }]
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

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/servers')
    serversList.value = data
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editId.value = null
  Object.assign(form, blank())
  hasPassword.value = false
  hasKey.value = false
  dlg.value = true
}

function openEdit(row) {
  editId.value = row.id
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
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  saving.value = true
  try {
    const payload = { ...form }
    if (editId.value) {
      // blank username on edit means "keep the stored one"
      if (!payload.username) delete payload.username
      if (!payload.password) delete payload.password
      if (!payload.private_key) delete payload.private_key
      if (!payload.passphrase) delete payload.passphrase
      if (!payload.bmc_password) delete payload.bmc_password
      await api.put(`/servers/${editId.value}`, payload)
    } else {
      await api.post('/servers', payload)
    }
    ElMessage.success('保存成功')
    dlg.value = false
    load()
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '保存失败')
  } finally {
    saving.value = false
  }
}

async function testIpmi() {
  if (!editId.value) return
  testingIpmi.value = true
  try {
    const payload = { ...form }
    if (!payload.username) delete payload.username
    if (!payload.password) delete payload.password
    if (!payload.private_key) delete payload.private_key
    if (!payload.passphrase) delete payload.passphrase
    if (!payload.bmc_password) delete payload.bmc_password
    await api.put(`/servers/${editId.value}`, payload)
    const { data } = await api.post(`/servers/${editId.value}/ipmi/test`)
    if (data.ok) {
      const s = data.summary || {}
      ElMessage.success(`IPMI 正常 · 电源${s.power_on ? '开启' : '关闭'} · 整机功耗 ${s.power_w}W · 传感器 ${(data.snapshot?.sensors || []).length} 项 · ${data.duration}s`)
      hasBmc.value = true
    } else {
      ElMessage.error('IPMI 连接失败：' + (data.error || '未知错误'))
    }
    load()
  } catch (e) {
    ElMessage.error(e.friendlyMessage || 'IPMI 测试失败')
  } finally {
    testingIpmi.value = false
  }
}

async function remove(row) {
  try {
    await api.delete(`/servers/${row.id}`)
    ElMessage.success('已删除')
    load()
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '删除失败')
  }
}

async function toggleEnabled(row) {
  try {
    await api.put(`/servers/${row.id}`, { enabled: row.enabled })
    ElMessage.success(row.enabled ? '已启用' : '已禁用')
  } catch (e) {
    row.enabled = !row.enabled
    ElMessage.error(e.friendlyMessage || '操作失败')
  }
}

async function testConn() {
  testing.value = true
  try {
    const payload = {
      host: form.host, port: form.port, auth_type: form.auth_type, username: form.username,
      password: form.password || '', private_key: form.private_key || '', passphrase: form.passphrase || ''
    }
    const { data } = await api.post('/servers/test', payload)
    data.ok ? ElMessage.success(data.message) : ElMessage.error(data.message)
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '测试失败')
  } finally {
    testing.value = false
  }
}

async function testExisting(row) {
  testingId.value = row.id
  try {
    const { data } = await api.post(`/servers/${row.id}/test`)
    data.ok ? ElMessage.success(data.message) : ElMessage.error(data.message)
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '测试失败')
  } finally {
    testingId.value = null
  }
}

onMounted(load)
</script>

<style scoped>
.server-card-status { display: flex; flex: 0 0 auto; align-items: center; gap: 6px; }
.server-address { margin-top: 5px; color: var(--csub); font-size: 11px; font-weight: 400; }
.server-card-tags { display: flex; flex-wrap: wrap; gap: 5px; margin: -2px 0 12px; }
.server-mobile-card :deep(.el-switch) { justify-self: start; }
@media (max-width: 768px) {
  .server-toolbar .el-input,
  .server-toolbar .el-select { width: 100% !important; }
  .server-list-card :deep(.el-card__body) { padding: 12px; }
}
</style>
