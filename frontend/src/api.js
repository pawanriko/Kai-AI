// API client: every call the UI makes to the Django backend lives here.
// All URLs are relative (/api/...) — Vite's dev proxy forwards them to
// Django on :8000, and in production Django serves this app itself, so
// the same paths work in both worlds. The browser never sees an AI key.

// The model catalogue comes from the backend (GET /api/models/): a
// list of providers, each with its models and a `configured` flag
// telling whether that provider's API key exists in the server's .env.
// A picker choice is encoded as "provider::model".

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
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
    throw new Error(message)
  }
  if (response.status === 204) return null
  return response.json()
}

export function listModels() {
  return request('/api/models/')
}

export function sendChat(
  message,
  conversationId,
  model,
  agent = false,
  coding = false
) {
  return request('/api/chat/', {
    method: 'POST',
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      model,
      agent,
      coding,
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

export function deleteMemory(id) {
  return request(`/api/memories/${id}/delete/`, { method: 'DELETE' })
}
