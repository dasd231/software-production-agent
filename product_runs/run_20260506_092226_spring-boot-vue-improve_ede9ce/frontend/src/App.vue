<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { createEmployee, deleteEmployee as removeEmployee, listEmployees, updateEmployee } from './api'

const goal = '基于上一版软件方案继续改进，不要从零开始。 上一版 run: run_20260506_092224_spring-boot-vue_aec4cd 上一版原始需'
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
</script>

<template>
  <main class="shell">
    <section class="summary card">
      <p class="eyebrow">Software Production Agent</p>
      <h1>人员管理 CRUD</h1>
      <p>{{ goal }}</p>
      <div class="stats">
        <div><span>员工</span><strong>{{ employees.length }}</strong></div>
        <div><span>平均工资</span><strong>{{ averageSalary }}</strong></div>
        <div><span>接口模式</span><strong>{{ apiMode }}</strong></div>
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
.table-card { grid-column: 1 / -1; }
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
