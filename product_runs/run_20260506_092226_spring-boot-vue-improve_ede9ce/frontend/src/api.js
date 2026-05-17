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
