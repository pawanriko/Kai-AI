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

export function listUsage() {
  return request('/api/usage/')
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

// Streaming chat (Phase 2): POST /api/chat/stream/ answers with
// NDJSON events — {"type":"chunk","text"} lines, then a final
// {"type":"done","conversation_id"} or {"type":"error","error"}.
// onChunk fires per text piece so the UI can grow the reply bubble
// live. Resolves with the done event; throws on any failure (a
// pre-stream HTTP error, or the error event once streaming began).
// Phase 2.1: an error event carrying "interrupted": true means the
// provider died mid-reply and the server SAVED the partial text
// flagged incomplete — the thrown error then has .interrupted and
// .conversationId set, so the UI keeps the bubble and labels it
// instead of dropping it as if nothing had been saved.
export async function sendChatStream(message, conversationId, model, onChunk) {
  const response = await fetch('/api/chat/stream/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken(),
    },
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      model,
    }),
  })
  if (!response.ok) {
    let message = `Request failed (${response.status})`
    try {
      const data = await response.json()
      if (data.error) message = data.error
    } catch {
      // keep the generic message
    }
    const error = new Error(message)
    error.status = response.status
    throw error
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let doneEvent = null
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop()
    for (const line of lines) {
      if (!line.trim()) continue
      const event = JSON.parse(line)
      if (event.type === 'chunk') onChunk(event.text)
      else if (event.type === 'done') doneEvent = event
      else if (event.type === 'error') {
        const error = new Error(event.error)
        if (event.interrupted) {
          error.interrupted = true
          error.conversationId = event.conversation_id
        }
        throw error
      }
    }
  }
  if (!doneEvent) throw new Error('Stream ended unexpectedly')
  return doneEvent
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

export function listMemories(params = {}) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value) query.set(key, value)
  }
  const suffix = query.toString()
  return request(suffix ? `/api/memories/?${suffix}` : '/api/memories/')
}

export function addMemory(fact, project) {
  return request('/api/memories/add/', {
    method: 'POST',
    body: JSON.stringify({ fact, project: project || '' }),
  })
}

export function setMemoryScope(id, project) {
  return request(`/api/memories/${id}/scope/`, {
    method: 'POST',
    body: JSON.stringify({ project }),
  })
}

export function listDuplicates() {
  return request('/api/memories/duplicates/')
}

export function mergeMemories(keepId, dropIds) {
  return request('/api/memories/merge/', {
    method: 'POST',
    body: JSON.stringify({ keep_id: keepId, drop_ids: dropIds }),
  })
}

// File downloads (memory export, research reports) are blobs, not
// JSON: fetch directly and hand the caller a Blob. Errors still
// surface as thrown Errors with a status, like request().
async function fetchBlob(path) {
  const response = await fetch(path)
  if (!response.ok) {
    const error = new Error(`Request failed (${response.status})`)
    error.status = response.status
    throw error
  }
  return response.blob()
}

export async function exportMemories(format, project) {
  const query = new URLSearchParams({ format })
  if (project) query.set('project', project)
  return fetchBlob(`/api/memories/export/?${query}`)
}

export function exportReport(conversationId) {
  return fetchBlob(`/api/conversations/${conversationId}/report/`)
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
