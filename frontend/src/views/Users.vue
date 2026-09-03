<template>
  <div class="cockpit">
    <div class="toolbar users-toolbar">
      <el-button type="primary" :icon="Plus" @click="openCreate">新建用户</el-button>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
      <span class="users-toolbar__spacer"></span>
      <el-button class="change-password-button" plain type="primary" @click="pwdDlg = true">修改我的密码</el-button>
    </div>

    <div class="users-summary" aria-label="用户概况">
      <div><b>{{ users.length }}</b><span>全部用户</span></div>
      <div><b>{{ activeUserCount }}</b><span>已启用</span></div>
      <div><b>{{ adminCount }}</b><span>管理员</span></div>
    </div>

    <el-card class="users-list-card">
      <el-table class="desktop-only" :data="users" v-loading="loading" max-height="640">
        <el-table-column prop="id" label="ID" width="54" />
        <el-table-column prop="username" label="用户名" min-width="105" />
        <el-table-column prop="display_name" label="显示名" min-width="105" />
        <el-table-column prop="email" label="邮箱" min-width="145" show-overflow-tooltip />
        <el-table-column label="角色" width="90">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : 'info'" size="small">
              {{ row.role === 'admin' ? '管理员' : '查看者' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="76">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用' : '禁用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="MFA" width="82">
          <template #default="{ row }">
            <el-tag v-if="row.role === 'admin'" :type="row.mfa_enrolled ? 'success' : 'danger'" size="small">
              {{ row.mfa_enrolled ? '已绑定' : '未绑定' }}
            </el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="158">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="290">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" :type="row.is_active ? 'warning' : 'success'" @click="toggleActive(row)">
              {{ row.is_active ? '禁用' : '启用' }}
            </el-button>
            <el-button
              v-if="row.role === 'admin' && row.mfa_enrolled && row.id !== me?.id"
              size="small"
              type="warning"
              plain
              @click="resetMfa(row)"
            >重置 MFA</el-button>
            <el-popconfirm title="确定删除该用户？" @confirm="remove(row)">
              <template #reference>
                <el-button size="small" type="danger" :disabled="row.id === me?.id">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-only" v-loading="loading">
        <div v-if="users.length" class="mobile-card-list">
          <article v-for="row in users" :key="row.id" class="mobile-data-card user-mobile-card">
            <div class="mobile-data-card__head">
              <div class="mobile-data-card__title">
                {{ row.display_name || row.username }}
                <span v-if="row.display_name" class="user-mobile-card__username">@{{ row.username }}</span>
              </div>
              <div class="user-mobile-card__status">
                <el-tag v-if="row.id === me?.id" type="primary" effect="plain" size="small">当前账号</el-tag>
                <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用' : '禁用' }}</el-tag>
              </div>
            </div>
            <div class="mobile-data-card__meta">
              <span>邮箱</span><span class="user-mobile-card__email">{{ row.email || '—' }}</span>
              <span>角色</span><span>{{ row.role === 'admin' ? '管理员' : '查看者' }}</span>
              <span>MFA</span><span>{{ row.role === 'admin' ? (row.mfa_enrolled ? '已绑定' : '未绑定') : '不要求' }}</span>
              <span>创建时间</span><span>{{ fmtTime(row.created_at) }}</span>
            </div>
            <div class="mobile-data-card__actions">
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
              <el-button size="small" :type="row.is_active ? 'warning' : 'success'" plain @click="toggleActive(row)">
                {{ row.is_active ? '禁用' : '启用' }}
              </el-button>
              <el-button
                v-if="row.role === 'admin' && row.mfa_enrolled && row.id !== me?.id"
                size="small"
                type="warning"
                plain
                @click="resetMfa(row)"
              >重置 MFA</el-button>
              <el-popconfirm title="确定删除该用户？" @confirm="remove(row)">
                <template #reference>
                  <el-button size="small" type="danger" plain :disabled="row.id === me?.id">删除</el-button>
                </template>
              </el-popconfirm>
            </div>
          </article>
        </div>
        <el-empty v-else-if="!loading" description="暂无用户" :image-size="72" />
      </div>
    </el-card>

    <el-dialog v-model="dlg" class="responsive-dialog" :title="editId ? '编辑用户' : '新建用户'" width="460px">
      <el-form ref="formRef" class="responsive-form" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" :disabled="!!editId" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password
            autocomplete="new-password" :placeholder="editId ? '留空保持不变' : '至少 15 位'" />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="form.display_name" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" />
        </el-form-item>
        <el-form-item label="角色">
          <el-radio-group v-model="form.role" :disabled="editId === me?.id">
            <el-radio value="admin">管理员</el-radio>
            <el-radio value="viewer">查看者</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="pwdDlg" class="responsive-dialog" title="修改我的密码" width="420px">
      <el-form ref="pwdFormRef" class="responsive-form" :model="pwdForm" :rules="pwdRules" label-width="90px">
        <el-form-item label="当前密码" prop="old_password">
          <el-input v-model="pwdForm.old_password" type="password" show-password autocomplete="current-password" />
        </el-form-item>
        <el-form-item label="新密码" prop="new_password">
          <el-input v-model="pwdForm.new_password" type="password" show-password autocomplete="new-password" placeholder="至少 15 位" />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirm">
          <el-input v-model="pwdForm.confirm" type="password" show-password autocomplete="new-password" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdDlg = false">取消</el-button>
        <el-button type="primary" :loading="savingPwd" @click="changePwd">修改</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import api from '../api'
import { getSession, setSession } from '../composables'
import { fmtTime } from '../format'

const loading = ref(false)
const users = ref([])
const dlg = ref(false)
const editId = ref(null)
const saving = ref(false)
const formRef = ref()

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
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [
    { validator: (r, v, cb) => {
      if (!editId.value && !v) cb(new Error('请输入密码'))
      else if (v && v.length < 15) cb(new Error('密码至少 15 位'))
      else cb()
    }, trigger: 'blur' }
  ]
}

const pwdRules = {
  old_password: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 15, message: '密码至少 15 位', trigger: 'blur' }
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
    ElMessage.error(e.friendlyMessage || '加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editId.value = null
  Object.assign(form, blank())
  dlg.value = true
}

function openEdit(row) {
  editId.value = row.id
  Object.assign(form, blank(), {
    username: row.username, display_name: row.display_name, email: row.email, role: row.role
  })
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
    if (editId.value) {
      const payload = { display_name: form.display_name, email: form.email, role: form.role }
      if (form.password) payload.password = form.password
      await api.put(`/users/${editId.value}`, payload)
    } else {
      await api.post('/users', form)
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

async function toggleActive(row) {
  try {
    await api.put(`/users/${row.id}`, { is_active: !row.is_active })
    row.is_active = !row.is_active
    ElMessage.success(row.is_active ? '已启用' : '已禁用')
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '操作失败')
  }
}

async function remove(row) {
  try {
    await api.delete(`/users/${row.id}`)
    ElMessage.success('已删除')
    load()
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '删除失败')
  }
}

async function resetMfa(row) {
  try {
    await ElMessageBox.confirm(
      `确认重置管理员 ${row.username} 的 MFA？其所有现有会话会立即失效。`,
      '重置 MFA',
      { type: 'warning' }
    )
    await api.post(`/users/${row.id}/reset-mfa`)
    ElMessage.success('MFA 已重置；该管理员下次登录必须重新绑定')
    load()
  } catch (e) {
    if (e && e !== 'cancel' && e.friendlyMessage) ElMessage.error(e.friendlyMessage)
  }
}

async function changePwd() {
  try {
    await pwdFormRef.value.validate()
  } catch {
    return
  }
  savingPwd.value = true
  try {
    const { data } = await api.post('/users/change-password', { old_password: pwdForm.old_password, new_password: pwdForm.new_password })
    if (data.access_token) {
      // The backend replaced the HttpOnly cookie with the new token version.
      setSession(getSession().user)
    }
    ElMessage.success('密码已修改')
    pwdDlg.value = false
    Object.assign(pwdForm, { old_password: '', new_password: '', confirm: '' })
  } catch (e) {
    ElMessage.error(e.friendlyMessage || '修改失败')
  } finally {
    savingPwd.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.users-toolbar__spacer { flex: 1; }
.users-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  max-width: 520px;
  margin-bottom: 14px;
}
.users-summary > div {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 11px 13px;
  border: 1px solid var(--cborder);
  border-radius: 9px;
  background: var(--cpanel);
}
.users-summary b {
  color: var(--cprimary);
  font-size: 20px;
  font-variant-numeric: tabular-nums;
}
.users-summary span { color: var(--csub); font-size: 12px; }
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
  .users-toolbar > .el-button:not(.change-password-button) { flex: 1; }
  .users-toolbar__spacer { display: none; }
  .change-password-button { width: 100%; margin-left: 0; }
  .users-summary { max-width: none; gap: 7px; }
  .users-summary > div {
    align-items: center;
    flex-direction: column;
    gap: 1px;
    padding: 9px 4px;
    text-align: center;
  }
  .users-summary b { font-size: 18px; }
  .users-list-card :deep(.el-card__body) { padding: 12px; }
  .mobile-data-card__actions :deep(.el-button + .el-button) { margin-left: 0; }
}
</style>
