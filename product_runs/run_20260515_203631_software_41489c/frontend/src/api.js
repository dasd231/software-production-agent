const API_BASE = '/api'

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options
  })
  if (!response.ok) {
    throw new Error(`API ${response.status}: ${path}`)
  }
  return response.json()
}

export function listEmployees() {
  return request('/employees')
}

export function createEmployee(payload) {
  return request('/employees', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function updateEmployee(id, payload) {
  return request(`/employees/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload)
  })
}

export function deleteEmployee(id) {
  return request(`/employees/${id}`, {
    method: 'DELETE'
  })
}

export function loginUser(payload) {
  return request('/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function logoutUser() {
  return request('/auth/logout', { method: 'POST' })
}

export function listApprovals() {
  return request('/workflows/approvals')
}

export function approveWorkflow(id) {
  return request(`/workflows/approvals/${id}/approve`, { method: 'POST' })
}

export function importEmployees() {
  return request('/exchange/employees/import', { method: 'POST' })
}

export function exportEmployees() {
  return request('/exchange/employees/export')
}

export function listAuditLogs() {
  return request('/audit/logs')
}
