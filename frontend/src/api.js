// API client: every call the UI makes to the Django backend lives here.
// All URLs are relative (/api/...) — Vite's dev proxy forwards them to
// Django on :8000, and in production Django serves this app itself, so
// the same paths work in both worlds. The browser never sees an AI key.

export const MODELS = [
  { id: 'llama-3.3-70b-versatile', label: 'Llama 3.3 70B' },
  { id: 'openai/gpt-oss-120b', label: 'GPT OSS 120B' },
  { id: 'openai/gpt-oss-20b', label: 'GPT OSS 20B' },
  { id: 'meta-llama/llama-4-scout-17b-16e-instruct', label: 'Llama 4 Scout' },
  { id: 'qwen/qwen3-32b', label: 'Qwen3 32B' },
  { id: 'llama-3.1-8b-instant', label: 'Llama 3.1 8B' },
]

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

export function sendChat(message, conversationId, model) {
  return request('/api/chat/', {
    method: 'POST',
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      model,
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
