<template>
  <div class="cockpit">
    <div class="toolbar users-toolbar">
      <a-button type="primary" @click="openCreate"><template #icon><PlusOutlined /></template>新建用户</a-button>
      <a-button @click="load"><template #icon><ReloadOutlined /></template>刷新</a-button>
      <span class="users-toolbar__spacer"></span>
      <a-button class="change-password-button" @click="pwdDlg = true">修改我的密码</a-button>
    </div>

    <a-row :gutter="[16, 16]" class="users-summary kpi-row" aria-label="用户概况">
      <a-col :span="8"><a-card size="small"><a-statistic title="全部用户" :value="users.length" /></a-card></a-col>
      <a-col :span="8"><a-card size="small"><a-statistic title="已启用" :value="activeUserCount" /></a-card></a-col>
      <a-col :span="8"><a-card size="small"><a-statistic title="管理员" :value="adminCount" /></a-card></a-col>
    </a-row>

    <a-card class="users-list-card">
      <a-table class="desktop-only" :data-source="users" :loading="loading" :pagination="false" :scroll="{ x: 1120, y: 640 }" row-key="id" size="middle">
        <a-table-column data-index="id" title="ID" :width="64" />
        <a-table-column data-index="username" title="用户名" :width="130" ellipsis />
        <a-table-column data-index="display_name" title="显示名" :width="130" ellipsis />
        <a-table-column data-index="email" title="邮箱" :width="190" ellipsis />
        <a-table-column title="角色" :width="100">
          <template #default="{ record: row }">
            <a-tag :color="row.role === 'admin' ? 'red' : undefined">
              {{ row.role === 'admin' ? '管理员' : '查看者' }}
            </a-tag>
          </template>
        </a-table-column>
        <a-table-column title="状态" :width="90">
          <template #default="{ record: row }">
            <a-tag :color="row.is_active ? 'green' : undefined">{{ row.is_active ? '启用' : '禁用' }}</a-tag>
          </template>
        </a-table-column>
        <a-table-column title="MFA" :width="100">
          <template #default="{ record: row }">
            <a-tag v-if="row.role === 'admin'" :color="row.mfa_enrolled ? 'green' : 'red'">
              {{ row.mfa_enrolled ? '已绑定' : '未绑定' }}
            </a-tag>
            <span v-else>—</span>
          </template>
        </a-table-column>
        <a-table-column title="创建时间" :width="170">
          <template #default="{ record: row }">{{ fmtTime(row.created_at) }}</template>
        </a-table-column>
        <a-table-column title="操作" :width="310" fixed="right">
          <template #default="{ record: row }">
            <div class="table-actions">
              <a-button size="small" @click="openEdit(row)">编辑</a-button>
              <a-popconfirm :title="`确定${row.is_active ? '禁用' : '启用'}用户 ${row.username}？`" ok-text="确定" cancel-text="取消" @confirm="toggleActive(row)">
                <a-button size="small" :danger="row.is_active" :disabled="row.id === me?.id" :loading="busyUserIds.has(row.id)">
                  {{ row.is_active ? '禁用' : '启用' }}
                </a-button>
              </a-popconfirm>
              <a-button
                v-if="row.role === 'admin' && row.mfa_enrolled && row.id !== me?.id"
                size="small"
                @click="resetMfa(row)"
              >重置 MFA</a-button>
              <a-popconfirm title="确定删除该用户？" ok-text="删除" cancel-text="取消" @confirm="remove(row)">
                <a-button size="small" danger :disabled="row.id === me?.id">删除</a-button>
              </a-popconfirm>
            </div>
          </template>
        </a-table-column>
      </a-table>

      <a-spin wrapper-class-name="mobile-only" :spinning="loading">
        <div v-if="users.length" class="mobile-card-list">
          <article v-for="row in users" :key="row.id" class="mobile-data-card user-mobile-card">
            <div class="mobile-data-card__head">
              <div class="mobile-data-card__title">
                {{ row.display_name || row.username }}
                <span v-if="row.display_name" class="user-mobile-card__username">@{{ row.username }}</span>
              </div>
              <div class="user-mobile-card__status">
                <a-tag v-if="row.id === me?.id" color="blue">当前账号</a-tag>
                <a-tag :color="row.is_active ? 'green' : undefined">{{ row.is_active ? '启用' : '禁用' }}</a-tag>
              </div>
            </div>
            <div class="mobile-data-card__meta">
              <span>邮箱</span><span class="user-mobile-card__email">{{ row.email || '—' }}</span>
              <span>角色</span><span>{{ row.role === 'admin' ? '管理员' : '查看者' }}</span>
              <span>MFA</span><span>{{ row.role === 'admin' ? (row.mfa_enrolled ? '已绑定' : '未绑定') : '不要求' }}</span>
              <span>创建时间</span><span>{{ fmtTime(row.created_at) }}</span>
            </div>
            <div class="mobile-data-card__actions">
              <a-button size="small" @click="openEdit(row)">编辑</a-button>
              <a-popconfirm :title="`确定${row.is_active ? '禁用' : '启用'}用户 ${row.username}？`" ok-text="确定" cancel-text="取消" @confirm="toggleActive(row)">
                  <a-button size="small" :danger="row.is_active" :disabled="row.id === me?.id" :loading="busyUserIds.has(row.id)">
                    {{ row.is_active ? '禁用' : '启用' }}
                  </a-button>
              </a-popconfirm>
              <a-button
                v-if="row.role === 'admin' && row.mfa_enrolled && row.id !== me?.id"
                size="small"
                @click="resetMfa(row)"
              >重置 MFA</a-button>
              <a-popconfirm title="确定删除该用户？" ok-text="删除" cancel-text="取消" @confirm="remove(row)">
                  <a-button size="small" danger :disabled="row.id === me?.id">删除</a-button>
              </a-popconfirm>
            </div>
          </article>
        </div>
        <a-empty v-else-if="!loading" description="暂无用户" />
      </a-spin>
    </a-card>

    <a-modal v-model:open="dlg" class="responsive-dialog" :title="editId ? '编辑用户' : '新建用户'" :width="480">
      <a-form ref="formRef" class="responsive-form" :model="form" :rules="rules" :label-col="{ style: { width: '84px' } }">
        <a-form-item label="用户名" name="username">
          <a-input v-model:value="form.username" :disabled="!!editId" autocomplete="username" :maxlength="64" />
        </a-form-item>
        <a-form-item label="密码" name="password">
          <a-input-password v-model:value="form.password"
            autocomplete="new-password" :placeholder="editId ? '留空保持不变' : '至少 15 位'" />
        </a-form-item>
        <a-form-item label="显示名">
          <a-input v-model:value="form.display_name" />
        </a-form-item>
        <a-form-item label="邮箱">
          <a-input v-model:value="form.email" />
        </a-form-item>
        <a-form-item label="角色">
          <a-radio-group v-model:value="form.role" :disabled="editId === me?.id">
            <a-radio value="admin">管理员</a-radio>
            <a-radio value="viewer">查看者</a-radio>
          </a-radio-group>
        </a-form-item>
      </a-form>
      <template #footer>
        <a-button @click="dlg = false">取消</a-button>
        <a-button type="primary" :loading="saving" @click="save">保存</a-button>
      </template>
    </a-modal>

    <a-modal v-model:open="pwdDlg" class="responsive-dialog" title="修改我的密码" :width="440">
      <a-form ref="pwdFormRef" class="responsive-form" :model="pwdForm" :rules="pwdRules" :label-col="{ style: { width: '96px' } }">
        <a-form-item label="当前密码" name="old_password">
          <a-input-password v-model:value="pwdForm.old_password" autocomplete="current-password" />
        </a-form-item>
        <a-form-item label="新密码" name="new_password">
          <a-input-password v-model:value="pwdForm.new_password" autocomplete="new-password" placeholder="至少 15 位" />
        </a-form-item>
        <a-form-item label="确认新密码" name="confirm">
          <a-input-password v-model:value="pwdForm.confirm" autocomplete="new-password" />
        </a-form-item>
      </a-form>
      <template #footer>
        <a-button @click="pwdDlg = false">取消</a-button>
        <a-button type="primary" :loading="savingPwd" @click="changePwd">修改</a-button>
      </template>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { App as AntApp } from 'ant-design-vue'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import api from '../api'
import { clearSession, getSession, setSession } from '../composables'
import { fmtTime } from '../format'

const loading = ref(false)
const router = useRouter()
const { message, modal } = AntApp.useApp()
const users = ref([])
const dlg = ref(false)
const editId = ref(null)
const saving = ref(false)
const formRef = ref()
const originalRole = ref(null)
const busyUserIds = reactive(new Set())

const pwdDlg = ref(false)
const savingPwd = ref(false)
const pwdFormRef = ref()
const pwdForm = reactive({ old_password: '', new_password: '', confirm: '' })

const me = computed(() => getSession().user)
const activeUserCount = computed(() => users.value.filter(user => user.is_active).length)
const adminCount = computed(() => users.value.filter(user => user.role === 'admin').length)

const blank = () => ({ username: '', password: '', display_name: '', email: '', role: 'viewer' })
const form = reactive(blank())

const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 2, max: 64, message: '用户名须为 2–64 个字符', trigger: 'blur' }
  ],
  password: [
    { validator: (r, v, cb) => {
      if (!editId.value && !v) cb(new Error('请输入密码'))
      else if (v && ([...v].length < 15 || [...v].length > 72)) cb(new Error('密码须为 15–72 个字符'))
      else cb()
    }, trigger: 'blur' }
  ]
}

const pwdRules = {
  old_password: [
    { required: true, message: '请输入当前密码', trigger: 'blur' },
    { max: 128, message: '当前密码最多 128 个字符', trigger: 'blur' }
  ],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { validator: (_, value) => [...(value || '')].length >= 15 && [...value].length <= 72
      ? Promise.resolve() : Promise.reject(new Error('密码须为 15–72 个字符')), trigger: 'blur' }
  ],
  confirm: [
    { validator: (r, v, cb) => v === pwdForm.new_password ? cb() : cb(new Error('两次密码不一致')), trigger: 'blur' }
  ]
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/users')
    users.value = data
  } catch (e) {
    message.error(e.friendlyMessage || '加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editId.value = null
  originalRole.value = null
  Object.assign(form, blank())
  dlg.value = true
}

function openEdit(row) {
  editId.value = row.id
  originalRole.value = row.role
  Object.assign(form, blank(), {
    username: row.username, display_name: row.display_name, email: row.email, role: row.role
  })
  dlg.value = true
}

async function save() {
  if (saving.value) return
  saving.value = true
  try {
    await formRef.value.validate()
  } catch {
    saving.value = false
    return
  }
  try {
    if (editId.value) {
      const payload = { display_name: form.display_name, email: form.email }
      if (form.role !== originalRole.value) payload.role = form.role
      if (form.password) payload.password = form.password
      const { data } = await api.put(`/users/${editId.value}`, payload)
      if (editId.value === me.value?.id) {
        if (payload.password) {
          clearSession()
          dlg.value = false
          message.success('密码已重置，请重新登录')
          await router.replace('/login')
          return
        }
        setSession(data)
      }
    } else {
      await api.post('/users', form)
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

async function toggleActive(row) {
  if (row.id === me.value?.id || busyUserIds.has(row.id)) return
  busyUserIds.add(row.id)
  try {
    await api.put(`/users/${row.id}`, { is_active: !row.is_active })
    row.is_active = !row.is_active
    message.success(row.is_active ? '已启用' : '已禁用')
  } catch (e) {
    message.error(e.friendlyMessage || '操作失败')
  } finally {
    busyUserIds.delete(row.id)
  }
}

async function remove(row) {
  try {
    await api.delete(`/users/${row.id}`)
    message.success('已删除')
    load()
  } catch (e) {
    message.error(e.friendlyMessage || '删除失败')
  }
}

function resetMfa(row) {
  modal.confirm({
    title: '重置 MFA',
    content: `确认重置管理员 ${row.username} 的 MFA？其所有现有会话会立即失效。`,
    okText: '确认重置',
    cancelText: '取消',
    okType: 'danger',
    async onOk() {
      await runResetMfa(row)
    },
  })
}

async function runResetMfa(row) {
  try {
    await api.post(`/users/${row.id}/reset-mfa`)
    message.success('MFA 已重置；该管理员下次登录必须重新绑定')
    load()
  } catch (e) {
    message.error(e.friendlyMessage || 'MFA 重置失败')
    throw e
  }
}

async function changePwd() {
  if (savingPwd.value) return
  savingPwd.value = true
  try {
    await pwdFormRef.value.validate()
  } catch {
    savingPwd.value = false
    return
  }
  try {
    await api.post('/users/change-password', { old_password: pwdForm.old_password, new_password: pwdForm.new_password })
    message.success('密码已修改')
    pwdDlg.value = false
    Object.assign(pwdForm, { old_password: '', new_password: '', confirm: '' })
  } catch (e) {
    message.error(e.friendlyMessage || '修改失败')
  } finally {
    savingPwd.value = false
  }
}

watch(dlg, (open) => { if (!open) form.password = '' })
watch(pwdDlg, (open) => {
  if (!open) Object.assign(pwdForm, { old_password: '', new_password: '', confirm: '' })
})

onMounted(load)
</script>

<style scoped>
.users-toolbar__spacer { flex: 1; }
.users-summary {
  margin-bottom: 16px;
}
.table-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.user-mobile-card__username {
  display: block;
  margin-top: 2px;
  color: var(--csub);
  font-size: 11px;
  font-weight: 400;
}
.user-mobile-card__status {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 5px;
}
.user-mobile-card__email { overflow-wrap: anywhere; }

@media (max-width: 768px) {
  .users-toolbar > .ant-btn:not(.change-password-button) { flex: 1; }
  .users-toolbar__spacer { display: none; }
  .change-password-button { width: 100%; margin-left: 0; }
  .users-summary { max-width: none; }
  .users-summary :deep(.ant-card-body) { padding: 10px; }
  .users-summary :deep(.ant-statistic-title) { font-size: 12px; }
  .users-summary :deep(.ant-statistic-content) { font-size: 18px; }
  .users-list-card :deep(.ant-card-body) { padding: 12px; }
  .mobile-data-card__actions :deep(.ant-btn + .ant-btn) { margin-left: 0; }
}
</style>
