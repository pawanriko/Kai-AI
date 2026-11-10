import { useEffect, useState } from 'react'

import {
  confirmMemory,
  deleteMemory,
  listMemories,
  rejectMemory,
} from '../api'

// The Memory view (Phase 1 Step 6): facts KAI extracted land as
// SUGGESTIONS first — they only reach future system prompts after
// the user confirms them here. Confirmed facts can be forgotten;
// suggestions can be confirmed or rejected.
export default function MemoryPanel() {
  const [memories, setMemories] = useState([])
  const [error, setError] = useState('')

  async function load() {
    try {
      const data = await listMemories()
      setMemories(data.memories)
    } catch {
      setError('Could not load memory — is Django running?')
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function confirm(id) {
    await confirmMemory(id)
    setMemories((prev) =>
      prev.map((m) => (m.id === id ? { ...m, status: 'confirmed' } : m))
    )
  }

  async function reject(id) {
    await rejectMemory(id)
    setMemories((prev) => prev.filter((m) => m.id !== id))
  }

  async function forget(id) {
    await deleteMemory(id)
    setMemories((prev) => prev.filter((m) => m.id !== id))
  }

  const suggested = memories.filter((m) => m.status === 'suggested')
  const confirmed = memories.filter((m) => m.status !== 'suggested')

  return (
    <div className="memory-panel">
      <h2>What KAI remembers</h2>
      {error && <p className="error-box">{error}</p>}

      {suggested.length > 0 && (
        <>
          <h3>Suggested — waiting for your OK</h3>
          <p className="muted">
            KAI inferred these from your chats. They are NOT used until
            you confirm them.
          </p>
          <ul className="memory-list">
            {suggested.map((m) => (
              <li key={m.id} className="memory-item">
                <span>{m.fact}</span>
                <span>
                  <button className="forget-btn" onClick={() => confirm(m.id)}>
                    Confirm
                  </button>{' '}
                  <button className="forget-btn" onClick={() => reject(m.id)}>
                    Reject
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      <h3>Confirmed facts</h3>
      {confirmed.length === 0 && !error && (
        <p className="muted">
          Nothing yet. Tell KAI something durable — your name, your college,
          an exam date — confirm the suggestion here, and KAI will remember
          it in every chat.
        </p>
      )}
      <ul className="memory-list">
        {confirmed.map((m) => (
          <li key={m.id} className="memory-item">
            <span>{m.fact}</span>
            <button className="forget-btn" onClick={() => forget(m.id)}>
              Forget
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
