<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { createEmployee, deleteEmployee as removeEmployee, listEmployees, loginUser, updateEmployee } from './api'

const goal = '写一个成熟的 Spring Boot + Vue 人员管理系统，包含员工 CRUD、部门岗位、工资、API 契约、数据库设计、测试、交付清单和静态预览。本次是 '
const authEnabled = false
const workflowEnabled = false
const importExportEnabled = false
const auditEnabled = false
const currentUser = ref(authEnabled ? null : { name: '本地演示用户', role: 'HR_ADMIN' })
const loginForm = reactive({ username: 'admin', password: 'admin123' })
const loginMessage = ref('')
const departments = ['研发部', '财务部', '人事部', '市场部']
const positions = ['后端工程师', '前端工程师', '薪酬专员', 'HRBP', '产品经理']
const employees = ref([
  { id: 1, name: '林夏', department: '研发部', position: '后端工程师', salary: 15000, status: '在职' },
  { id: 2, name: '周澄', department: '研发部', position: '前端工程师', salary: 13000, status: '试用' },
  { id: 3, name: '许诺', department: '财务部', position: '薪酬专员', salary: 11000, status: '在职' },
  { id: 4, name: '陈一', department: '人事部', position: 'HRBP', salary: 12000, status: '待调岗' }
])
const query = ref('')
const departmentFilter = ref('')
const editingId = ref(null)
const apiMode = ref('local fallback')
const form = reactive({ name: '', department: '研发部', position: '后端工程师', salary: 12000, status: '在职' })
const approvals = ref([
  { id: 1, title: '薪资调整审批', employee: '林夏', status: '部门负责人审批中' },
  { id: 2, title: '岗位调动审批', employee: '陈一', status: '人事复核中' },
  { id: 3, title: '新员工入职审批', employee: '王新', status: '待提交材料' }
])
const auditLogs = ref([
  { actor: 'admin', action: 'LOGIN', target: 'auth', time: '2026-05-07 09:00' },
  { actor: 'admin', action: 'UPDATE_EMPLOYEE', target: 'employee#1', time: '2026-05-07 09:06' },
  { actor: 'admin', action: 'APPROVE_WORKFLOW', target: 'approval#2', time: '2026-05-07 09:12' }
])
const exchangeStatus = ref('等待导入导出操作')

const filteredEmployees = computed(() => {
  const needle = query.value.trim().toLowerCase()
  return employees.value.filter((employee) => {
    const matchesQuery = [employee.name, employee.department, employee.position, employee.status]
      .join(' ')
      .toLowerCase()
      .includes(needle)
    return matchesQuery && (!departmentFilter.value || employee.department === departmentFilter.value)
  })
})

const averageSalary = computed(() => {
  if (!employees.value.length) return 0
  const total = employees.value.reduce((sum, employee) => sum + Number(employee.salary || 0), 0)
  return Math.round(total / employees.value.length)
})

function resetForm() {
  editingId.value = null
  Object.assign(form, { name: '', department: '研发部', position: '后端工程师', salary: 12000, status: '在职' })
}

async function login() {
  loginMessage.value = ''
  try {
    const result = await loginUser(loginForm)
    currentUser.value = result.user || { name: loginForm.username, role: 'HR_ADMIN' }
    apiMode.value = 'backend api'
  } catch {
    if (loginForm.username.trim() && loginForm.password.trim()) {
      currentUser.value = { name: '系统管理员', role: 'HR_ADMIN' }
      apiMode.value = 'local fallback'
    } else {
      loginMessage.value = '请输入用户名和密码'
    }
  }
}

function logout() {
  currentUser.value = null
}

onMounted(async () => {
  try {
    employees.value = await listEmployees()
    apiMode.value = 'backend api'
  } catch {
    apiMode.value = 'local fallback'
  }
})

async function submitEmployee() {
  const payload = { ...form, salary: Number(form.salary || 0) }
  if (!payload.name.trim()) return
  try {
    if (editingId.value) {
      const updated = await updateEmployee(editingId.value, payload)
      employees.value = employees.value.map((employee) =>
        employee.id === editingId.value ? updated : employee
      )
    } else {
      const created = await createEmployee(payload)
      employees.value = [...employees.value, created]
    }
    apiMode.value = 'backend api'
  } catch {
    if (editingId.value) {
      employees.value = employees.value.map((employee) =>
        employee.id === editingId.value ? { ...employee, ...payload } : employee
      )
    } else {
      const nextId = Math.max(0, ...employees.value.map((employee) => employee.id)) + 1
      employees.value = [...employees.value, { id: nextId, ...payload }]
    }
    apiMode.value = 'local fallback'
  }
  resetForm()
}

function editEmployee(employee) {
  editingId.value = employee.id
  Object.assign(form, {
    name: employee.name,
    department: employee.department,
    position: employee.position,
    salary: employee.salary,
    status: employee.status
  })
}

async function deleteEmployee(id) {
  try {
    await removeEmployee(id)
    apiMode.value = 'backend api'
  } catch {
    apiMode.value = 'local fallback'
  }
  employees.value = employees.value.filter((employee) => employee.id !== id)
  if (editingId.value === id) resetForm()
}

function approveItem(id) {
  approvals.value = approvals.value.map((item) =>
    item.id === id ? { ...item, status: '已通过' } : item
  )
  auditLogs.value = [
    { actor: 'admin', action: 'APPROVE_WORKFLOW', target: `approval#${id}`, time: '刚刚' },
    ...auditLogs.value
  ]
}

function simulateImport() {
  exchangeStatus.value = '已模拟导入 3 条员工数据'
  auditLogs.value = [
    { actor: 'admin', action: 'IMPORT_EMPLOYEES', target: 'csv-demo', time: '刚刚' },
    ...auditLogs.value
  ]
}

function simulateExport() {
  exchangeStatus.value = '已生成员工导出预览数据'
  auditLogs.value = [
    { actor: 'admin', action: 'EXPORT_EMPLOYEES', target: 'employee-export', time: '刚刚' },
    ...auditLogs.value
  ]
}
</script>

<template>
  <main v-if="authEnabled && !currentUser" class="login-shell">
    <section class="login-card card">
      <p class="eyebrow">人员管理系统</p>
      <h1>登录页面</h1>
      <p>默认演示账号：admin / admin123。登录后进入带角色权限的人事管理工作台。</p>
      <form class="login-form" @submit.prevent="login">
        <input v-model="loginForm.username" placeholder="用户名" />
        <input v-model="loginForm.password" placeholder="密码" type="password" />
        <button type="submit">登录进入系统</button>
      </form>
      <p class="login-message">{{ loginMessage }}</p>
      <div class="permission-list">
        <span>HR_ADMIN</span>
        <span>employee:read</span>
        <span>employee:write</span>
        <span>audit:read</span>
      </div>
    </section>
  </main>
  <main v-else class="shell">
    <section class="summary card">
      <p class="eyebrow">Software Production Agent</p>
      <h1>人员管理 CRUD</h1>
      <p>{{ goal }}</p>
      <div class="stats">
        <div><span>员工</span><strong>{{ employees.length }}</strong></div>
        <div><span>平均工资</span><strong>{{ averageSalary }}</strong></div>
        <div><span>接口模式</span><strong>{{ apiMode }}</strong></div>
      </div>
      <div v-if="authEnabled" class="auth-strip">
        <span>当前用户：{{ currentUser.name }}</span>
        <span>角色：{{ currentUser.role }}</span>
        <button type="button" class="ghost" @click="logout">退出登录</button>
      </div>
    </section>
    <section class="card form-card">
      <h2>{{ editingId ? '编辑员工' : '新增员工' }}</h2>
      <form class="form" @submit.prevent="submitEmployee">
        <input v-model="form.name" placeholder="姓名" />
        <select v-model="form.department">
          <option v-for="department in departments" :key="department">{{ department }}</option>
        </select>
        <select v-model="form.position">
          <option v-for="position in positions" :key="position">{{ position }}</option>
        </select>
        <input v-model.number="form.salary" type="number" min="0" placeholder="工资" />
        <select v-model="form.status">
          <option>在职</option>
          <option>试用</option>
          <option>待调岗</option>
          <option>离职</option>
        </select>
        <button type="submit">{{ editingId ? '保存修改' : '新增员工' }}</button>
        <button type="button" class="ghost" @click="resetForm">清空</button>
      </form>
    </section>
    <section class="card table-card">
      <div class="toolbar">
        <input v-model="query" placeholder="搜索姓名、部门、岗位或状态" />
        <select v-model="departmentFilter">
          <option value="">全部部门</option>
          <option v-for="department in departments" :key="department">{{ department }}</option>
        </select>
      </div>
      <table>
        <thead>
          <tr><th>姓名</th><th>部门</th><th>岗位</th><th>工资</th><th>状态</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="employee in filteredEmployees" :key="employee.id">
            <td>{{ employee.name }}</td>
            <td>{{ employee.department }}</td>
            <td>{{ employee.position }}</td>
            <td>{{ employee.salary }}</td>
            <td><span class="badge">{{ employee.status }}</span></td>
            <td class="row-actions">
              <button type="button" class="ghost" @click="editEmployee(employee)">编辑</button>
              <button type="button" class="danger" @click="deleteEmployee(employee.id)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>
    <section v-if="workflowEnabled || importExportEnabled || auditEnabled" class="feature-grid">
      <article v-if="workflowEnabled" class="card module-card">
        <h2>审批流</h2>
        <div v-for="item in approvals" :key="item.id" class="module-row">
          <span>{{ item.title }} · {{ item.employee }}</span>
          <strong>{{ item.status }}</strong>
          <button type="button" class="ghost" @click="approveItem(item.id)">通过</button>
        </div>
      </article>
      <article v-if="importExportEnabled" class="card module-card">
        <h2>导入导出</h2>
        <p>{{ exchangeStatus }}</p>
        <div class="row-actions">
          <button type="button" @click="simulateImport">模拟导入</button>
          <button type="button" class="ghost" @click="simulateExport">导出预览</button>
        </div>
      </article>
      <article v-if="auditEnabled" class="card module-card">
        <h2>操作审计</h2>
        <div v-for="log in auditLogs" :key="log.action + log.time" class="module-row">
          <span>{{ log.actor }} · {{ log.action }}</span>
          <strong>{{ log.target }}</strong>
          <em>{{ log.time }}</em>
        </div>
      </article>
    </section>
  </main>
</template>

<style scoped>
.shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(260px, 0.7fr) minmax(380px, 1fr);
  gap: 16px;
  align-items: start;
  padding: 48px;
  background: #f6f7f3;
  color: #151817;
  font-family: Inter, system-ui, sans-serif;
}
.login-shell {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 32px;
  background: #f6f7f3;
  color: #151817;
  font-family: Inter, system-ui, sans-serif;
}
.login-card {
  width: min(460px, calc(100vw - 32px));
}
.login-card h1 {
  margin: 0 0 10px;
  font-size: 42px;
  letter-spacing: 0;
}
.login-form {
  display: grid;
  gap: 10px;
  margin-top: 18px;
}
.login-message {
  min-height: 22px;
  color: #9b3d26;
}
.permission-list, .auth-strip {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 14px;
}
.permission-list span, .auth-strip span {
  border: 1px solid #d9ded4;
  border-radius: 999px;
  padding: 6px 9px;
  background: #f5fbf7;
  color: #12513b;
  font-size: 12px;
  font-weight: 720;
}
.summary h1 {
  margin: 0 0 12px;
  font-size: 40px;
  letter-spacing: 0;
}
.eyebrow {
  color: #1b7b54;
  font-weight: 760;
}
.card {
  border: 1px solid #d9ded4;
  border-radius: 8px;
  padding: 22px;
  background: white;
  box-shadow: 0 16px 40px rgba(22, 28, 24, 0.08);
}
.table-card, .feature-grid { grid-column: 1 / -1; }
.feature-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }
.module-card { display: grid; gap: 10px; }
.module-row { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 8px; align-items: center; border: 1px solid #d9ded4; border-radius: 8px; padding: 9px; background: #fbfcf8; }
.module-row em { color: #687269; font-style: normal; font-size: 12px; }
.stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 18px; }
.stats div { border: 1px solid #d9ded4; border-radius: 8px; padding: 12px; background: #fbfcf8; }
.stats strong { display: block; font-size: 24px; }
.form, .toolbar { display: flex; gap: 10px; flex-wrap: wrap; }
input, select { min-height: 40px; border: 1px solid #cbd1c7; border-radius: 8px; padding: 0 10px; font: inherit; }
button { min-height: 40px; border: 0; border-radius: 8px; padding: 0 14px; background: #151817; color: white; font-weight: 760; cursor: pointer; }
button.ghost { background: #fff; color: #151817; border: 1px solid #d9ded4; }
button.danger { background: #fff3ef; color: #9b3d26; border: 1px solid #efc7b9; }
table { width: 100%; border-collapse: collapse; margin-top: 14px; }
th, td { padding: 12px; border-bottom: 1px solid #d9ded4; text-align: left; }
th { color: #5f6861; font-size: 13px; }
.badge { border-radius: 999px; padding: 4px 8px; background: #e9f7ef; color: #12513b; font-size: 12px; }
.row-actions { display: flex; gap: 8px; }
@media (max-width: 760px) {
  .shell { grid-template-columns: 1fr; padding: 24px; }
  .table-card { grid-column: auto; overflow-x: auto; }
}
</style>
