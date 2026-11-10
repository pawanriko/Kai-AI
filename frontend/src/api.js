// API client: every call the UI makes to the Django backend lives here.
// All URLs are relative (/api/...) — Vite's dev proxy forwards them to
// Django on :8000, and in production Django serves this app itself, so
// the same paths work in both worlds. The browser never sees an AI key.

// The model catalogue comes from the backend (GET /api/models/): a
// list of providers, each with its models and a `configured` flag
// telling whether that provider's API key exists in the server's .env.
// A picker choice is encoded as "provider::model".

// Django protects every state-changing request with a CSRF token.
// The token lives in the `csrftoken` cookie (planted by
// GET /api/auth/me/); read it FRESH before every request — Django
// rotates it at login, so a cached copy would go stale.
function csrfToken() {
  const match = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/)
  return match ? decodeURIComponent(match[1]) : ''
}

async function request(path, options = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (options.method && options.method !== 'GET') {
    headers['X-CSRFToken'] = csrfToken()
  }
  const response = await fetch(path, {
    headers,
    ...options,
  })
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const data = await response.json()
      if (data.error) message = data.error
    } catch {
      // keep the generic message
    }
    // Carry the HTTP status so the app can react precisely — a 401
    // from a data endpoint means the session expired and the user
    // belongs back on the login screen, not staring at an error.
    const error = new Error(message)
    error.status = response.status
    throw error
  }
  if (response.status === 204) return null
  return response.json()
}

// --- auth (Phase 1): Django session login -------------------------

export function getMe() {
  return request('/api/auth/me/')
}

export function setupOwner(username, password, setupToken) {
  return request('/api/auth/setup/', {
    method: 'POST',
    body: JSON.stringify({
      username,
      password,
      setup_token: setupToken,
    }),
  })
}

export function login(username, password) {
  return request('/api/auth/login/', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

export function logout() {
  return request('/api/auth/logout/', { method: 'POST' })
}

export function listModels() {
  return request('/api/models/')
}

export function sendChat(
  message,
  conversationId,
  model,
  agent = false,
  coding = false,
  confirmCommands = false
) {
  return request('/api/chat/', {
    method: 'POST',
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      model,
      agent,
      coding,
      confirm_commands: confirmCommands,
    }),
  })
}

export function listConversations() {
  return request('/api/conversations/')
}

export function getConversation(id) {
  return request(`/api/conversations/${id}/`)
}

export function deleteConversation(id) {
  return request(`/api/conversations/${id}/delete/`, { method: 'DELETE' })
}

export function listMemories() {
  return request('/api/memories/')
}

export function confirmMemory(id) {
  return request(`/api/memories/${id}/confirm/`, { method: 'POST' })
}

export function rejectMemory(id) {
  return request(`/api/memories/${id}/reject/`, { method: 'POST' })
}

export function deleteMemory(id) {
  return request(`/api/memories/${id}/delete/`, { method: 'DELETE' })
}
