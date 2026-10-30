// Same-origin API client. Session cookies authenticate users; CSRF tokens protect writes.
export const MODELS = [
  { id: 'llama-3.3-70b-versatile', label: 'Llama 3.3 70B' },
  { id: 'openai/gpt-oss-120b', label: 'GPT OSS 120B' },
  { id: 'openai/gpt-oss-20b', label: 'GPT OSS 20B' },
  { id: 'meta-llama/llama-4-scout-17b-16e-instruct', label: 'Llama 4 Scout' },
  { id: 'qwen/qwen3-32b', label: 'Qwen3 32B' },
  { id: 'llama-3.1-8b-instant', label: 'Llama 3.1 8B' },
]

function readCookie(name) {
  const entry = document.cookie.split('; ').find((part) => part.startsWith(`${name}=`))
  return entry ? decodeURIComponent(entry.split('=').slice(1).join('=')) : ''
}

async function request(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase()
  const headers = { 'Content-Type': 'application/json', ...options.headers }
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    await fetch('/api/csrf/', { credentials: 'same-origin' })
    const token = readCookie('csrftoken')
    if (token) headers['X-CSRFToken'] = token
  }
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...options,
    method,
    headers,
  })
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const data = await response.json()
      if (data.error) message = data.error
    } catch {
      // Keep the generic message.
    }
    throw new Error(message)
  }
  if (response.status === 204) return null
  return response.json()
}

export function getMe() { return request('/api/auth/me/') }
export function register(username, password) {
  return request('/api/auth/register/', { method: 'POST', body: JSON.stringify({ username, password }) })
}
export function login(username, password) {
  return request('/api/auth/login/', { method: 'POST', body: JSON.stringify({ username, password }) })
}
export function logout() { return request('/api/auth/logout/', { method: 'POST', body: '{}' }) }
export function sendChat(message, conversationId, model) {
  return request('/api/chat/', { method: 'POST', body: JSON.stringify({ message, conversation_id: conversationId, model }) })
}
export function listConversations() { return request('/api/conversations/') }
export function getConversation(id) { return request(`/api/conversations/${id}/`) }
export function deleteConversation(id) {
  return request(`/api/conversations/${id}/delete/`, { method: 'DELETE' })
}
export function listMemories() { return request('/api/memories/') }
export function deleteMemory(id) {
  return request(`/api/memories/${id}/delete/`, { method: 'DELETE' })
}
