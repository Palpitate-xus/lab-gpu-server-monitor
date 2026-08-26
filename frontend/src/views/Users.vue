<template>
  <div class="cockpit">
    <div class="toolbar">
      <el-button type="primary" :icon="Plus" @click="openCreate">新建用户</el-button>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
      <span style="flex:1"></span>
      <el-button text type="primary" @click="pwdDlg = true">修改我的密码</el-button>
    </div>

    <el-card>
      <el-table :data="users" v-loading="loading" max-height="640">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="username" label="用户名" min-width="120" />
        <el-table-column prop="display_name" label="显示名" min-width="120" />
        <el-table-column prop="email" label="邮箱" min-width="160" show-overflow-tooltip />
        <el-table-column label="角色" width="100">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : 'info'" size="small">
              {{ row.role === 'admin' ? '管理员' : '查看者' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用' : '禁用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="240">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" :type="row.is_active ? 'warning' : 'success'" @click="toggleActive(row)">
              {{ row.is_active ? '禁用' : '启用' }}
            </el-button>
            <el-popconfirm title="确定删除该用户？" @confirm="remove(row)">
              <template #reference>
                <el-button size="small" type="danger" :disabled="row.id === me?.id">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dlg" :title="editId ? '编辑用户' : '新建用户'" width="460px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" :disabled="!!editId" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password
            :placeholder="editId ? '留空保持不变' : '至少 6 位'" />
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

    <el-dialog v-model="pwdDlg" title="修改我的密码" width="420px">
      <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-width="90px">
        <el-form-item label="当前密码" prop="old_password">
          <el-input v-model="pwdForm.old_password" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码" prop="new_password">
          <el-input v-model="pwdForm.new_password" type="password" show-password />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirm">
          <el-input v-model="pwdForm.confirm" type="password" show-password />
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
import { ElMessage } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import api from '../api'
import { getSession } from '../composables'
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

const blank = () => ({ username: '', password: '', display_name: '', email: '', role: 'viewer' })
const form = reactive(blank())

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [
    { validator: (r, v, cb) => {
      if (!editId.value && !v) cb(new Error('请输入密码'))
      else if (v && v.length < 6) cb(new Error('密码至少 6 位'))
      else cb()
    }, trigger: 'blur' }
  ]
}

const pwdRules = {
  old_password: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' }
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
  await formRef.value.validate().catch(() => Promise.reject())
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

async function changePwd() {
  await pwdFormRef.value.validate().catch(() => Promise.reject())
  savingPwd.value = true
  try {
    await api.post('/users/change-password', { old_password: pwdForm.old_password, new_password: pwdForm.new_password })
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
